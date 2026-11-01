"""Which shows are worth Erik's attention: pick score, travel zone, small rooms, one entry per act.

Erik goes to about one show every two weeks, so the weekly email carries a handful of picks rather than
every strong match. Settings live in taste.yaml (`travel`, `digest`, `venues.book_ahead`).

pick score = base - travel penalty, where base is
  * the research fit (data/research.json), when the show has been researched, else
  * the rules score minus 5, when the bill names one of his seed artists, else
  * nothing: the show is not a pick until it is researched (research.build_queue moves it up).
A show outside the near and mid zones also needs base >= travel.far.min_base ("pretty special").
"""
import re

from .normalize import BAY_AREA_CITIES, fold, similar_titles

_CFG = None


def cfg() -> dict:
    global _CFG
    if _CFG is None:
        from .rank import load_taste
        t = load_taste()
        v = t.get("venues", {})
        travel = t.get("travel", {})
        zones = {z: {fold(c) for c in (travel.get(z) or {}).get("cities", [])} for z in ("near", "mid")}
        cities = sorted(BAY_AREA_CITIES | zones["near"] | zones["mid"], key=len, reverse=True)
        _CFG = {
            "travel": travel, "zones": zones,
            "city_re": re.compile(r"\b(" + "|".join(re.escape(c) for c in cities) + r")\b"),
            "book": [x for x in [re.sub(r"^the ", "", fold(x)) for x in v.get("book_ahead", [])]
                     + [fold(x) for x in v.get("book_ahead_patterns", [])] if x],
            "digest": {"pick_min": 80, "max_soon": 3, "max_new_ahead": 3, "max_still_ahead": 6, "max_also": 4,
                       "alert_min": 88, **(t.get("digest") or {})},
        }
    return _CFG


def book_ahead(e) -> bool:
    """Is this show in a small room that can sell out (taste.yaml venues.book_ahead / book_ahead_patterns)?"""
    text = fold(" ".join(str(x) for x in (e.get("venue"), e.get("venue_raw")) if x))
    return any(k in text for k in cfg()["book"])


def city_of(e) -> str:
    """The event's city, falling back to a place named in the venue text (calendar listings often
    put "Otter Opry, Monterey" in the venue and leave city empty)."""
    c = fold(re.sub(r",\s*ca$", "", e.get("city") or "", flags=re.I))
    if c:
        return c
    m = cfg()["city_re"].search(fold(" ".join(str(x) for x in (e.get("venue"), e.get("venue_raw")) if x)))
    if m:
        return m.group(1)
    if re.search(r"\bsf\b", fold(e.get("venue") or "")):
        return "san francisco"
    return ""


def zone(e) -> str:
    c = city_of(e)
    if not c:
        return cfg()["travel"].get("unknown_zone", "mid")
    for z in ("near", "mid"):
        if c in cfg()["zones"][z]:
            return z
    return "far"


def base_score(e):
    r = e.get("research") or {}
    if r.get("fit") is not None and r.get("tier") != "unknown":
        return float(r["fit"])
    if (e.get("signals") or {}).get("seed_hits"):
        return float(e.get("final_score") or e.get("score") or 0) - 5
    return None


def pick_score(e):
    """None when the show cannot be a pick (unresearched without a seed, too far for its score, sold out in a small room)."""
    if (e.get("research") or {}).get("ticket_status") == "sold-out" and book_ahead(e):
        return None  # a sold-out small room is gone; a sold-out big venue still has resale (Erik, 2026-11-01)
    b = base_score(e)
    if b is None:
        return None
    z = zone(e)
    t = cfg()["travel"].get(z) or {}
    if z == "far" and b < float(t.get("min_base", 90)):
        return None
    return round(b - float(t.get("penalty", 0)), 1)


def one_per_act(events, key):
    """Keep the best-scoring date for each act (a touring band listed at four venues counts once)."""
    out = []
    for e in sorted(events, key=key, reverse=True):
        if any(similar_titles(e["title"], o["title"]) >= 0.6 for o in out):
            continue
        out.append(e)
    return out
