"""Deterministic venue collectors (no model): page structure and ticketing-platform endpoints.

`cards`        a listing page whose events are repeated HTML elements. The source names CSS selectors:
               cards: {item, title, date, time, link, support, venue, price, genre, description}
               Each value is "selector" (element text) or "selector@attr" (attribute); "@attr" alone
               reads the item itself. `title` may match several elements (joined with " / ").
               Dates are read from the date text (ISO, "Nov 6", "Friday October 30 2026", "11/06");
               a missing year is the next occurrence. With `run: true` a printed range becomes one
               production (start .. run_end), "Through <date>" meaning now playing.
`venuepilot`   VenuePilot's public widget API (GraphQL), by account id.
`ticketweb_wp` TicketWeb's "event-discovery" WordPress plugin: the calendar's admin-ajax call, with the
               nonce read from the calendar page each run.

Every collector reports a basis in stats["warnings"] when it skips items, so a markup change shows up
as warnings and a falling count rather than silence."""
import datetime as dt
import html
import json
import re
from urllib.parse import urljoin

import soupsieve
from bs4 import BeautifulSoup

from .. import config, fetch
from ..normalize import TZ, clean_text

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
ISO_RE = re.compile(r"(20\d\d)-(\d\d)-(\d\d)(?:[ T](\d\d):(\d\d))?")
MDY_RE = re.compile(rf"\b{MON}\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(20\d\d))?", re.I)
DMY_RE = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{MON}(?:,?\s+(20\d\d))?", re.I)
NUM_RE = re.compile(r"\b(\d{1,2})[/.](\d{1,2})(?:[/.](20\d\d|\d\d))?\b")
TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d\d))?\s*([ap])\.?m\.?\b", re.I)
SHOW_TIME_RE = re.compile(r"(?:show|music|starts?|begins?|concert|performance)[^0-9]{0,20}(\d{1,2})(?::(\d\d))?\s*([ap])\.?m", re.I)
BARE_TIME_RE = re.compile(r"\b(\d{1,2}):(\d\d)\b")


def _today():
    return dt.datetime.now(TZ).date()


def _infer_year(month, day, today, year=None):
    if year:
        year = int(year)
        return year + 2000 if year < 100 else year
    y = today.year
    try:
        d = dt.date(y, month, day)
    except ValueError:
        return y
    return y + 1 if d < today - dt.timedelta(days=60) else y


def find_dates(text: str, today=None, numeric=False) -> list[dt.date]:
    """Every calendar date printed in `text`, in order of appearance."""
    today = today or _today()
    hits = []
    for m in ISO_RE.finditer(text):
        hits.append((m.start(), int(m.group(1)), int(m.group(2)), int(m.group(3))))
    for m in MDY_RE.finditer(text):
        mo, d = MONTHS[m.group(1).lower()[:3]], int(m.group(2))
        hits.append((m.start(), _infer_year(mo, d, today, m.group(3)), mo, d))
    for m in DMY_RE.finditer(text):
        mo, d = MONTHS[m.group(2).lower()[:3]], int(m.group(1))
        if not any(abs(h[0] - m.start()) < 12 for h in hits):
            hits.append((m.start(), _infer_year(mo, d, today, m.group(3)), mo, d))
    if numeric and not hits:
        for m in NUM_RE.finditer(text):
            mo, d = int(m.group(1)), int(m.group(2))
            if 1 <= mo <= 12 and 1 <= d <= 31:
                hits.append((m.start(), _infer_year(mo, d, today, m.group(3)), mo, d))
    out = []
    for _, y, mo, d in sorted(hits):
        try:
            x = dt.date(y, mo, d)
        except ValueError:
            continue
        if x not in out:
            out.append(x)
    return out


def find_time(text: str):
    """(hour, minute) of the show, preferring a time labelled show/music/starts over doors."""
    m = SHOW_TIME_RE.search(text) or TIME_RE.search(text)
    if m:
        h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3).lower()
        if h > 12 or mi > 59:
            return None
        return (h % 12 + (12 if ap == "p" else 0), mi)
    m = ISO_RE.search(text)
    if m and m.group(4):
        return int(m.group(4)), int(m.group(5))
    m = BARE_TIME_RE.search(text)
    if m and 1 <= int(m.group(1)) <= 11:
        return int(m.group(1)) + 12, int(m.group(2))  # an evening listing that omits pm
    return None


def _when(d: dt.date, t):
    if t:
        return dt.datetime(d.year, d.month, d.day, t[0], t[1], tzinfo=TZ)
    return d.isoformat()


def _field(el, spec):
    """Text (or attribute) of the elements `spec` selects inside `el` ("." or "" selects `el` itself)."""
    if not spec:
        return []
    sel, _, attr = spec.partition("@")
    nodes = el.select(sel) if sel and sel != "." else [el]
    vals = []
    for n in nodes:
        v = n.get(attr) if attr else n.get_text(" ")
        v = clean_text(html.unescape(" ".join(v) if isinstance(v, list) else (v or "")))
        if v and v not in vals:
            vals.append(v)
    return vals


def _one(el, spec, joiner=" "):
    return joiner.join(_field(el, spec))


def _closest(el, selector):
    return next((p for p in el.parents if getattr(p, "name", None) and soupsieve.match(selector, p)), None)


def _get(it, c, name, joiner=" "):
    """Field `name` of a card: selector (c[name]) and/or a regex over the card text (c[name + "_re"],
    group 1), then an optional strip regex (c[name + "_strip"])."""
    v = _one(it, c.get(name), joiner) if c.get(name) else ""
    if not v and c.get(name + "_re"):
        m = re.search(c[name + "_re"], it.get_text("\n"), re.I | re.M)
        v = clean_text(m.group(1)) if m else ""
    if v and c.get(name + "_strip"):
        v = clean_text(re.sub(c[name + "_strip"], "", v, flags=re.I))
    return v


def collect_cards(source: dict, stats: dict) -> list[dict]:
    c = source["cards"]
    today = _today()
    out, seen = [], set()
    urls = source.get("urls") or [source["url"]]
    for url in urls:
        r = fetch.get(url, stats=stats)
        soup = BeautifulSoup(r.content, "html.parser")  # bytes: honours the page's meta charset
        items = soup.select(c["item"])
        stats["items"] = stats.get("items", 0) + len(items)
        if not items:
            stats.setdefault("warnings", []).append(f"no items match {c['item']!r} on {url}")
        for it in items:
            title = _get(it, c, "title", " / ")
            if not title or (c.get("skip") and re.search(c["skip"], title, re.I)):
                continue
            scope = (_closest(it, c["date_scope"]) or it) if c.get("date_scope") else it
            date_text = (_get(scope, c, "date") if c.get("date") or c.get("date_re") else "") or it.get_text(" ")
            dates = find_dates(date_text, today, numeric=c.get("numeric_dates", False))
            if not dates:
                stats.setdefault("warnings", []).append(f"no date: {title[:60]}")
                continue
            t = find_time(_get(it, c, "time") if c.get("time") or c.get("time_re") else date_text)
            link = _get(it, c, "link") if (c.get("link") or c.get("link_re")) else (_field(it, "a@href") or [""])[0]
            if link and c.get("link_tpl"):
                link = c["link_tpl"].format(link)
            link = urljoin(r.url, link.split()[0]) if link else url
            support = _get(it, c, "support", ", ")
            venue = _get(it, c, "venue")
            desc = " | ".join(x for x in (support and f"with {support}", _get(it, c, "description")) if x)
            ev = {"title": title, "url": link, "description": desc[:1500], "price": _get(it, c, "price")[:80],
                  "tags": _field(it, c.get("genre")) if c.get("genre") else [],
                  "performers": [p for p in [title] + [s.strip() for s in support.split(",")] if p] if support else [],
                  "category": source.get("category", "music")}
            if venue:
                ev["venue"] = venue
            for pat, city in (source.get("city_in_title") or {}).items():
                if re.search(pat, title + " " + venue, re.I):
                    ev["city"] = city
            run = c.get("run")
            if run == "auto":
                run = len(dates) > 1 and dates[-1] > dates[0]
            if run:
                first, last = dates[0], dates[-1]
                if last < today:
                    continue
                now_playing = first < today or re.search(rf"\b(?:through|thru|until)\s+(?:\w+,?\s+)?{MON}\s+\d", date_text, re.I)
                start = today if now_playing else first
                ev.update(start=start.isoformat() if now_playing else _when(start, t), run_end=last.isoformat(),
                          tags=ev["tags"] + ["theater-run"],
                          description=clean_text(f"{'Now playing; ' if now_playing else ''}run {date_text}; {desc}").strip("; "))
            else:
                if dates[0] < today - dt.timedelta(days=1):
                    continue
                ev["start"] = _when(dates[0], t)
            key = (title.lower(), str(ev["start"]))
            if key in seen:
                continue  # the same listing printed twice (desktop and mobile menus)
            seen.add(key)
            out.append(ev)
    return out


# ----------------------------------------------------------------------------- VenuePilot
VP_QUERY = """query ($accountIds: [Int!]!, $startDate: String!, $endDate: String, $page: Int, $limit: Int) {
  paginatedEvents(arguments: {accountIds: $accountIds, startDate: $startDate, endDate: $endDate, page: $page, limit: $limit}) {
    collection { id name date doorTime startTime endTime minimumAge promoter support description status ticketsUrl
                 venue { name } artists { name } }
    metadata { currentPage totalPages }
  }
}"""


def collect_venuepilot(source: dict, stats: dict) -> list[dict]:
    today = _today()
    end = today + dt.timedelta(days=config.HORIZON_DAYS)
    out = []
    page, pages = 1, 1
    while page <= min(pages, 10):
        body = {"query": VP_QUERY, "variables": {"accountIds": [int(a) for a in source["account_ids"]],
                                                "startDate": today.isoformat(), "endDate": end.isoformat(),
                                                "page": page, "limit": 100}}
        r = fetch.get("https://www.venuepilot.co/graphql", method="POST", json_body=body, stats=stats,
                      headers={"Content-Type": "application/json", "Origin": source.get("site") or source["url"]})
        try:
            d = r.json()["data"]["paginatedEvents"]
        except (ValueError, KeyError, TypeError):
            raise fetch.FetchError(f"venuepilot: unexpected response {r.text[:160]!r}", kind="format")
        for e in d.get("collection") or []:
            if not e.get("name") or not e.get("date"):
                continue
            t = e.get("startTime") or e.get("doorTime")
            start = f"{e['date']}T{t[:5]}" if t else e["date"]
            support = clean_text(e.get("support") or "")
            desc = clean_text(re.sub(r"<[^>]+>", " ", e.get("description") or ""))
            out.append({
                "title": clean_text(e["name"]),
                "start": start,
                "venue": clean_text((e.get("venue") or {}).get("name") or "") or None,
                "url": e.get("ticketsUrl") or source["url"],
                "ticket_url": e.get("ticketsUrl"),
                "performers": [clean_text(a["name"]) for a in (e.get("artists") or []) if a.get("name")],
                "description": clean_text(" | ".join(x for x in (support and f"with {support}", e.get("promoter"), desc) if x))[:1500],
                "status": "cancelled" if str(e.get("status") or "").lower() in ("cancelled", "canceled") else "scheduled",
                "source_event_id": f"venuepilot:{e.get('id')}",
            })
        pages = int((d.get("metadata") or {}).get("totalPages") or 1)
        page += 1
    return out


# ----------------------------------------------------------------------------- TicketWeb WordPress plugin
NONCE_RE = re.compile(r"action:\s*'get_events_for_calendar',\s*nonce:\s*'([0-9a-f]+)'")
PARAMS_RE = re.compile(r"action:\s*'get_events_for_calendar'.*?params:\s*'(\{.*?\})'", re.S)


def collect_ticketweb_wp(source: dict, stats: dict) -> list[dict]:
    page = fetch.get(source["url"], stats=stats)
    m = NONCE_RE.search(page.text)
    p = PARAMS_RE.search(page.text)
    if not m:
        raise fetch.FetchError("ticketweb_wp: calendar nonce not found on page", kind="format")
    ajax = urljoin(page.url, "/wp-admin/admin-ajax.php")
    today = _today()
    out, seen = [], set()
    # The calendar asks one month at a time; ask in 2-month windows across the horizon.
    start = today.replace(day=1)
    while start < today + dt.timedelta(days=config.HORIZON_DAYS):
        end = (start + dt.timedelta(days=62)).replace(day=1)
        r = fetch.get(ajax, method="POST", stats=stats, form_body={
            "action": "get_events_for_calendar", "nonce": m.group(1), "start": start.isoformat(),
            "end": end.isoformat(), "params": p.group(1) if p else "{}"},
            headers={"X-Requested-With": "XMLHttpRequest", "Referer": page.url})
        try:
            d = r.json()
        except ValueError:
            raise fetch.FetchError(f"ticketweb_wp: non-JSON from admin-ajax ({r.text[:80]!r})", kind="format")
        evs = d.get("events") if isinstance(d, dict) else d
        popups = BeautifulSoup(d.get("popupdata") or "", "html.parser") if isinstance(d, dict) else None
        for e in evs or []:
            title = clean_text(html.unescape(e.get("title") or ""))
            when = e.get("sortkey") or e.get("start")
            if not title or not when or str(when)[:10] < today.isoformat():
                continue
            key = (e.get("id"), str(when))
            if key in seen:
                continue
            seen.add(key)
            url, desc = source["url"], ""
            pop = popups.find(id=f"tw-event-dialog-{e.get('id')}") if popups else None
            if pop:
                a = pop.select_one(".tw-name a[href]")
                url = a["href"] if a else url
                desc = " | ".join(x for x in (_one(pop, ".tw-name-presenting"), _one(pop, ".tw-description")) if x)
            out.append({"title": title, "start": str(when).replace(" ", "T")[:16], "url": url,
                        "venue": (_one(pop, ".tw-venue-name") if pop else "") or None,
                        "description": desc[:1500], "source_event_id": f"ticketweb:{e.get('id')}"})
        start = end
    stats["ajax_events"] = len(out)
    return out
