"""Collector method `theater_run`: one inventory event per production, not per performance.

Reads a season/index page, follows show links (follow regex), and on each show page takes the run
from (1) schema.org Event JSON-LD performances (min upcoming start .. max start), else (2) a printed
range like "Sep 26 - Nov 28, 2026", else (3) "Starting Date: November 28, 2026". A production that
is already running is filed under today's date with "now playing" in the description, so it stays
actionable. No model involved."""
import datetime as dt
import html
import re

from .. import fetch
from ..normalize import TZ, clean_text, parse_dt
from .common import jsonld_blocks, links, visible_text, walk_events

MON = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
RANGE = re.compile(rf"({MON}\s+\d{{1,2}})(?:,?\s+(20\d\d))?\s*(?:-|–|—|to|through)\s*({MON}\s+)?(\d{{1,2}}),?\s+(20\d\d)", re.I)
START = re.compile(rf"(?:Starting Date|Opens|Begins|Previews? begin)\s*:?\s*({MON}\s+\d{{1,2}},?\s+20\d\d)", re.I)


def _d(s):
    d = parse_dt(re.sub(r"(?i)sept", "Sep", s))
    return d.date() if d else None


def _title(page_html, fallback):
    m = re.search(r'<meta property="og:title" content="([^"]+)"', page_html)
    t = html.unescape(m.group(1)) if m else ""
    if not t:
        m = re.search(r"<h1[^>]*>(.*?)</h1>", page_html, re.S)
        t = re.sub(r"<[^>]+>", " ", m.group(1)) if m else fallback
    t = re.split(r"\s+[|–—-]\s+(?=[^|–—-]*(?:Theat|Playhouse|Official|Players|Company|Rep\b))", t)[0]
    return clean_text(t)


def collect_theater_run(source: dict, stats: dict) -> list[dict]:
    today = dt.datetime.now(TZ).date()
    idx = fetch.get(source["url"], stats=stats)
    show_links = links(idx.text, source["url"], source["follow"])[: int(source.get("max_follow", 20))]
    idx_text = ""
    by_order = {}
    if source.get("range_by_order"):
        # Nav menu prints each production's run in the same order as the show links (verified for
        # sfplayhouse.org 2026-10-28). Pair by position; the basis says so.
        rs, keys = [], []
        for m in RANGE.finditer(visible_text(idx.text, 60000)):
            y2 = m.group(5)
            key = (_d(f"{m.group(1)} {m.group(2) or y2}"), _d(f"{m.group(3) or m.group(1).split()[0]} {m.group(4)} {y2}"))
            if key not in keys:
                keys.append(key)
                rs.append(m.group(0))
        if len(rs) >= len(show_links):  # the menu block comes first; later promos repeat or add ranges
            by_order = dict(zip(show_links, rs[:len(show_links)]))
        else:
            stats.setdefault("warnings", []).append(f"range_by_order: {len(rs)} ranges for {len(show_links)} shows; skipped pairing")
    out = []
    for u in show_links:
        try:
            r = fetch.get(u, stats=stats)
        except fetch.FetchError as e:
            stats.setdefault("detail_errors", []).append(f"{u}: {e}")
            continue
        title = _title(r.text, u.rstrip("/").split("/")[-1].replace("-", " ").title())
        first = last = None
        evs = list(walk_events(jsonld_blocks(r.text)))
        perfs = sorted(p for p in (parse_dt(e.get("startDate")) for e in evs if e.get("startDate")) if p)
        ends = [p for p in (parse_dt(e.get("endDate")) for e in evs if e.get("endDate")) if p]
        basis = None
        if perfs:
            upcoming = [p for p in perfs if p.date() >= today]
            if not upcoming:
                continue
            first, last = upcoming[0], max(perfs + ends)
            basis = (f"{len(upcoming)} upcoming performances (JSON-LD)" if len(perfs) > 1
                     else f"run {first:%b %-d} - {last:%b %-d, %Y} (JSON-LD)")
        else:
            text = by_order.get(u) or visible_text(r.text, 30000)
            # Prefer the range printed nearest after the show's own title; site banners repeat the
            # current production's dates on every page.
            ms = list(RANGE.finditer(text))
            tl = title.lower()[:30]
            near = [x for x in ms if tl and tl in text[max(0, x.start() - 400):x.start()].lower()]
            m = (near[-1] if near else (ms[0] if len(set(x.group(0) for x in ms)) <= 1 or not ms else None)) if ms else None
            if near and len(near) > 1:
                m = max(near, key=lambda x: text[max(0, x.start() - 400):x.start()].lower().rfind(tl))
            if m:
                y2 = m.group(5)
                a = _d(f"{m.group(1)} {m.group(2) or y2}")
                b = _d(f"{m.group(3) or m.group(1).split()[0]} {m.group(4)} {y2}")
                if a and b and a > b and not m.group(2):
                    a = a.replace(year=a.year - 1)
                if a and b:
                    if b < today:
                        continue
                    first, last, basis = a, b, f"run {a:%b %-d} - {b:%b %-d, %Y} ({'season menu, paired by position' if u in by_order else 'printed range'})"
            if not first:
                m = START.search(text)
                if m and _d(m.group(1)):
                    first = _d(m.group(1))
                    basis = f"opens {first:%b %-d, %Y} (printed start date)"
        if not first and u in by_order:
            pass
        if not first:
            stats.setdefault("warnings", []).append(f"no dates found: {u}")
            continue
        start_date = first.date() if isinstance(first, dt.datetime) else first
        now_playing = start_date < today
        if now_playing:
            start_date = today
        start = first if isinstance(first, dt.datetime) and not now_playing else start_date.isoformat()
        end_d = last.date() if isinstance(last, dt.datetime) else last
        desc = f"{'Now playing; ' if now_playing else ''}{basis}" + (f"; closes {end_d:%b %-d, %Y}" if end_d else "")
        out.append({"title": title, "start": start, "url": u, "description": desc, "category": source.get("category", "theater"),
                    "tags": ["theater-run"], "run_end": end_d.isoformat() if end_d else None})
    return out
