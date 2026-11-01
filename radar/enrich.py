"""Stage C/D (model half): research unfamiliar performers and judge fit, two passes.

Pass 1 (fast model): every plausible candidate gets a compact fit judgement. Candidates are events at
taste venues / from taste calendars, plus anything the rules scored >= 35. This is where a name the
seed list has never heard of (a Stampfel, a Hurley) gets recognised.
Pass 2 (stronger model): events the fast pass rated promising get a fuller write-up with artist
background, scarcity and uncertainty, grounded with Wikipedia summaries fetched for each performer.
Results are cached on the event (enrichment) and per artist (data/artists.json) so nothing is
researched twice unless the listing changes.
"""
import datetime as dt
import hashlib
import json
import re

import requests

from . import config, llm, store
from .normalize import TZ, clean_text, fold, norm_venue, title_core
from .rank import _compile, blend, load_taste, tier_for

WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"

TASTE_BRIEF = """The listener lives in Rockridge, Oakland. Core loves: old-time and Appalachian music, bluegrass and
progressive acoustic (Billy Strings, Molly Tuttle, Michael Cleveland, Sierra Ferrell, Punch Brothers lineage),
fiddle traditions (Bruce Molsky, April Verch, Jeremy Kittel), psychedelic / freak / outsider folk and the
early folk revival (Peter Stampfel, Holy Modal Rounders, the Fugs, Michael Hurley and their networks),
countercultural Americana, unusual traditional-music collaborations (Nora Brown & Stephanie Coleman,
Rhiannon Giddens, Aoife O'Donovan, Grant Gordy, Ross Martin, Flynn Cohen, Low Lily, the Crooked Jades,
Mountain Grass Unit). Adventurous, emotionally compelling improvised jazz in intimate rooms, especially with
distinctive instrumentation or strong artistic identity. Acclaimed contemporary plays, excellent writing and
acting, classic revivals with exceptional casts/directors, premieres, unusual theatrical concepts (liked The
Crucible, All My Sons, Uncle Vanya, John Proctor Is the Villain). Partner enjoys musicals, dance and
celebrity-cast productions; limited-run unusually-cast musicals can justify travel. Also: special cultural
events, immersive and interdisciplinary work, exceptional legacy artists, select 1990s alternative, design, art.
Guiding rule: a foundational musician playing a $20 show in a 100-person room may matter more than an arena
headliner. Be generous with borderline roots/jazz/theater; be harsh on tribute acts, DJ nights, karaoke,
comedy, classes, kids' shows and generic cover-band Americana."""

FAST_SYSTEM = """You judge how well a live event fits one specific listener's taste. Reply ONLY with JSON:
{"fit": 0-100, "known": true|false, "significance": "none|local|notable|major|foundational",
 "why": "<=40 words for the listener", "flags": ["sellout-risk","rare-appearance","historic","unknown-performer","noise"]}
fit scale: 85+ must-see for this listener; 70 strong; 50 worth a look; 30 marginal; <20 noise.
"known" means you recognise the main performer(s) with confidence. Do not inflate unknown acts; do not
penalise an act merely for being unknown if the venue/calendar and description fit the taste."""

DEEP_SYSTEM = """You are a music/theater researcher writing a short brief for one listener. Use the background
notes provided (Wikipedia summaries) and your own knowledge. Reply ONLY with JSON:
{"fit": 0-100, "tier": "exceptional|strong|inventory|noise",
 "headline": "<=12 words: why this matters",
 "why": "2-4 sentences for the listener: who this is, lineage/collaborators, why it fits, what is special about this date",
 "background": "2-3 sentences of factual background on the main performer(s); say 'unverified' for anything you are not sure of",
 "scarcity": "how rare this is (touring frequency, age, venue size, likely sellout) in one sentence",
 "uncertainty": "what is unclear (lineup, date, whether it is the same artist) in one sentence or 'none'",
 "performers": [{"name": str, "known_for": str, "significance": "none|local|notable|major|foundational"}]}
Be concrete and honest. Historic significance in a small room should score very high. Tribute shows,
DJ sets, classes, comedy and generic cover acts are noise regardless of venue."""


def _fingerprint(e: dict) -> str:
    return hashlib.sha1(f"{e['title']}|{e.get('venue')}|{e['date']}|{','.join(e.get('performers', []))}".encode()).hexdigest()[:12]


def _event_block(e: dict) -> str:
    srcs = sorted({s["source"] for s in e.get("sources", [])})
    return (f"Title: {e['title']}\nPerformers: {', '.join(e.get('performers', [])) or '(not listed)'}\n"
            f"Date: {e['date']} {e['start'][11:16] if e.get('start') else ''}\nVenue: {e.get('venue') or e.get('venue_raw')} ({e.get('city') or '?'})\n"
            f"Category: {e.get('category')}\nTags: {', '.join(e.get('tags', [])[:8])}\nPrice: {e.get('price') or '?'}\n"
            f"Sources: {', '.join(srcs)}\nRules score: {e.get('score')} ({'; '.join(e.get('score_reasons', [])[:4])})\n"
            f"Description: {e.get('description', '')[:700]}")


# ----------------------------------------------------------------------------- Wikipedia grounding
def wiki_lookup(name: str, artists: dict) -> dict | None:
    key = fold(name)
    if not key or len(key) < 3:
        return None
    cached = artists.get(key)
    if cached and cached.get("wiki_checked"):
        try:
            if (config.now_utc() - dt.datetime.fromisoformat(cached["wiki_checked"])).days < 120:
                return cached
        except ValueError:
            pass
    rec = dict(cached or {}, name=name, wiki_checked=config.now_iso())
    try:
        r = requests.get(WIKI_API, params={"action": "opensearch", "search": name, "limit": 3, "namespace": 0, "format": "json"},
                         headers={"User-Agent": config.USER_AGENT}, timeout=20)
        titles = r.json()[1] if r.status_code == 200 else []
        pick = None
        for t in titles:
            ft = fold(t)
            if ft == key or ft.startswith(key) or key in ft:
                pick = t
                break
        if pick:
            s = requests.get(WIKI_SUMMARY + requests.utils.quote(pick.replace(" ", "_")), headers={"User-Agent": config.USER_AGENT}, timeout=20)
            if s.status_code == 200:
                d = s.json()
                desc = clean_text(d.get("description") or "")
                extract = clean_text(d.get("extract") or "")[:700]
                # a disambiguation or an obviously-wrong hit (e.g. a village) is not grounding
                if d.get("type") == "disambiguation" or not re.search(r"musician|band|singer|composer|fiddler|banjo|guitarist|duo|trio|group|artist|ensemble|songwriter|playwright|actor|actress|director|theatre|theater|pianist|saxophon|trumpet|drummer|bassist|violinist|cellist|producer|rapper|comedian|dancer|choreograph|orchestra|quartet", (desc + " " + extract).lower()):
                    rec.update({"wiki": None, "wiki_note": f"nearest page '{pick}' does not look like a performer"})
                else:
                    rec.update({"wiki": pick, "wiki_desc": desc, "wiki_extract": extract, "wiki_url": (d.get("content_urls") or {}).get("desktop", {}).get("page")})
        else:
            rec["wiki"] = None
    except (requests.RequestException, ValueError, IndexError):
        rec.setdefault("wiki", None)
    artists[key] = rec
    return rec


def _performer_names(e: dict) -> list[str]:
    names = list(e.get("performers", []))
    if not names:
        t = clean_text(e["title"])
        parts = re.split(r"\s+(?:w/|with|feat\.?|featuring|\+|/|\|)\s+|:\s|\s-\s|\s–\s|\s—\s|,\s|\s&\s|\s and \s", t)
        names = [p.strip() for p in parts if 2 < len(p.strip()) < 60][:4]
    return names[:4]


# ----------------------------------------------------------------------------- candidate selection
def candidates(events: dict, C: dict, min_score: float) -> list[dict]:
    out = []
    for e in events.values():
        if e.get("status") not in ("scheduled",):
            continue
        if e.get("score") is None:
            continue
        venue = fold(e.get("venue") or e.get("venue_raw") or "")
        srcs = {s["source"] for s in e.get("sources", [])}
        taste_src = any(s in C["src_bonus"] for s in srcs)
        if e["score"] >= min_score or venue in C["taste_venues"] or venue in C["intimate"] or taste_src:
            if e.get("tier") == "noise" and e["score"] < 12:
                continue
            out.append(e)
    today = dt.datetime.now(TZ).date()

    def prio(e):
        enr = e.get("enrichment") or {}
        fresh = enr.get("fingerprint") == _fingerprint(e)
        days = (dt.date.fromisoformat(e["date"]) - today).days
        return (fresh, -e["score"] if days > 14 else -e["score"] - 20, days)
    out.sort(key=prio)
    return out


def fast_pass(e: dict, C: dict) -> dict:
    user = TASTE_BRIEF + "\n\nEVENT\n" + _event_block(e)
    raw = llm.complete(FAST_SYSTEM, user, tier="fast", max_tokens=300, purpose="enrich-fast")
    d = llm.parse_json(raw)
    return {"fit": float(d.get("fit", 0)), "known": bool(d.get("known")), "significance": d.get("significance", "none"),
            "why": clean_text(d.get("why", ""))[:400], "flags": [str(f) for f in d.get("flags", [])][:6]}


def deep_pass(e: dict, artists: dict) -> dict:
    notes = []
    for name in _performer_names(e):
        rec = wiki_lookup(name, artists)
        if rec and rec.get("wiki"):
            notes.append(f"- {name}: [{rec['wiki']}] {rec.get('wiki_desc', '')}. {rec.get('wiki_extract', '')}")
        else:
            notes.append(f"- {name}: no Wikipedia page found")
    user = TASTE_BRIEF + "\n\nEVENT\n" + _event_block(e) + "\n\nBACKGROUND NOTES\n" + "\n".join(notes)
    raw = llm.complete(DEEP_SYSTEM, user, tier="smart", max_tokens=900, purpose="enrich-deep")
    d = llm.parse_json(raw)
    perf = []
    for p in d.get("performers", [])[:5]:
        if isinstance(p, dict) and p.get("name"):
            perf.append({"name": clean_text(p["name"])[:80], "known_for": clean_text(p.get("known_for", ""))[:200], "significance": p.get("significance", "none")})
            key = fold(p["name"])
            if key:
                a = artists.setdefault(key, {"name": p["name"]})
                a["known_for"] = perf[-1]["known_for"]
                a["significance"] = perf[-1]["significance"]
                a["updated"] = config.now_iso()
    return {"fit": float(d.get("fit", 0)), "tier_suggested": d.get("tier"), "headline": clean_text(d.get("headline", ""))[:120],
            "why": clean_text(d.get("why", ""))[:900], "background": clean_text(d.get("background", ""))[:700],
            "scarcity": clean_text(d.get("scarcity", ""))[:300], "uncertainty": clean_text(d.get("uncertainty", ""))[:300],
            "performers": perf}


def run(limit: int = 60, min_score: float | None = None, deep_threshold: float = 55):
    if not llm.available():
        print("[enrich] no LLM provider configured (set ANTHROPIC_API_KEY or OPENAI_API_KEY); skipping")
        return {"skipped": True}
    taste = load_taste()
    C = _compile(taste)
    events = store.load_events()
    artists = store.load_artists()
    cands = candidates(events, C, min_score if min_score is not None else 35)
    todo = [e for e in cands if (e.get("enrichment") or {}).get("fingerprint") != _fingerprint(e)][:limit]
    print(f"[enrich] {len(cands)} candidates, {len(todo)} need research (limit {limit}); model fast={llm.model_for('fast')} smart={llm.model_for('smart')}")
    done = deep = 0
    for e in todo:
        try:
            fast = fast_pass(e, C)
        except (llm.LLMError, ValueError, json.JSONDecodeError) as ex:
            print(f"  ! fast pass failed for {e['title'][:50]}: {ex}")
            continue
        enr = {"fingerprint": _fingerprint(e), "at": config.now_iso(), "fast": fast, "fit": fast["fit"], "model_fast": llm.model_for("fast")}
        if fast["fit"] >= deep_threshold or fast.get("significance") in ("major", "foundational") or "historic" in fast.get("flags", []):
            try:
                d = deep_pass(e, artists)
                enr["deep"] = d
                enr["fit"] = round(0.3 * fast["fit"] + 0.7 * d["fit"], 1)
                enr["model_smart"] = llm.model_for("smart")
                deep += 1
            except (llm.LLMError, ValueError, json.JSONDecodeError) as ex:
                enr["deep_error"] = str(ex)[:200]
        e["enrichment"] = enr
        e["final_score"] = blend(e["score"], enr["fit"])
        e["tier"] = tier_for(e["score"], C["tiers"], enr["fit"], e.get("signals"))
        done += 1
        print(f"  {e['date']} {e['title'][:48]:48} rules={e['score']:5} fit={enr['fit']:5} -> {e['tier']}")
    store.save_events(events)
    store.save_artists(artists)
    cost = llm.cost_summary(1)
    print(f"[enrich] researched {done} events ({deep} deep); cost today ${cost['usd']}")
    return {"researched": done, "deep": deep, "cost_today_usd": cost["usd"]}
