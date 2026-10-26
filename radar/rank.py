"""Stage D (rules half): cheap, explainable taste scoring for every upcoming event.

The score is additive and every contribution is recorded in `reasons`, so a reviewer can see why an
event landed where it did. Model-based enrichment (enrich.py) later refines the plausible middle.
"""
import datetime as dt
import re

import yaml

from . import config, store
from .normalize import TZ, fold, norm_venue, tokens


def load_taste() -> dict:
    with open(config.TASTE_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _compile(taste):
    seeds = []
    for s in taste.get("seed_artists", []):
        name = fold(s["name"])
        if not name:
            continue
        seeds.append((s["name"], re.compile(r"(?<![a-z0-9])" + re.escape(name) + r"(?![a-z0-9])"), float(s.get("weight", 20))))
    kws = []
    for group, spec in taste.get("keywords", {}).items():
        for term in spec.get("terms", []):
            t = fold(term)
            if t:
                kws.append((group, term, re.compile(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])"), float(spec["weight"])))
    v = taste.get("venues", {})
    return {
        "seeds": seeds,
        "kws": kws,
        "intimate": {fold(norm_venue(x)) for x in v.get("intimate", [])},
        "taste_venues": {fold(norm_venue(x)) for x in v.get("taste_venues", [])},
        "arena": {fold(norm_venue(x)) for x in v.get("arena", [])},
        "v": v,
        "src_bonus": (taste.get("sources") or {}).get("bonus", {}),
        "tiers": taste.get("tiers", {"exceptional": 72, "strong": 50, "inventory": 15}),
        "cat": taste.get("category_weights", {}),
        "multi": float(taste.get("multi_source_bonus", 4)),
        "soon": float(taste.get("upcoming_14d_bonus", 3)),
    }


def score_event(e: dict, C: dict, today: dt.date) -> tuple[float, list[str], dict]:
    reasons = []
    score = 20.0  # baseline: every real event is worth keeping
    text = fold(" ".join([e.get("title", ""), " ".join(e.get("performers", [])), e.get("description", "")[:600], " ".join(e.get("tags", []))]))
    title_text = fold(" ".join([e.get("title", ""), " ".join(e.get("performers", []))]))
    seed_hits = []
    seed_hits_title = []
    for name, rx, w in C["seeds"]:
        if rx.search(title_text):
            seed_hits.append((name, w))
            seed_hits_title.append(name)
        elif rx.search(text):
            seed_hits.append((name, w * 0.3))  # a name in the blurb is a hint, not a billing
    if seed_hits:
        best = max(seed_hits, key=lambda x: x[1])
        score += best[1]
        reasons.append(f"seed artist: {best[0]} (+{best[1]:.0f})")
        if len(seed_hits) > 1:
            score += 5
            reasons.append(f"{len(seed_hits)} seed artists on the bill (+5)")
    group_hits = {}
    for group, term, rx, w in C["kws"]:
        if rx.search(text):
            group_hits.setdefault(group, []).append((term, w))
    for group, hits in group_hits.items():
        w = hits[0][1]
        n = len(hits)
        contrib = w if w < 0 else min(w * (1 + 0.25 * (n - 1)), w * 1.75)
        score += contrib
        reasons.append(f"{group}: {', '.join(t for t, _ in hits[:4])} ({contrib:+.0f})")
    venue = fold(e.get("venue") or e.get("venue_raw") or "")
    if venue in C["intimate"]:
        score += float(C["v"].get("intimate_bonus", 14))
        reasons.append(f"intimate room: {e.get('venue')} (+{C['v'].get('intimate_bonus', 14)})")
    if venue in C["taste_venues"]:
        score += float(C["v"].get("taste_venues_bonus", 10))
        reasons.append(f"booking signal: {e.get('venue')} (+{C['v'].get('taste_venues_bonus', 10)})")
    if venue in C["arena"]:
        score += float(C["v"].get("arena_penalty", -20))
        reasons.append(f"arena-scale venue ({C['v'].get('arena_penalty', -20)})")
    srcs = {s["source"] for s in e.get("sources", [])}
    sb = max((float(C["src_bonus"].get(s, 0)) for s in srcs), default=0)
    if sb:
        score += sb
        reasons.append(f"listed by a taste-aligned calendar (+{sb:.0f})")
    if len(srcs) > 1:
        b = min(C["multi"] * (len(srcs) - 1), 12)
        score += b
        reasons.append(f"{len(srcs)} independent sources (+{b:.0f})")
    cat = e.get("category") or "music"
    cw = float(C["cat"].get(cat, 0))
    if cw:
        score += cw
        reasons.append(f"category {cat} ({cw:+.0f})")
    try:
        d = dt.date.fromisoformat(e["date"])
        if 0 <= (d - today).days <= 14:
            score += C["soon"]
    except (TypeError, ValueError):
        pass
    if e.get("region") == "norcal":
        score -= 6
        reasons.append("outside the core Bay Area (-6)")
    elif e.get("region") == "unknown":
        reasons.append("location unresolved (no penalty)")
    if e.get("extraction") == "heuristic":
        score -= 8
        reasons.append("heuristic text extraction, unverified (-8)")
    if e.get("status") in ("cancelled", "postponed"):
        score -= 30
        reasons.append(f"status {e['status']} (-30)")
    score = max(0.0, min(100.0, score))
    signals = {"seed_hits": seed_hits_title, "seed_mentions": [n for n, _ in seed_hits if n not in seed_hits_title],
               "keyword_groups": sorted(group_hits), "venue_intimate": venue in C["intimate"]}
    return round(score, 1), reasons, signals


def blend(score: float, llm_fit: float | None) -> float:
    """Final score: the model's fit judgement dominates once it exists; rules carry the rest."""
    return round(score, 1) if llm_fit is None else round(0.25 * score + 0.75 * llm_fit, 1)


def tier_for(score: float, tiers: dict, llm_fit: float | None = None, signals: dict | None = None) -> str:
    s = blend(score, llm_fit)
    if llm_fit is not None and llm_fit >= 88:
        return "exceptional"  # the model is confident this is a must-see; rules cannot veto that
    if s >= tiers["exceptional"]:
        if llm_fit is None and signals is not None:
            # Rules alone cannot tell a foundational artist from a competent local trio: without model
            # research, "exceptional" needs a named seed artist or an explicit legacy / psych-folk signal.
            groups = set(signals.get("keyword_groups", []))
            if not signals.get("seed_hits") and "roots_psych" not in groups:
                return "strong"
        return "exceptional"
    if s >= tiers["strong"]:
        return "strong"
    if s >= tiers["inventory"]:
        return "inventory"
    return "noise"


def run():
    taste = load_taste()
    C = _compile(taste)
    events = store.load_events()
    today = dt.datetime.now(TZ).date()
    counts = {}
    for e in events.values():
        if e.get("status") == "past":
            continue
        sc, reasons, signals = score_event(e, C, today)
        e["score"] = sc
        e["score_reasons"] = reasons
        e["signals"] = signals
        fit = (e.get("enrichment") or {}).get("fit")
        e["final_score"] = blend(sc, fit)
        e["tier"] = tier_for(sc, C["tiers"], fit, signals)
        counts[e["tier"]] = counts.get(e["tier"], 0) + 1
    store.save_events(events)
    print(f"[score] scored {sum(counts.values())} upcoming events: {counts}")
    return counts
