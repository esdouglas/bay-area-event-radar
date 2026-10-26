"""Collectors for structured sources: iCalendar, JSON-LD pages (with optional link following),
The Events Calendar REST API, Squarespace event collections, Localist, Dice, Prekindle."""
import datetime as dt
import json
import re

import icalendar

from .. import config, fetch
from ..normalize import clean_text, parse_dt
from .common import jsonld_blocks, links, raw_from_schema, walk_events


def _horizon():
    return config.now_utc() + dt.timedelta(days=config.HORIZON_DAYS)


# ----------------------------------------------------------------------------- iCalendar
def collect_ics(source: dict, stats: dict) -> list[dict]:
    r = fetch.get(source["url"], stats=stats)
    cal = icalendar.Calendar.from_ical(r.content)
    out = []
    now = config.now_utc() - dt.timedelta(days=1)
    horizon = _horizon()
    for comp in cal.walk("VEVENT"):
        start = comp.get("DTSTART")
        if not start:
            continue
        s = start.dt
        if isinstance(s, dt.date) and not isinstance(s, dt.datetime):
            s = dt.datetime(s.year, s.month, s.day, 12, 0)
        sdt = parse_dt(s)
        if not sdt or sdt < now or sdt > horizon:
            continue
        if comp.get("RRULE"):
            continue  # recurring bases (weekly karaoke) are noise; the venue API expands real instances
        summary = clean_text(str(comp.get("SUMMARY", "")))
        if not summary:
            continue
        status = str(comp.get("STATUS", "CONFIRMED")).upper()
        desc = clean_text(str(comp.get("DESCRIPTION", "")))
        url = str(comp.get("URL", "")) or source.get("event_url_template", "").format(uid=str(comp.get("UID", ""))) or source.get("url")
        created = comp.get("CREATED")
        out.append({
            "title": summary,
            "start": sdt,
            "end": comp.get("DTEND").dt if comp.get("DTEND") else None,
            "venue": clean_text(str(comp.get("LOCATION", ""))) or None,
            "url": url,
            "description": desc,
            "status": "cancelled" if status == "CANCELLED" else "scheduled",
            "announced": created.dt.isoformat() if created is not None and hasattr(created, "dt") else None,
            "source_event_id": str(comp.get("UID", "")),
        })
    return out


# ----------------------------------------------------------------------------- JSON-LD pages
def _page_urls(source: dict) -> list[str]:
    urls = source.get("urls") or [source["url"]]
    out = []
    for u in urls:
        if "{page}" in u:
            for p in range(1, int(source.get("max_pages", 1)) + 1):
                out.append(u.format(page=p))
        else:
            out.append(u)
    return out


def collect_jsonld(source: dict, stats: dict) -> list[dict]:
    """Events from schema.org JSON-LD on listing pages, optionally following links to detail pages.

    source keys: url | urls, max_pages, follow (regex for detail links), max_follow, detail_ttl_hours,
                 stop_when_empty (default true), require_venue (drop events with no location name)
    """
    out = []
    seen_urls = set()
    horizon = _horizon()
    detail_links = []
    for page_url in _page_urls(source):
        r = fetch.get(page_url, stats=stats)
        html_text = r.text
        found = 0
        for ev in walk_events(jsonld_blocks(html_text)):
            raw = raw_from_schema(ev, page_url)
            if not raw["title"] or not raw["start"]:
                continue
            found += 1
            out.append(raw)
        stats["pages"] = stats.get("pages", 0) + 1
        if source.get("follow"):
            found_links = links(html_text, page_url, source["follow"])
            if source.get("follow_rewrite"):
                a, b = source["follow_rewrite"]
                found_links = [u.replace(a, b) for u in found_links]
            detail_links.extend(found_links)
        if found == 0 and source.get("stop_when_empty", True) and "{page}" in (source.get("url") or "") and len(_page_urls(source)) > 1:
            break
        # stop paging once we are past the horizon
        dates = [parse_dt(x["start"]) for x in out[-found:]] if found else []
        dates = [d for d in dates if d]
        if dates and min(dates) > horizon:
            break
    if detail_links:
        out.extend(_follow_details(source, detail_links, stats, have=[o.get("url") for o in out]))
    if source.get("require_venue"):
        out = [o for o in out if o.get("venue")]
    for o in out:
        if o.get("url") in seen_urls:
            continue
        seen_urls.add(o.get("url"))
    return out


def _follow_details(source, detail_links, stats, have):
    """Fetch detail pages (cached) and read their JSON-LD. Unseen links first, then stale ones."""
    ttl = float(source.get("detail_ttl_hours", 72))
    max_follow = int(source.get("max_follow", 60))
    have = set(h for h in have if h)
    results = []
    todo = []
    for u in detail_links:
        if u in have:
            continue
        c = fetch.cache_get("detail:" + u, max_age_hours=ttl)
        if c is not None:
            results.extend(c.get("events", []))
            stats["cached_details"] = stats.get("cached_details", 0) + 1
            continue
        todo.append(u)
    for u in todo[:max_follow]:
        try:
            r = fetch.get(u, stats=stats)
        except fetch.FetchError as e:
            stats.setdefault("detail_errors", []).append(f"{u}: {e}")
            continue
        evs = []
        for ev in walk_events(jsonld_blocks(r.text)):
            raw = raw_from_schema(ev, u)
            if raw["title"] and raw["start"]:
                if not raw.get("url"):
                    raw["url"] = u
                evs.append(_jsonable(raw))
        if not evs and source.get("detail_text_fallback"):
            evs = _detail_text_fallback(r.text, u, source)
        fetch.cache_put("detail:" + u, {"events": evs})
        results.extend(evs)
        stats["details"] = stats.get("details", 0) + 1
    if len(todo) > max_follow:
        stats["details_deferred"] = len(todo) - max_follow
    return results


def _detail_text_fallback(html_text, url, source):
    """Very small heuristic: <title> + first ISO-ish date in meta tags. Used only when a site has no JSON-LD."""
    m = re.search(r'<meta[^>]+(?:property|name)=["\'](?:event:start_time|og:start_time|startDate)["\'][^>]+content=["\']([^"\']+)', html_text, re.I)
    t = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.S | re.I)
    if m and t:
        return [{"title": clean_text(t.group(1)).split("|")[0].strip(), "start": m.group(1), "url": url}]
    return []


def _jsonable(raw):
    return {k: (v.isoformat() if isinstance(v, dt.datetime) else v) for k, v in raw.items()}


# ----------------------------------------------------------------------------- The Events Calendar REST
def collect_tribe(source: dict, stats: dict) -> list[dict]:
    base = source["url"].rstrip("/")
    out = []
    page = 1
    end = _horizon().strftime("%Y-%m-%d")
    while page <= int(source.get("max_pages", 20)):
        r = fetch.get(f"{base}/wp-json/tribe/events/v1/events",
                      params={"per_page": 50, "page": page, "start_date": config.now_utc().strftime("%Y-%m-%d"),
                              "end_date": end}, stats=stats)
        try:
            d = r.json()
        except ValueError:
            raise fetch.FetchError("tribe endpoint returned non-JSON", kind="format")
        evs = d.get("events", [])
        for e in evs:
            venue = e.get("venue") or {}
            if isinstance(venue, list):
                venue = venue[0] if venue else {}
            cats = [c.get("name") for c in (e.get("categories") or []) if c.get("name")]
            tags = [t.get("name") for t in (e.get("tags") or []) if t.get("name")]
            out.append({
                "title": clean_text(e.get("title")),
                "start": e.get("start_date"),
                "end": e.get("end_date"),
                "venue": clean_text(venue.get("venue") or ""),
                "city": clean_text(venue.get("city") or ""),
                "state": clean_text(venue.get("state") or venue.get("province") or ""),
                "address": clean_text(venue.get("address") or ""),
                "url": e.get("url"),
                "ticket_url": e.get("website"),
                "description": clean_text(re.sub(r"<[^>]+>", " ", e.get("description") or ""))[:1500],
                "price": clean_text(e.get("cost") or ""),
                "tags": cats + tags,
                "image": (e.get("image") or {}).get("url") if isinstance(e.get("image"), dict) else None,
                "source_event_id": str(e.get("id")),
                "announced": e.get("date_utc") or e.get("date"),
            })
        stats["pages"] = stats.get("pages", 0) + 1
        if page >= int(d.get("total_pages", 1)) or not evs:
            break
        page += 1
    return out


# ----------------------------------------------------------------------------- Squarespace events collection
def collect_squarespace(source: dict, stats: dict) -> list[dict]:
    url = source["url"]
    out = []
    offset = None
    for _ in range(int(source.get("max_pages", 6))):
        params = {"format": "json"}
        if offset:
            params["offset"] = offset
        r = fetch.get(url, params=params, stats=stats)
        try:
            d = r.json()
        except ValueError:
            raise fetch.FetchError("squarespace page is not a JSON collection", kind="format")
        items = d.get("upcoming") or d.get("items") or []
        for it in items:
            if not it.get("startDate"):
                continue
            loc = it.get("location") or {}
            out.append({
                "title": clean_text(it.get("title")),
                "start": it.get("startDate"),
                "end": it.get("endDate"),
                "venue": clean_text(loc.get("addressTitle") or "") or None,
                "address": clean_text(loc.get("addressLine1") or ""),
                "url": "https://" + re.sub(r"^https?://", "", source.get("site", url).split("/")[2] if "://" in source.get("site", url) else url.split("/")[2]) + it.get("fullUrl", ""),
                "description": clean_text(re.sub(r"<[^>]+>", " ", it.get("excerpt") or it.get("body") or ""))[:1500],
                "tags": (it.get("tags") or []) + (it.get("categories") or []),
                "image": it.get("assetUrl"),
                "source_event_id": it.get("id"),
                "announced": it.get("addedOn"),
            })
        stats["pages"] = stats.get("pages", 0) + 1
        pag = d.get("pagination") or {}
        if not pag.get("nextPage"):
            break
        offset = pag.get("nextPageOffset")
    return out


# ----------------------------------------------------------------------------- Localist
def collect_localist(source: dict, stats: dict) -> list[dict]:
    base = source["url"].rstrip("/")
    out = []
    page = 1
    while page <= int(source.get("max_pages", 15)):
        r = fetch.get(f"{base}/api/2/events", params={"days": config.HORIZON_DAYS, "pp": 100, "page": page,
                                                      **(source.get("params") or {})}, stats=stats)
        d = r.json()
        for w in d.get("events", []):
            e = w.get("event", {})
            for inst in e.get("event_instances", [])[:12]:
                i = inst.get("event_instance", {})
                f = e.get("filters") or {}
                tags = [x.get("name") for grp in f.values() for x in grp if isinstance(x, dict) and x.get("name")]
                out.append({
                    "title": clean_text(e.get("title")),
                    "start": i.get("start"),
                    "end": i.get("end"),
                    "venue": clean_text(e.get("location_name") or ""),
                    "address": clean_text(e.get("address") or ""),
                    "url": e.get("localist_url") or e.get("url"),
                    "ticket_url": e.get("ticket_url"),
                    "description": clean_text(e.get("description_text") or "")[:1500],
                    "price": clean_text(e.get("ticket_cost") or ""),
                    "tags": tags,
                    "image": e.get("photo_url"),
                    "source_event_id": f"{e.get('id')}:{i.get('id')}",
                    "announced": e.get("created_at"),
                })
        stats["pages"] = stats.get("pages", 0) + 1
        pg = d.get("page", {})
        if not pg.get("next_page"):
            break
        page = pg["next_page"]
    return out


# ----------------------------------------------------------------------------- Dice (Next.js data)
def collect_dice(source: dict, stats: dict) -> list[dict]:
    out = []
    for url in source.get("urls") or [source["url"]]:
        r = fetch.get(url, stats=stats)
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
        if not m:
            raise fetch.FetchError("no __NEXT_DATA__ on Dice page", kind="format")
        d = json.loads(m.group(1))
        evs = (d.get("props", {}).get("pageProps", {}) or {}).get("events") or []
        for e in evs:
            dates = e.get("dates") or {}
            venues = e.get("venues") or []
            v = venues[0] if venues else {}
            city = ""
            addr = v.get("address") or ""
            if isinstance(v.get("city"), dict):
                city = v["city"].get("name", "")
            elif isinstance(v.get("city"), str):
                city = v["city"]
            out.append({
                "title": clean_text(e.get("name")),
                "start": dates.get("event_start_date"),
                "end": dates.get("event_end_date"),
                "venue": clean_text(v.get("name") or ""),
                "city": clean_text(city),
                "address": clean_text(addr),
                "url": f"https://dice.fm/event/{e.get('id')}",
                "price": clean_text(str((e.get("price") or {}).get("amount", "") or "")),
                "tags": [t for t in [e.get("event_tag")] if t],
                "status": "cancelled" if str(e.get("status", "")).lower() == "cancelled" else "scheduled",
                "image": (e.get("images") or {}).get("landscape") if isinstance(e.get("images"), dict) else None,
                "source_event_id": e.get("id"),
                "announced": dates.get("announcement_date"),
            })
        stats["pages"] = stats.get("pages", 0) + 1
    return out
