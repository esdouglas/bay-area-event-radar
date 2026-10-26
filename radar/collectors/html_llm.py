"""Generic page collector: readable text -> model -> structured events, cached by content hash.

This is what lets the registry carry venues that publish only a human-readable calendar (Bluegrass
Signal, KALX, SFFMC, Down Home Music, most theaters). The model is only called when the page text
changes, so an unchanged page costs nothing on later runs. Without an LLM provider the collector
falls back to a date-line heuristic so the source is still exercised and health-checked.
"""
import datetime as dt
import json
import re

from .. import config, fetch, llm
from ..normalize import clean_text
from .common import visible_text

SYSTEM = """You extract upcoming live events from the text of a web page. Return ONLY a JSON object:
{"events":[{"title":str,"start":"YYYY-MM-DDTHH:MM" or "YYYY-MM-DD","end":str|null,"venue":str|null,
 "city":str|null,"url":str|null,"performers":[str],"description":str|null,"price":str|null,"category":"music|theater|dance|comedy|film|art|talk|other"}]}
Rules: one entry per performance date (expand date ranges and multi-day runs into separate dates only if dates are listed; otherwise give the first date and put the run in description).
Use the year in context; today's date is given. Never invent dates: if a listing has no resolvable date, omit it.
Keep titles as printed (headliner + support). Include recurring weekly events only once. Do not include past events."""


def _chunks(text: str, size: int = 28000):
    if len(text) <= size:
        yield text
        return
    lines = text.split("\n")
    buf = []
    n = 0
    for l in lines:
        buf.append(l)
        n += len(l) + 1
        if n >= size:
            yield "\n".join(buf)
            buf, n = [], 0
    if buf:
        yield "\n".join(buf)


def _llm_extract(text: str, source: dict, stats: dict) -> list[dict]:
    today = dt.datetime.now(dt.timezone.utc).astimezone().strftime("%Y-%m-%d (%A)")
    out = []
    for i, chunk in enumerate(_chunks(text)):
        user = (f"Today is {today}. Source: {source.get('name')} ({source['url']}). "
                f"Default venue if the page is a single venue's calendar: {source.get('venue', {}).get('name') or 'unknown'}.\n"
                f"Page text:\n\n{chunk}")
        raw = llm.complete(SYSTEM, user, tier="fast", max_tokens=6000, purpose=f"extract:{source['id']}")
        try:
            d = llm.parse_json(raw)
        except (ValueError, json.JSONDecodeError):
            stats.setdefault("warnings", []).append(f"chunk {i}: model returned non-JSON")
            continue
        for e in d.get("events", []):
            if e.get("title") and e.get("start"):
                out.append({
                    "title": clean_text(e["title"]),
                    "start": e["start"],
                    "end": e.get("end"),
                    "venue": clean_text(e.get("venue") or "") or None,
                    "city": clean_text(e.get("city") or "") or None,
                    "url": e.get("url") or source["url"],
                    "performers": [clean_text(p) for p in (e.get("performers") or []) if p],
                    "description": clean_text(e.get("description") or ""),
                    "price": clean_text(e.get("price") or ""),
                    "category": e.get("category") or source.get("category") or "music",
                    "model_extracted": True,
                })
        stats["llm_chunks"] = stats.get("llm_chunks", 0) + 1
    return out


MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
DATE_LINE = re.compile(rf"\b(?:(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?,?\s+)?((?:{MONTHS})[a-z]*\.?)\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?", re.I)


JUNK_TITLE = re.compile(r"^(?:\d{1,2}(?::\d{2})?\s*(?:am|pm)|\d{4}|doors?\b.*|show(?:time)?\b.*|(?:get|buy)\s+tickets?.*|tickets?|sold out|more info|rsvp|free|all ages|\d{1,2}\+|[\W\d]+)$", re.I)


def _plausible_title(title: str, source: dict) -> bool:
    from ..normalize import VENUE_ALIASES, fold
    t = clean_text(title)
    if len(t) < 4 or len(t) > 140 or JUNK_TITLE.match(t):
        return False
    f = fold(t)
    if f in VENUE_ALIASES or f in {fold(v) for v in VENUE_ALIASES.values()} or f == fold(source.get("venue", {}).get("name") or "~"):
        return False
    if len(re.sub(r"[^a-z]", "", f)) < 4:
        return False
    return True


def _heuristic_extract(text: str, source: dict) -> list[dict]:
    """No model available: pair 'Month Day' lines with the nearest following non-date line."""
    out = []
    lines = text.split("\n")
    today = dt.date.today()
    for i, line in enumerate(lines):
        m = DATE_LINE.search(line)
        if not m or len(line) > 90:
            continue
        mon, day, year = m.group(1), int(m.group(2)), m.group(3)
        try:
            mnum = [k for k, v in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]) if mon.lower().startswith(v)][0] + 1
            y = int(year) if year else today.year
            d = dt.date(y, mnum, day)
            if not year and d < today - dt.timedelta(days=30):
                d = dt.date(y + 1, mnum, day)
        except (ValueError, IndexError):
            continue
        rest = DATE_LINE.sub("", line).strip(" -–—:,|")
        rest = re.sub(r"^\s*(?:\d{1,2}(?::\d{2})?\s*(?:am|pm)\s*[:\-–]?\s*)", "", rest, flags=re.I)
        candidates = [rest] + [l for l in lines[i + 1:i + 4] if not DATE_LINE.search(l)]
        title = next((c for c in candidates if _plausible_title(c, source)), "")
        if title:
            out.append({"title": clean_text(title), "start": d.isoformat(), "url": source["url"], "heuristic": True})
    return out


def collect_html(source: dict, stats: dict) -> list[dict]:
    urls = source.get("urls") or [source["url"]]
    source = dict(source, url=source.get("url") or urls[0])
    out = []
    for url in urls:
        r = fetch.get(url, stats=stats)
        text = visible_text(r.text, max_chars=int(source.get("max_chars", 90000)))
        if source.get("start_marker") and source["start_marker"] in text:
            text = text.split(source["start_marker"], 1)[1]
        if source.get("end_marker") and source["end_marker"] in text:
            text = text.split(source["end_marker"], 1)[0]
        h = fetch.text_hash(text)
        cache_key = f"html:{source['id']}:{url}"
        cached = fetch.cache_get(cache_key)
        if cached and cached.get("hash") == h and cached.get("mode") == ("llm" if llm.available() else "heuristic"):
            out.extend(cached.get("events", []))
            stats["cache_hits"] = stats.get("cache_hits", 0) + 1
            continue
        if llm.available():
            events = _llm_extract(text, source, stats)
            mode = "llm"
        else:
            events = _heuristic_extract(text, source)
            mode = "heuristic"
            stats.setdefault("warnings", []).append("no LLM provider: heuristic extraction only")
        fetch.cache_put(cache_key, {"hash": h, "mode": mode, "events": events, "chars": len(text)})
        out.extend(events)
        stats["pages"] = stats.get("pages", 0) + 1
    return out
