"""One-time import of the GPT collector's history from main (data/inventory.json, observations,
research.json), reconciled against this inventory rather than appended.

* Every GPT record is normalised and passed through store.upsert, so it merges into an existing
  event (same venue/date/title rules as live collection) or becomes a new one. Its original
  first_seen is kept and wins if earlier, so lead-time history survives.
* Past events are skipped for the active inventory; all raw GPT observations are preserved verbatim
  in data/observations/gpt-history.jsonl.
* GPT's research findings attach to the matched event as `research` (with evidence URLs).
Run: python -m radar import-gpt <dir containing main's data/>"""
import datetime as dt
import json
import pathlib

from . import config, store
from .collectors.gpt import JAMBASE
from .normalize import TZ

# Per-performance theater rows; this repo now holds one event per production for these.
SKIP_SOURCES = {"berkeley-rep", "act", "shotgun", "aurora", "marin-theatre"}


def run(src_root: str):
    root = pathlib.Path(src_root)
    inv = json.loads((root / "data/inventory.json").read_text())
    research = json.loads((root / "data/research.json").read_text()) if (root / "data/research.json").exists() else {}
    events = store.load_events()
    today = dt.datetime.now(TZ).date().isoformat()
    stats = {}
    mapped, skipped_past, skipped_bad = {}, 0, 0
    before = len(events)
    for gid, g in inv.items():
        if not g.get("date") or g["date"] < today:
            skipped_past += 1
            continue
        obs = g.get("observations") or [{}]
        src = obs[0].get("source_id", "unknown")
        if src in SKIP_SOURCES:
            skipped_bad += 1
            continue
        m = JAMBASE.match(g.get("title") or "")
        city = None
        if m:
            g = dict(g, title=m.group(1).strip(), venue=m.group(3).strip())
            city = m.group(2).strip()
        raw = {"title": g.get("title"), "start": g.get("start") or g["date"], "venue": g.get("venue"),
               "url": obs[0].get("url"), "description": g.get("description", ""), "evidence_hash": obs[0].get("evidence_hash"),
               "date_basis": g.get("date_basis"), "city": city, "tags": ["imported-from-main"], "heuristic": bool(g.get("date_basis") and "infer" in str(g.get("date_basis")))}
        rec = store.normalize_raw(raw, {"id": f"gpt:{src}", "venue": {}})
        if not rec or rec["region"] == "outside":
            skipped_bad += 1
            continue
        eid, new = store.upsert(events, rec, f"gpt:{src}", g.get("first_seen") or config.now_iso(), stats)
        e = events[eid]
        if g.get("first_seen") and g["first_seen"] < e["first_seen"]:
            e["first_seen"] = g["first_seen"]
        e.setdefault("gpt_ids", [])
        if gid not in e["gpt_ids"]:
            e["gpt_ids"].append(gid)
        mapped[gid] = eid
        if gid in research:
            e["research"] = dict(research[gid], imported_from="main:data/research.json")
    store.save_events(events)
    # preserve the raw observation history verbatim
    out = config.DATA / "observations" / "gpt-history.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(out, "w", encoding="utf-8") as f:
        for gid, g in inv.items():
            for o in g.get("observations", []):
                f.write(json.dumps(dict(o, gpt_event_id=gid, title=g.get("title"), date=g.get("date"), venue=g.get("venue"),
                                        mapped_to=mapped.get(gid)), ensure_ascii=False, sort_keys=True) + "\n")
                n += 1
        for p in sorted((root / "data/observations").glob("*.jsonl")):
            for line in p.read_text().splitlines():
                if line.strip():
                    f.write(line + "\n")
                    n += 1
    summary = {"gpt_records": len(inv), "imported_future": len(mapped), "skipped_past": skipped_past,
               "skipped_unparseable_or_outside": skipped_bad, "merged_into_existing": len(mapped) - stats.get("new", 0),
               "new_events": stats.get("new", 0), "inventory_before": before, "inventory_after": len(events),
               "observations_preserved": n, "research_attached": sum(1 for g in research if g in mapped)}
    store._save(config.DATA / "gpt_import.json", dict(summary, ts=config.now_iso(), source="main@" + (root / ".git").name))
    print(f"[import-gpt] {summary}")
    return summary
