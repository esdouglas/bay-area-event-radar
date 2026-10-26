"""Quick terminal summary of inventory and source health."""
import datetime as dt

from . import config, llm, store
from .collect import load_sources
from .normalize import TZ


def run():
    events = store.load_events()
    health = store.load_health()
    today = dt.datetime.now(TZ).date().isoformat()
    up = [e for e in events.values() if e.get("status") == "scheduled" and e["date"] >= today]
    tiers = {}
    for e in up:
        tiers[e.get("tier") or "unscored"] = tiers.get(e.get("tier") or "unscored", 0) + 1
    print(f"inventory: {len(events)} total, {len(up)} upcoming; tiers {tiers}")
    multi = sum(1 for e in up if len({s['source'] for s in e['sources']}) > 1)
    print(f"confirmed by 2+ sources: {multi}; model spend 30d: ${llm.cost_summary(30)['usd']}")
    print(f"{'source':36} {'status':9} {'last ok':17} {'kept':>5} {'fail':>4}")
    for s in load_sources():
        h = health.get(s["id"], {})
        print(f"{s['id']:36} {str(h.get('last_status') or ('off' if not s.get('enabled', True) else '-')):9} {str(h.get('last_ok') or '')[:17]:17} {str(h.get('last_count', '')):>5} {h.get('consecutive_failures', 0):>4}  {str(h.get('last_error') or '')[:60]}")
    top = sorted(up, key=lambda e: -(e.get("final_score") or e.get("score") or 0))[:25]
    print("\ntop upcoming:")
    for e in top:
        print(f"  {e['date']} {e.get('final_score', e.get('score')):5} {e.get('tier', ''):11} {e['title'][:52]:52} {e.get('venue') or e.get('venue_raw') or '':28}")
