"""Research queue for model-assisted review without any API: a Claude Code routine (scheduled, runs on
the owner's subscription) or an interactive session reads data/research-queue.json, researches each
item on the web, and writes findings to data/research.json. `python -m radar research apply` folds
findings into ranking. The deterministic pipeline never waits for this.

research.json entry (keyed by inventory event id):
  {"tier": "exceptional|strong|possible|low|unknown", "fit": 0-100, "reason": str,
   "evidence": [{"url": str, "finding": str}], "ticket_status": "available|sold-out|waitlist|unverified",
   "performers": [{"name": str, "known_for": str, "significance": "none|local|notable|major|foundational"}],
   "researched_at": iso, "researcher": str, "fingerprint": <copied from the queue item>}
An event is re-queued only when its listing fingerprint changes."""
import datetime as dt
import hashlib

from . import config, store
from .normalize import TZ
from .rank import _compile, blend, load_taste, tier_for

QUEUE_FILE = config.DATA / "research-queue.json"
RESEARCH_FILE = config.DATA / "research.json"
TIER_FIT = {"exceptional": 92, "strong": 75, "possible": 55, "low": 20}


def fingerprint(e):
    return hashlib.sha1(f"{e['title']}|{e.get('venue')}|{e['date']}".encode()).hexdigest()[:12]


def build_queue(n: int = 40):
    """Highest-value unresearched candidates: plausible fit, unknown names favoured, sooner first."""
    C = _compile(load_taste())
    events = store.load_events()
    done = store._load(RESEARCH_FILE, {})
    today = dt.datetime.now(TZ).date()
    cands = []
    for e in events.values():
        if e.get("status") != "scheduled" or e.get("tier") == "noise":
            continue
        d = dt.date.fromisoformat(e["date"])
        if (d - today).days > 180:
            continue
        r = done.get(e["id"]) or e.get("research")
        if r and r.get("fingerprint", fingerprint(e)) == fingerprint(e):
            continue
        srcs = {s["source"] for s in e["sources"]}
        taste_src = any(s.split(":")[-1] in C["src_bonus"] for s in srcs)
        sig = e.get("signals") or {}
        if not (e.get("score", 0) >= 40 or sig.get("venue_intimate") or taste_src):
            continue
        unknown = not sig.get("seed_hits")
        prio = (e.get("score") or 0) + (15 if unknown and (sig.get("venue_intimate") or taste_src) else 0) - min((d - today).days, 120) / 6
        cands.append((prio, e))
    cands.sort(key=lambda x: -x[0])
    q = [{"id": e["id"], "fingerprint": fingerprint(e), "title": e["title"], "date": e["date"], "start": e["start"],
          "venue": e.get("venue") or e.get("venue_raw"), "city": e.get("city"), "url": e.get("url"),
          "other_urls": [s.get("url") for s in e["sources"] if s.get("url") and s.get("url") != e.get("url")][:4],
          "rules_score": e.get("score"), "rules_tier": e.get("tier"), "why_rules": e.get("score_reasons", [])[:4],
          "description": (e.get("description") or "")[:400]} for _, e in cands[:n]]
    store._save(QUEUE_FILE, {"generated_at": config.now_iso(), "count": len(q), "backlog": len(cands), "items": q})
    print(f"[research] queue: {len(q)} items written ({len(cands)} candidates awaiting research)")
    return q


def apply():
    C = _compile(load_taste())
    events = store.load_events()
    found = store._load(RESEARCH_FILE, {})
    n = 0
    for eid, r in found.items():
        e = events.get(eid)
        if not e:
            continue
        fit = r.get("fit")
        if fit is None:
            fit = TIER_FIT.get(r.get("tier"))
        e["research"] = r
        if fit is not None:
            e["enrichment"] = {"fit": float(fit), "fast": {"why": r.get("reason", "")}, "deep": {"why": r.get("reason", ""),
                               "uncertainty": "; ".join(r.get("uncertainties", [])) if isinstance(r.get("uncertainties"), list) else r.get("uncertainties", "")},
                               "fingerprint": r.get("fingerprint"), "at": r.get("researched_at"), "source": r.get("researcher", "research.json")}
            e["final_score"] = blend(e.get("score") or 0, float(fit))
            e["tier"] = tier_for(e.get("score") or 0, C["tiers"], float(fit), e.get("signals"))
        n += 1
    store.save_events(events)
    print(f"[research] applied {n} findings")
    return n
