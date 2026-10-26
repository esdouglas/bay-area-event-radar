"""Historical discoverability benchmark (see benchmark/events.yaml for the rules of evidence).

Classification for each benchmark event, in this order:
  blocked       every listed source is disabled/blocked in the registry  -> would have been missed
  proven        a pre-dated artifact from a registered, enabled source (announced:, or a Wayback hit)
  plausible     the venue's own feed is a registered, enabled, currently healthy source
  indirect      only aggregators/calendars might have carried it (venue page blocked or unregistered)
  unverifiable  nothing above holds
`--live` additionally queries the Wayback Machine CDX index for snapshots of the source page taken
before the event and searches them for the `match` string (needs a network path to web.archive.org,
which GitHub runners have and this sandbox did not).
"""
import datetime as dt
import json
import re

import requests
import yaml

from . import config, store
from .collect import load_sources
from .normalize import TZ, fold, norm_venue
from .rank import _compile, load_taste, score_event, tier_for

CDX = "https://web.archive.org/cdx/search/cdx"


def _wayback(url: str, match: str, event_date: dt.date, stats: dict) -> dict | None:
    """Earliest pre-event snapshot of `url` that contains `match` (case-insensitive)."""
    frm = (event_date - dt.timedelta(days=150)).strftime("%Y%m%d")
    to = (event_date - dt.timedelta(days=1)).strftime("%Y%m%d")
    try:
        r = requests.get(CDX, params={"url": url, "from": frm, "to": to, "output": "json", "fl": "timestamp,statuscode", "filter": "statuscode:200", "limit": 60},
                         headers={"User-Agent": config.USER_AGENT}, timeout=60)
        rows = r.json()[1:] if r.status_code == 200 and r.text.strip() else []
    except (requests.RequestException, ValueError):
        stats["cdx_errors"] = stats.get("cdx_errors", 0) + 1
        return None
    stats["snapshots_listed"] = stats.get("snapshots_listed", 0) + len(rows)
    checked = 0
    for ts, _ in rows:
        if checked >= 6:
            break
        checked += 1
        try:
            s = requests.get(f"https://web.archive.org/web/{ts}id_/{url}", headers={"User-Agent": config.USER_AGENT}, timeout=60)
        except requests.RequestException:
            continue
        if s.status_code == 200 and match.lower() in s.text.lower():
            when = dt.datetime.strptime(ts, "%Y%m%d%H%M%S").date()
            return {"snapshot": ts, "snapshot_date": when.isoformat(), "snapshot_url": f"https://web.archive.org/web/{ts}/{url}"}
    return {"checked": checked, "found": False} if rows else {"checked": 0, "found": False, "note": "no snapshots in window"}


def classify(ev: dict, sources_by_id: dict, health: dict, live: bool, stats: dict) -> dict:
    date = ev["date"] if isinstance(ev["date"], dt.date) else dt.date.fromisoformat(str(ev["date"]))
    ev = dict(ev, date=date.isoformat())
    srcs = [sources_by_id.get(s) for s in ev.get("sources", [])]
    srcs = [s for s in srcs if s]
    enabled = [s for s in srcs if s.get("enabled", True)]
    healthy = [s for s in enabled if health.get(s["id"], {}).get("last_status") in ("ok", "partial")]
    res = {"id": ev["id"], "title": ev["title"], "date": ev["date"], "venue": ev["venue"], "registered": [s["id"] for s in srcs],
           "enabled": [s["id"] for s in enabled], "healthy": [s["id"] for s in healthy]}
    lead = None
    if ev.get("announced") and enabled:
        a = ev["announced"]
        try:
            if isinstance(a, dt.datetime):
                ad = a.date()
            elif isinstance(a, dt.date):
                ad = a
            else:
                a = str(a)
                ad = dt.datetime.fromisoformat(a.replace("Z", "+00:00")).date() if "T" in a else dt.date.fromisoformat(a)
            lead = (date - ad).days
            res.update(cls="proven", lead_days=lead, basis=f"primary-source timestamp {str(a)[:19]} ({ev.get('evidence', '')[:90]})")
        except ValueError:
            pass
    if "cls" not in res and live and ev.get("wayback") and enabled:
        wb = _wayback(ev["wayback"]["url"], ev["wayback"]["match"], date, stats)
        res["wayback"] = wb
        if wb and wb.get("snapshot_date"):
            lead = (date - dt.date.fromisoformat(wb["snapshot_date"])).days
            res.update(cls="proven", lead_days=lead, basis=f"Wayback snapshot {wb['snapshot_date']} of {ev['wayback']['url']} contains '{ev['wayback']['match']}' (lower bound on lead time)")
    if "cls" not in res:
        if srcs and not enabled:
            res.update(cls="blocked", basis=f"only registered via disabled/blocked sources: {', '.join(s['id'] for s in srcs)}")
        elif healthy:
            direct = [s for s in healthy if s.get("kind") in ("venue", "presenter", "theater", "festival", "arts")]
            if direct:
                res.update(cls="plausible", basis=f"the venue's own feed ({', '.join(s['id'] for s in direct)}) is a healthy registry source; no pre-dated artifact captured")
            else:
                res.update(cls="indirect", basis=f"venue page is blocked/unregistered; only aggregators or calendars ({', '.join(s['id'] for s in healthy)}) might carry it, and their coverage of this venue is unproven")
        elif enabled:
            res.update(cls="unverifiable", basis=f"registered source(s) {', '.join(s['id'] for s in enabled)} not currently healthy")
        else:
            res.update(cls="unverifiable", basis="venue/presenter is not a registered source")
    # what the ranking would have done with the bare listing (title + venue only, as a collector would see it)
    taste = _compile(load_taste())
    fake = {"title": ev["title"], "performers": [], "description": "", "tags": [], "venue": norm_venue(ev["venue"]), "venue_raw": ev["venue"],
            "sources": [{"source": s} for s in ev.get("sources", [])], "category": ev.get("category", "music"), "date": ev["date"],
            "region": "bay", "status": "scheduled"}
    sc, reasons, signals = score_event(fake, taste, dt.date.today())
    res["rules_score"] = sc
    res["rules_tier"] = tier_for(sc, taste["tiers"], None, signals)
    res["rules_reasons"] = reasons[:4]
    return res


def run(live: bool = False):
    with open(config.BENCHMARK_FILE, encoding="utf-8") as f:
        bench = yaml.safe_load(f)["events"]
    sources_by_id = {s["id"]: s for s in load_sources()}
    health = store.load_health()
    stats = {}
    results = [classify(ev, sources_by_id, health, live, stats) for ev in bench]
    by = {}
    for r in results:
        by.setdefault(r["cls"], []).append(r)
    n = len(results)
    proven = by.get("proven", [])
    leads = sorted(r["lead_days"] for r in proven if r.get("lead_days") is not None)
    median_lead = leads[len(leads) // 2] if leads else None
    rules_hit = sum(1 for r in results if r["rules_tier"] in ("strong", "exceptional"))
    rules_noise = sum(1 for r in results if r["rules_tier"] == "noise")
    lines = [f"{'event':58} {'date':10} {'class':12} {'lead':>5}  {'rules':>5} {'tier':11} basis"]
    for r in sorted(results, key=lambda x: (x["cls"], x["date"])):
        lines.append(f"{r['title'][:58]:58} {r['date']:10} {r['cls']:12} {str(r.get('lead_days', '')):>5}  {r['rules_score']:>5} {r['rules_tier']:11} {r['basis'][:110]}")
    headline = (f"{n} benchmark events: {len(proven)} proven discoverable by registered sources (median lead {median_lead} days, "
                f"range {leads[0] if leads else '-'}..{leads[-1] if leads else '-'}), {len(by.get('plausible', []))} plausible via the venue's own feed, "
                f"{len(by.get('indirect', []))} reachable only through aggregators, {len(by.get('blocked', []))} only via blocked sources, {len(by.get('unverifiable', []))} unverifiable. "
                f"Rules-only ranking would have put {rules_hit}/{n} in the digest/alert tiers and {rules_noise} in noise.")
    print(headline)
    print("\n".join(lines))
    summary = {"ts": config.now_iso(), "n": n, "headline": headline, "table": "\n".join(lines), "live": live, "wayback_stats": stats,
               "counts": {k: len(v) for k, v in by.items()}, "median_lead_days": median_lead, "results": results}
    store._save(config.DATA / "benchmark_summary.json", summary)
    report = ["# Historical discoverability benchmark", "", f"Generated {summary['ts']} (live Wayback checks: {live}).", "", headline, "",
              "Evidence classes are defined in `benchmark/events.yaml`. 'Proven' lead times come from primary-source timestamps "
              "(Google Calendar CREATED, The Events Calendar creation stamps, Squarespace addedOn) or Wayback snapshots; they are "
              "lower bounds on how early the system would have seen the listing, assuming the source had been registered at the time.", "",
              "```", "\n".join(lines), "```", "", "## Honest limitations", "",
              "- The registry did not exist before 2026-10-25; every 'proven' case shows the source carried the listing early, not that this system ran then.",
              "- 'Plausible' means the venue's own feed is registered and healthy today, but the past listing is gone and no snapshot was captured.",
              "- Freight & Salvage, SFJAZZ and Eventbrite pages are blocked for the collector; events only visible there depend on Songkick's partial coverage, Bluegrass Signal or an Eventbrite API token.",
              "- Rules-only tiers above are computed from title + venue alone, the way a bare listing arrives; model enrichment (when a key is configured) is what lifts unknown names such as Rakish or Scottish Fish.",
              "- The taste profile (taste.yaml) was written knowing these events exist, so rows whose title names a seed artist (Stampfel, Mountain Grass Unit, Tony Furtado, Nora Brown, Laurie Lewis, Kathy Kallick) are hindsight-tuned for the ranking column; only the unknown-name rows say anything about ranking recall. The discoverability columns (class, lead) do not depend on the taste profile."]
    (config.ROOT / "benchmark" / "REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return summary
