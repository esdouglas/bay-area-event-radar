"""Aggregator collectors: Songkick metro pages, Eventbrite (official API, and the web search API where
reachable), allevents.in. Aggregators are recall insurance: they list rooms we have never named."""
import datetime as dt
import os
import re

from .. import config, fetch
from ..normalize import clean_text, parse_dt
from .common import jsonld_blocks, raw_from_schema, walk_events


# ----------------------------------------------------------------------------- Songkick
def collect_songkick(source: dict, stats: dict) -> list[dict]:
    """Songkick metro-area or venue pages carry 50 MusicEvent JSON-LD objects per page.

    Songkick answers 406 to bursts, so pacing is enforced in fetch.HOST_PACING and 406s are retried."""
    out = []
    url = source["url"]
    horizon = config.now_utc() + dt.timedelta(days=config.HORIZON_DAYS)
    served, refused = [], []
    for page in range(1, int(source.get("max_pages", 25)) + 1):
        try:
            r = fetch.get(url, params={"page": page}, stats=stats, retries=1)
        except fetch.FetchError as e:
            if e.kind == "blocked":
                raise
            refused.append(page)
            if len(refused) >= 6 and not served:
                raise fetch.FetchError("no Songkick page served (CDN cold)", kind="partial")
            continue
        served.append(page)
        found = 0
        last = None
        for ev in walk_events(jsonld_blocks(r.text)):
            raw = raw_from_schema(ev, url)
            if not raw["title"] or not raw["start"]:
                continue
            raw["title"] = re.sub(r"\s+@\s+.*$", "", raw["title"])  # "Artist @ Venue" -> "Artist"
            raw["url"] = (raw.get("url") or "").split("?")[0]
            out.append(raw)
            found += 1
            last = parse_dt(raw["start"])
        stats["pages"] = stats.get("pages", 0) + 1
        if found == 0:
            break
        if last and last > horizon:
            break
    stats["songkick_pages_served"] = served
    stats["songkick_pages_refused"] = refused
    if refused:
        stats.setdefault("warnings", []).append(
            f"partial: Songkick served {len(served)} pages, refused {len(refused)} (HTTP 406 on CDN misses); coverage improves across runs")
    return out


# ----------------------------------------------------------------------------- Eventbrite official API
EB_API = "https://www.eventbriteapi.com/v3"


def _eb_token():
    return os.environ.get("EVENTBRITE_TOKEN", "").strip()


def _eb_event_to_raw(e: dict) -> dict:
    venue = e.get("venue") or {}
    addr = venue.get("address") or {}
    cat = (e.get("category") or {}).get("name")
    sub = (e.get("subcategory") or {}).get("name")
    fmt = (e.get("format") or {}).get("name")
    return {
        "title": clean_text((e.get("name") or {}).get("text")),
        "start": (e.get("start") or {}).get("local"),
        "end": (e.get("end") or {}).get("local"),
        "venue": clean_text(venue.get("name") or ""),
        "city": clean_text(addr.get("city") or ""),
        "state": clean_text(addr.get("region") or ""),
        "address": clean_text(addr.get("address_1") or ""),
        "url": e.get("url"),
        "description": clean_text((e.get("summary") or (e.get("description") or {}).get("text") or ""))[:1500],
        "tags": [t for t in (cat, sub, fmt) if t],
        "status": {"canceled": "cancelled", "postponed": "postponed"}.get(e.get("status"), "scheduled"),
        "image": (e.get("logo") or {}).get("url") if e.get("logo") else None,
        "source_event_id": e.get("id"),
        "announced": e.get("created") or e.get("published"),
        "price": "free" if e.get("is_free") else "",
    }


def collect_eventbrite_api(source: dict, stats: dict) -> list[dict]:
    """List public events for organizers / venues / explicit event ids via the official API.

    source keys: organizers: [ids], venues: [ids], events: [ids]. Needs EVENTBRITE_TOKEN."""
    token = _eb_token()
    if not token:
        raise fetch.FetchError("EVENTBRITE_TOKEN not set", kind="config")
    headers = {"Authorization": f"Bearer {token}"}
    out = []

    def paged(path):
        page = 1
        while True:
            r = fetch.get(f"{EB_API}{path}", params={"status": "live", "order_by": "start_asc", "expand": "venue,category,subcategory,format", "page": page},
                          headers=headers, stats=stats)
            d = r.json()
            for e in d.get("events", []):
                out.append(_eb_event_to_raw(e))
            pg = d.get("pagination") or {}
            if not pg.get("has_more_items") or page >= 10:
                break
            page += 1

    for oid in source.get("organizers") or []:
        paged(f"/organizers/{oid}/events/")
    for vid in source.get("venues") or []:
        paged(f"/venues/{vid}/events/")
    for eid in source.get("events") or []:
        r = fetch.get(f"{EB_API}/events/{eid}/", params={"expand": "venue,category,subcategory,format"}, headers=headers, stats=stats)
        out.append(_eb_event_to_raw(r.json()))
    return out


# ----------------------------------------------------------------------------- Eventbrite web search API
EB_WEB_SEARCH = "https://www.eventbrite.com/api/v3/destination/search/"


def collect_eventbrite_web(source: dict, stats: dict) -> list[dict]:
    """Eventbrite's own front-end search endpoint. Rich (venue, organizer, dates) but Eventbrite blocks
    datacenter IPs such as GitHub runners with HTTP 405; when that happens the run records 'blocked'.

    source keys: places: [eventbrite place ids], tags: [EventbriteCategory/103, ...], max_pages"""
    r = fetch.get("https://www.eventbrite.com/d/ca--oakland/music/", stats=stats)
    csrf = fetch._session.cookies.get("csrftoken")
    if not csrf:
        raise fetch.FetchError("no csrftoken cookie from Eventbrite (blocked?)", kind="blocked")
    out = []
    for place in source.get("places") or []:
        for tag in source.get("tags") or [None]:
            for page in range(1, int(source.get("max_pages", 15)) + 1):
                es = {"dates": "current_future", "dedup": True, "places": [str(place)], "page": page,
                      "page_size": 50, "online_events_only": False}
                if tag:
                    es["tags"] = [tag]
                body = {"event_search": es, "expand.destination_event": ["primary_venue", "primary_organizer", "ticket_availability"]}
                rr = fetch.get(EB_WEB_SEARCH, method="POST", json_body=body, stats=stats,
                               headers={"X-CSRFToken": csrf, "Referer": "https://www.eventbrite.com/d/ca--oakland/music/",
                                        "Content-Type": "application/json"})
                d = rr.json()
                evs = d.get("events", {})
                for e in evs.get("results", []):
                    v = e.get("primary_venue") or {}
                    addr = v.get("address") or {}
                    org = e.get("primary_organizer") or {}
                    out.append({
                        "title": clean_text(e.get("name")),
                        "start": f"{e.get('start_date')}T{e.get('start_time') or '00:00'}",
                        "end": f"{e.get('end_date')}T{e.get('end_time')}" if e.get("end_date") and e.get("end_time") else None,
                        "venue": clean_text(v.get("name") or ""),
                        "city": clean_text(addr.get("city") or ""),
                        "state": clean_text(addr.get("region") or ""),
                        "address": clean_text(addr.get("address_1") or ""),
                        "url": e.get("url"),
                        "description": clean_text(e.get("summary") or "")[:1200],
                        "tags": [t.get("display_name") for t in (e.get("tags") or []) if isinstance(t, dict) and t.get("display_name")]
                                + ([f"organizer:{org.get('name')}"] if org.get("name") else []),
                        "image": (e.get("image") or {}).get("url") if isinstance(e.get("image"), dict) else None,
                        "source_event_id": e.get("id"),
                        "price": "free" if e.get("is_free") else "",
                    })
                stats["pages"] = stats.get("pages", 0) + 1
                pg = evs.get("pagination") or {}
                if page >= int(pg.get("page_count", 1)):
                    break
    return out


# ----------------------------------------------------------------------------- allevents.in
def collect_allevents(source: dict, stats: dict) -> list[dict]:
    out = []
    for url in source.get("urls") or [source["url"]]:
        r = fetch.get(url, stats=stats)
        for ev in walk_events(jsonld_blocks(r.text)):
            raw = raw_from_schema(ev, url)
            if raw["title"] and raw["start"]:
                out.append(raw)
        stats["pages"] = stats.get("pages", 0) + 1
    return out
