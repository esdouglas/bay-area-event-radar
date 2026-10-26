"""Persistent inventory on disk (JSON, committed to git).

Why JSON files and not SQLite: the repository *is* the database between GitHub Actions runs, and text
files give readable diffs and survive merges. Everything is loaded into memory per run; the inventory
is a few thousand records, which is trivial.
"""
import datetime as dt
import json

from . import config
from .normalize import (TZ, clean_text, dedup_key, event_id, iso, local_date, norm_venue, parse_dt,
                        region_of, similar_titles, venue_key)


def _load(path, default):
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def _save(path, obj):
    config.ensure_dirs()
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    tmp.replace(path)


def load_events() -> dict:
    return _load(config.EVENTS_FILE, {})


def save_events(events: dict):
    _save(config.EVENTS_FILE, events)


def load_artists() -> dict:
    return _load(config.ARTISTS_FILE, {})


def save_artists(a: dict):
    _save(config.ARTISTS_FILE, a)


def load_health() -> dict:
    return _load(config.SOURCE_HEALTH_FILE, {})


def save_health(h: dict):
    _save(config.SOURCE_HEALTH_FILE, h)


def load_alerts() -> dict:
    return _load(config.ALERTS_FILE, {"alerted": {}, "digests": []})


def save_alerts(a: dict):
    _save(config.ALERTS_FILE, a)


def append_run_log(record: dict):
    config.ensure_dirs()
    month = config.now_utc().strftime("%Y-%m")
    with open(config.RUNS / f"{month}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def read_run_logs(months: int = 2) -> list[dict]:
    out = []
    files = sorted(config.RUNS.glob("*.jsonl"))[-months:]
    for p in files:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    return out


def append_cost(record: dict):
    config.ensure_dirs()
    with open(config.COSTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")


# ------------------------------------------------------------------ merge logic
REQUIRED_RAW = ("title", "start")


def normalize_raw(raw: dict, source: dict) -> dict | None:
    """Turn a collector's raw dict into an inventory-shaped record (without id/sources)."""
    title = clean_text(raw.get("title"))
    start = parse_dt(raw.get("start"))
    if not title or not start:
        return None
    end = parse_dt(raw.get("end"))
    venue_name = clean_text(raw.get("venue") or source.get("venue", {}).get("name") or "")
    city = clean_text(raw.get("city") or source.get("venue", {}).get("city") or "")
    state = clean_text(raw.get("state") or source.get("venue", {}).get("state") or "")
    rec = {
        "title": title,
        "start": iso(start),
        "end": iso(end) if end and end > start else None,
        "date": local_date(start),
        "venue": norm_venue(venue_name) if venue_name else "",
        "venue_raw": venue_name,
        "city": city,
        "region": region_of(city, state) if city else (source.get("region") or "unknown"),
        "address": clean_text(raw.get("address") or ""),
        "url": clean_text(raw.get("url") or source.get("url") or "") or None,
        "ticket_url": clean_text(raw.get("ticket_url") or "") or None,
        "performers": [clean_text(p) for p in (raw.get("performers") or []) if clean_text(p)],
        "description": clean_text(raw.get("description") or "")[:1200],
        "price": clean_text(raw.get("price") or "")[:80],
        "tags": sorted({clean_text(t).lower() for t in (raw.get("tags") or []) if clean_text(t)}),
        "category": raw.get("category") or source.get("category") or "music",
        "status": raw.get("status") or "scheduled",
        "image": raw.get("image"),
        "announced": raw.get("announced"),  # when the source says it was posted (if it says)
        "source_event_id": raw.get("source_event_id"),
        "extraction": "heuristic" if raw.get("heuristic") else ("model" if raw.get("model_extracted") else "structured"),
    }
    if raw.get("lat") and raw.get("lon"):
        rec["lat"], rec["lon"] = raw["lat"], raw["lon"]
    return rec


def _find_match(events: dict, rec: dict, by_key: dict) -> str | None:
    key = dedup_key(rec["venue"] or rec["venue_raw"], rec["date"], rec["title"])
    if key in by_key:
        return by_key[key]
    # Fuzzy: same venue & date, overlapping title tokens (catches "X & Y" vs "X with Y", support acts, etc.)
    vk = venue_key(rec["venue"] or rec["venue_raw"])
    if not vk:
        return None
    best, best_score = None, 0.0
    for eid, e in events.items():
        if e["date"] != rec["date"] or venue_key(e["venue"] or e["venue_raw"]) != vk:
            continue
        s = similar_titles(e["title"], rec["title"])
        if s > best_score:
            best, best_score = eid, s
    if best and best_score >= 0.34:
        return best
    # Same venue+date+start time with only one event that night is almost certainly the same show
    same_night = [eid for eid, e in events.items()
                  if e["date"] == rec["date"] and venue_key(e["venue"] or e["venue_raw"]) == vk
                  and e["start"] == rec["start"]]
    if len(same_night) == 1:
        return same_night[0]
    return None


def upsert(events: dict, rec: dict, source_id: str, now: str, stats: dict):
    by_key = stats.setdefault("_by_key", {})
    if not by_key:
        for eid, e in events.items():
            by_key.setdefault(dedup_key(e["venue"] or e["venue_raw"], e["date"], e["title"]), eid)
    match = _find_match(events, rec, by_key)
    src_entry = {"source": source_id, "url": rec["url"], "first_seen": now, "last_seen": now,
                 "title": rec["title"], "source_event_id": rec.get("source_event_id")}
    if match:
        e = events[match]
        e["last_seen"] = now
        found = False
        for s in e["sources"]:
            if s["source"] == source_id and (s.get("url") == rec["url"] or s.get("source_event_id") == rec.get("source_event_id")):
                s["last_seen"] = now
                s["title"] = rec["title"]
                found = True
        if not found:
            e["sources"].append(src_entry)
            stats["merged"] = stats.get("merged", 0) + 1
        # Fill gaps and prefer richer fields; never overwrite a venue-sourced field with an aggregator's.
        for k in ("end", "address", "ticket_url", "description", "price", "image", "announced", "lat", "lon"):
            if not e.get(k) and rec.get(k):
                e[k] = rec[k]
        if len(rec.get("performers", [])) > len(e.get("performers", [])):
            e["performers"] = rec["performers"]
        if rec.get("tags"):
            e["tags"] = sorted(set(e.get("tags", [])) | set(rec["tags"]))
        if not e.get("venue") and rec.get("venue"):
            e["venue"] = rec["venue"]
        if not e.get("city") and rec.get("city"):
            e["city"], e["region"] = rec["city"], rec["region"]
        if e.get("extraction") == "heuristic" and rec.get("extraction") != "heuristic":
            e["extraction"] = rec["extraction"]
        if rec["status"] != "scheduled":
            e["status"] = rec["status"]
        if rec.get("title") and len(rec["title"]) > len(e["title"]) and similar_titles(rec["title"], e["title"]) >= 0.5:
            e["title"] = rec["title"]  # keep the fuller billing
        return match, False
    key = dedup_key(rec["venue"] or rec["venue_raw"], rec["date"], rec["title"])
    eid = event_id(key)
    while eid in events:  # hash collision on a different key: extremely unlikely, but never clobber
        eid += "x"
    e = dict(rec)
    e.update({"id": eid, "first_seen": now, "last_seen": now, "sources": [src_entry],
              "score": None, "tier": None, "enrichment": None})
    events[eid] = e
    by_key[key] = eid
    stats["new"] = stats.get("new", 0) + 1
    return eid, True


def mark_past(events: dict):
    today = dt.datetime.now(TZ).date().isoformat()
    for e in events.values():
        if e["date"] and e["date"] < today and e["status"] == "scheduled":
            e["status"] = "past"


def mark_stale(events: dict, source_health: dict, now: str, stale_days: int = 10):
    """An event no source has reported for a while (while its sources were healthy) is probably pulled."""
    cutoff = (config.now_utc() - dt.timedelta(days=stale_days)).isoformat()
    for e in events.values():
        if e["status"] != "scheduled":
            continue
        healthy_sources = [s for s in e["sources"] if source_health.get(s["source"], {}).get("last_ok")]
        if healthy_sources and all(s["last_seen"] < cutoff for s in healthy_sources):
            e["status"] = "unlisted"
