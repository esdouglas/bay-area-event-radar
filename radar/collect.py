"""Stage A: broad collection. Runs every registered source, merges into the inventory, logs everything."""
import concurrent.futures as cf
import datetime as dt
import time
import traceback

import yaml

from . import config, fetch, store
from .collectors import METHODS
from .normalize import parse_dt

FREQ_HOURS = {"every": 0, "6h": 6, "12h": 12, "daily": 22, "weekly": 6 * 24, "monthly": 27 * 24}


def load_sources(only=None) -> list[dict]:
    with open(config.SOURCES_FILE, encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    sources = doc.get("sources", [])
    ids = set()
    for s in sources:
        assert s.get("id") and s.get("method") and (s.get("url") or s.get("urls") or s["method"] == "eventbrite_api"), f"bad source {s}"
        assert s["id"] not in ids, f"duplicate source id {s['id']}"
        ids.add(s["id"])
        s.setdefault("frequency", "every")
        s.setdefault("enabled", True)
        s.setdefault("venue", {})
    if only:
        sources = [s for s in sources if s["id"] in only]
    return sources


def is_due(source: dict, health: dict, force: bool) -> bool:
    if not source.get("enabled", True):
        return False
    if force:
        return True
    hrs = FREQ_HOURS.get(source.get("frequency", "every"), 0)
    last = health.get(source["id"], {}).get("last_ok")
    if not last or hrs == 0:
        return True
    try:
        last_dt = dt.datetime.fromisoformat(last)
    except ValueError:
        return True
    return (config.now_utc() - last_dt) >= dt.timedelta(hours=hrs)


def run_source(source: dict) -> dict:
    stats = {"source": source["id"], "method": source["method"], "started": config.now_iso()}
    t0 = time.time()
    try:
        raws = METHODS[source["method"]](source, stats)
        stats["status"] = "ok"
        stats["raw_events"] = len(raws)
    except fetch.FetchError as e:
        raws = []
        stats["status"] = e.kind if e.kind in ("blocked", "ratelimited", "network", "config", "format", "partial") else "error"
        stats["error"] = str(e)
    except Exception as e:  # noqa: BLE001 - a broken collector must not kill the run
        raws = []
        stats["status"] = "error"
        stats["error"] = f"{type(e).__name__}: {e}"
        stats["trace"] = traceback.format_exc()[-1500:]
    stats["seconds"] = round(time.time() - t0, 1)
    stats["_raws"] = raws
    return stats


def ingest(events: dict, source: dict, raws: list[dict], now: str, stats: dict):
    horizon = config.now_utc() + dt.timedelta(days=config.HORIZON_DAYS)
    floor = config.now_utc() - dt.timedelta(days=1)
    kept = 0
    for raw in raws:
        rec = store.normalize_raw(raw, source)
        if not rec:
            stats["unparseable"] = stats.get("unparseable", 0) + 1
            continue
        start = parse_dt(rec["start"])
        if start < floor or start > horizon:
            stats["out_of_window"] = stats.get("out_of_window", 0) + 1
            continue
        if rec["region"] == "outside":
            stats["outside_region"] = stats.get("outside_region", 0) + 1
            continue
        if source.get("venue_filter") and source["venue_filter"].lower() not in (rec["venue"] + rec["venue_raw"]).lower():
            stats["filtered"] = stats.get("filtered", 0) + 1
            continue
        store.upsert(events, rec, source["id"], now, stats)
        kept += 1
    stats["ingested"] = kept
    return kept


def update_health(health: dict, stats: dict, now: str):
    h = health.setdefault(stats["source"], {"consecutive_failures": 0})
    h["last_run"] = now
    h["last_status"] = stats["status"]
    h["method"] = stats["method"]
    h["last_seconds"] = stats.get("seconds")
    if stats["status"] == "ok":
        h["last_ok"] = now
        h["last_count"] = stats.get("ingested", 0)
        h["last_raw"] = stats.get("raw_events", 0)
        h["consecutive_failures"] = 0
        h.pop("last_error", None)
        if stats.get("warnings"):
            h["last_warnings"] = stats["warnings"][:5]
        else:
            h.pop("last_warnings", None)
    else:
        h["consecutive_failures"] = h.get("consecutive_failures", 0) + 1
        h["last_error"] = stats.get("error")
    h["new_total"] = h.get("new_total", 0) + stats.get("new", 0)


def prune_cache(max_age_days: int = 21):
    """Caches are committed so Actions runs reuse them; drop entries nobody has touched in a while."""
    cutoff = time.time() - max_age_days * 86400
    n = 0
    for p in config.CACHE.glob("*.json"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                n += 1
        except OSError:
            pass
    if n:
        print(f"[collect] pruned {n} stale cache entries")


def run(only=None, force=False, workers=6, dry_run=False) -> dict:
    config.ensure_dirs()
    prune_cache()
    now = config.now_iso()
    sources = load_sources(only)
    events = store.load_events()
    health = store.load_health()
    due = [s for s in sources if is_due(s, health, force or bool(only))]
    skipped = [s["id"] for s in sources if s not in due]
    print(f"[collect] {len(due)} sources due, {len(skipped)} skipped (not due/disabled); inventory has {len(events)} events")
    results = []
    # Group by host so pacing works and one slow host does not block the pool.
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(run_source, s): s for s in due}
        for fut in cf.as_completed(futs):
            s = futs[fut]
            stats = fut.result()
            raws = stats.pop("_raws", [])
            stats.pop("_by_key", None)
            if stats["status"] == "ok":
                ingest(events, s, raws, now, stats)
            stats.pop("_by_key", None)
            update_health(health, stats, now)
            flag = "" if stats["status"] == "ok" else f"  !! {stats['status']}: {stats.get('error', '')[:120]}"
            print(f"  {s['id']:34} {stats['status']:10} raw={stats.get('raw_events', 0):4} kept={stats.get('ingested', 0):4} new={stats.get('new', 0):3} merged={stats.get('merged', 0):3} {stats.get('seconds', 0):5}s{flag}")
            store.append_run_log(stats)
            results.append(stats)
    store.mark_past(events)
    store.mark_stale(events, health, now)
    summary = {
        "ts": now,
        "sources_due": len(due),
        "sources_ok": sum(1 for r in results if r["status"] == "ok"),
        "sources_failed": [r["source"] for r in results if r["status"] != "ok"],
        "new_events": sum(r.get("new", 0) for r in results),
        "merged_sources": sum(r.get("merged", 0) for r in results),
        "inventory_total": len(events),
        "inventory_upcoming": sum(1 for e in events.values() if e["status"] == "scheduled"),
        "seconds": round(sum(r.get("seconds", 0) for r in results), 1),
    }
    print(f"[collect] done: {summary}")
    if not dry_run:
        store.save_events(events)
        store.save_health(health)
        store._save(config.RUN_SUMMARY_FILE, summary)
    return summary
