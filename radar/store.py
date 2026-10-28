"""Persistent inventory on disk (JSON, committed to git).

Why JSON files and not SQLite: the repository *is* the database between GitHub Actions runs, and text
files give readable diffs and survive merges. Everything is loaded into memory per run; the inventory
is a few thousand records, which is trivial.
"""
import datetime as dt
import json

from . import config
from .normalize import (TZ, clean_text, clean_title, dedup_key, event_id, iso, local_date, norm_venue, parse_dt,
                        region_of, same_venue, similar_titles, tokens, venue_key)


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


def append_observations(run_id: str, now: str, rows: list[dict]):
    """Append-only audit log of first sightings, new corroborating sources and changes (weekly files)."""
    if not rows:
        return
    d = config.DATA / "observations"
    d.mkdir(parents=True, exist_ok=True)
    week = config.now_utc().strftime("%G-W%V")
    with open(d / f"{week}.jsonl", "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(dict(r, run_id=run_id, observed_at=now), ensure_ascii=False, sort_keys=True) + "\n")


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
        "evidence_hash": raw.get("evidence_hash"),
        "date_basis": raw.get("date_basis"),
        "run_end": raw.get("run_end"),
        "extraction": "heuristic" if raw.get("heuristic") else ("model" if raw.get("model_extracted") else "structured"),
    }
    if raw.get("lat") and raw.get("lon"):
        rec["lat"], rec["lon"] = raw["lat"], raw["lon"]
    return rec


_DATE_INDEX = {"n": -1, "idx": {}}


def by_date(events: dict, date: str):
    """Events on a date. Rebuilt when the inventory size changes (cheap, avoids O(n) scans per record)."""
    if _DATE_INDEX["n"] != len(events) or _DATE_INDEX.get("id") != id(events):
        idx = {}
        for eid, e in events.items():
            idx.setdefault(e["date"], []).append(eid)
        _DATE_INDEX.update(n=len(events), idx=idx, id=id(events))
    return [(eid, events[eid]) for eid in _DATE_INDEX["idx"].get(date, []) if eid in events]


def _find_match(events: dict, rec: dict, by_key: dict) -> str | None:
    key = dedup_key(rec["venue"] or rec["venue_raw"], rec["date"], rec["title"])
    if key in by_key:
        return by_key[key]
    # Fuzzy: same date, same room (spelling-tolerant), overlapping title tokens. When either side has
    # no venue, require a near-identical multi-word title instead.
    rv = rec["venue"] or rec["venue_raw"]
    vk = venue_key(rv)
    rt = tokens(clean_title(rec["title"]))
    for eid, e in by_date(events, rec["date"]):
        ev_v = e["venue"] or e["venue_raw"]
        if (not vk or not venue_key(ev_v)) and len(rt) >= 2 and similar_titles(e["title"], rec["title"]) >= 0.8:
            return eid
    if not vk:
        return None
    best, best_score = None, 0.0
    for eid, e in by_date(events, rec["date"]):
        if not same_venue(e["venue"] or e["venue_raw"], rv):
            continue
        s = similar_titles(e["title"], rec["title"])
        if s > best_score:
            best, best_score = eid, s
    if best and best_score >= 0.34:
        return best
    # Same venue+date+start time with only one event that night is almost certainly the same show.
    # Never for date-only listings (00:00) or heuristic text lines: two different acts on one night
    # at a venue that lists no times must stay separate.
    if rec.get("extraction") == "heuristic" or rec["start"][11:16] == "00:00":
        return None
    same_night = [eid for eid, e in by_date(events, rec["date"])
                  if same_venue(e["venue"] or e["venue_raw"], rv)
                  and e["start"] == rec["start"] and e.get("extraction") != "heuristic"]
    if len(same_night) == 1:
        return same_night[0]
    # Aggregators occasionally file a show under the UTC date (03:30 "local"); match the neighbouring
    # day when the titles clearly agree.
    hour = int(rec["start"][11:13])
    if hour < 6:
        for eid, e in events.items():
            if same_venue(e["venue"] or e["venue_raw"], rv) and abs((dt.date.fromisoformat(e["date"]) - dt.date.fromisoformat(rec["date"])).days) == 1 \
                    and similar_titles(e["title"], rec["title"]) >= 0.6:
                return eid
    return None


def upsert(events: dict, rec: dict, source_id: str, now: str, stats: dict):
    by_key = stats.setdefault("_by_key", {})
    if not by_key:
        for eid, e in events.items():
            by_key.setdefault(dedup_key(e["venue"] or e["venue_raw"], e["date"], e["title"]), eid)
    match = _find_match(events, rec, by_key)
    src_entry = {"source": source_id, "url": rec["url"], "first_seen": now, "last_seen": now,
                 "title": rec["title"], "source_event_id": rec.get("source_event_id"), "seen_count": 1}
    obs = stats.setdefault("_observations", [])
    if match:
        e = events[match]
        e["last_seen"] = now
        found = False
        for s in e["sources"]:
            if s["source"] == source_id and (s.get("url") == rec["url"] or s.get("source_event_id") == rec.get("source_event_id")):
                if s.get("title") != rec["title"] or e["date"] != rec["date"]:
                    obs.append({"kind": "changed", "event_id": match, "source": source_id, "url": rec["url"], "title": rec["title"],
                                "date": rec["date"], "previous_title": s.get("title"), "evidence_hash": rec.get("evidence_hash")})
                s["last_seen"] = now
                s["title"] = rec["title"]
                s["seen_count"] = s.get("seen_count", 1) + 1
                found = True
        if not found:
            e["sources"].append(src_entry)
            stats["merged"] = stats.get("merged", 0) + 1
            obs.append({"kind": "new_source", "event_id": match, "source": source_id, "url": rec["url"], "title": rec["title"],
                        "date": rec["date"], "evidence_hash": rec.get("evidence_hash")})
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
            # A structured listing supersedes a text line: take its title, time and details.
            e["extraction"] = rec["extraction"]
            e["title"] = rec["title"]
            e["start"] = rec["start"]
            e["date"] = rec["date"]
            if rec.get("performers"):
                e["performers"] = rec["performers"]
            if rec.get("description"):
                e["description"] = rec["description"]
            if rec.get("venue"):
                e["venue"], e["venue_raw"] = rec["venue"], rec["venue_raw"]
            if rec.get("url"):
                e["url"] = rec["url"]
        if rec["status"] != "scheduled":
            e["status"] = rec["status"]
        e["title"] = best_title(e)  # keep the fullest clean billing across sources
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
    obs.append({"kind": "first_seen", "event_id": eid, "source": source_id, "url": rec["url"], "title": rec["title"],
                "date": rec["date"], "venue": rec.get("venue") or rec.get("venue_raw"), "evidence_hash": rec.get("evidence_hash"),
                "announced": rec.get("announced")})
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


def _better(a: dict, b: dict) -> dict:
    """Which of two duplicate records should survive as the canonical one."""
    rank = lambda e: (e.get("extraction") != "heuristic", bool(e.get("venue")), bool(e.get("start", "")[11:16] not in ("", "00:00")),
                      -len(e.get("sources", [])) * -1, e.get("first_seen", "~") and 0)
    return a if rank(a) >= rank(b) else b


def best_title(e: dict) -> str:
    """Fullest clean billing among the record's source titles (aggregator 'Artist - City - Venue -
    Date' strings are never chosen)."""
    from .collectors.gpt import JAMBASE
    cands = [t for t in [e["title"]] + [x.get("title") or "" for x in e.get("sources", [])] if t and not JAMBASE.match(t)]
    if not cands:
        m = JAMBASE.match(e["title"])
        return m.group(1).strip() if m else e["title"]
    base = cands[0]
    related = [t for t in cands if similar_titles(t, base) >= 0.3 or t.lower().startswith(base.lower()[:12])]
    return max(related or [base], key=lambda t: (len(tokens(clean_title(t))), -len(t)))


def compact(events: dict) -> int:
    """Merge duplicate records already in the inventory (same date, same room or blank room, matching
    titles). Keeps the earliest first_seen, unions sources, GPT ids and research."""
    for e in events.values():
        e["title"] = best_title(e)
    merged = 0
    dates = {}
    for eid, e in events.items():
        dates.setdefault(e["date"], []).append(eid)
    for d, ids in dates.items():
        alive = [i for i in ids if i in events]
        for i in range(len(alive)):
            for j in range(i + 1, len(alive)):
                a, b = alive[i], alive[j]
                if a not in events or b not in events:
                    continue
                ea, eb = events[a], events[b]
                va, vb = ea["venue"] or ea["venue_raw"], eb["venue"] or eb["venue_raw"]
                ta = {ea["title"]} | {x.get("title") or "" for x in ea["sources"]}
                tb = {eb["title"]} | {x.get("title") or "" for x in eb["sources"]}
                sim = max(similar_titles(x, y) for x in ta for y in tb if x and y)
                both_v = bool(venue_key(va)) and bool(venue_key(vb))
                ok = (both_v and same_venue(va, vb) and sim >= 0.5) or \
                     (not both_v and len(tokens(clean_title(ea["title"]))) >= 2 and sim >= 0.8)
                if not ok:
                    continue
                keep = _better(ea, eb)
                drop = eb if keep is ea else ea
                kid, did = keep["id"], drop["id"]
                keep["first_seen"] = min(keep["first_seen"], drop["first_seen"])
                keep["last_seen"] = max(keep["last_seen"], drop["last_seen"])
                have = {(s["source"], s.get("url")) for s in keep["sources"]}
                keep["sources"] += [s for s in drop["sources"] if (s["source"], s.get("url")) not in have]
                keep["gpt_ids"] = sorted(set(keep.get("gpt_ids", [])) | set(drop.get("gpt_ids", []))) or keep.get("gpt_ids")
                if not keep.get("gpt_ids"):
                    keep.pop("gpt_ids", None)
                for k in ("research", "enrichment", "venue", "city", "performers", "description", "ticket_url", "end", "run_end"):
                    if not keep.get(k) and drop.get(k):
                        keep[k] = drop[k]
                keep.setdefault("merged_ids", []).append(did)
                keep["title"] = best_title(keep)
                del events[did]
                merged += 1
    return merged
