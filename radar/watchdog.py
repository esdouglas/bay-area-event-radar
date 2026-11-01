"""Stage F: detect stale or broken collection and raise a radar-ops issue.

A successful process run is not success: this also checks that the inventory actually grew recently and
that the key grassroots sources are returning events.

How problems reach Erik: ONE open "[radar ops]" issue (GitHub e-mails it), commented on only when the set
of problems changes. The exit code stays 0 so a problem never also turns the workflow red: every red run
makes GitHub send a separate "Run failed" e-mail, which Erik asked not to get (2026-11-01). Pass
--strict to get a non-zero exit for local checks.
A single ordinary source failing three runs in a row is listed on the dashboard, not raised as an issue:
sources like Songkick flap (CDN refusals) and recover by themselves."""
import datetime as dt

from . import config, store
from .collect import load_sources
from .notify import LABEL_OPS, _headers, comment_issue, create_issue, ensure_labels, find_open_issue

KEY_SOURCES = ["little-hill-lounge", "cafe-du-nord", "songkick-bay-area", "bluegrass-signal", "california-bluegrass-association",
               "back-room-berkeley", "fifth-street-farms", "sf-folk-music-club", "kalx-entertainment-calendar"]


def run(dry_run=False, max_stale_hours=14, strict=False):
    problems = []
    summary = store._load(config.RUN_SUMMARY_FILE, {})
    health = store.load_health()
    events = store.load_events()
    now = config.now_utc()
    ts = summary.get("ts")
    if not ts:
        problems.append("no collection run recorded")
    else:
        age = (now - dt.datetime.fromisoformat(ts)).total_seconds() / 3600
        if age > max_stale_hours:
            problems.append(f"last collection was {age:.0f} h ago (limit {max_stale_hours} h): the schedule may be disabled or failing")
    srcs = load_sources()
    enabled = {s["id"] for s in srcs if s.get("enabled", True)}
    expected_blocked = {s["id"] for s in srcs if s.get("expected_blocked")}
    broken = [k for k, v in health.items() if k in enabled and k not in expected_blocked and v.get("consecutive_failures", 0) >= 3]
    if broken:
        print(f"[watchdog] note: sources failing 3+ runs in a row (dashboard only): {', '.join(sorted(broken))}")
    if len(broken) >= max(5, len(enabled) // 5):
        problems.append(f"{len(broken)} sources failing 3+ runs in a row (network or runner trouble?): {', '.join(sorted(broken))}")
    for k in KEY_SOURCES:
        h = health.get(k)
        if k in enabled and h and h.get("last_status") == "ok" and h.get("last_count", 0) == 0:
            problems.append(f"key source {k} returned ok but zero events (parser drift?)")
        if k in enabled and k not in expected_blocked and h and h.get("last_status") not in ("ok", "partial", None) and h.get("consecutive_failures", 0) >= 2:
            problems.append(f"key source {k} failing: {h.get('last_status')} ({str(h.get('last_error') or '')[:80]})")
    zero = sorted(k for k, v in health.items() if k in enabled and v.get("last_status") == "ok" and v.get("last_count", 0) == 0)
    if zero:
        print(f"[watchdog] note: {len(zero)} enabled sources returned zero events: {', '.join(zero)}")
    upcoming = sum(1 for e in events.values() if e.get("status") == "scheduled")
    if upcoming < 200:
        problems.append(f"inventory has only {upcoming} upcoming events; collection is not working")
    recent_new = sum(1 for e in events.values() if (now - dt.datetime.fromisoformat(e["first_seen"])).days <= 7)
    if ts and recent_new == 0:
        problems.append("no new events discovered in the last 7 days")
    if not problems:
        print(f"[watchdog] ok: last run {ts}, {upcoming} upcoming, {recent_new} new this week")
        return 0
    body = "@esdouglas the radar needs attention:\n\n" + "\n".join(f"- {p}" for p in problems) + \
        f"\n\n<sub>Checked {config.now_iso()}. Dashboard: https://esdouglas.github.io/bay-area-event-radar/dashboard.html · Actions: https://github.com/esdouglas/bay-area-event-radar/actions</sub>"
    print("[watchdog] PROBLEMS:\n" + "\n".join(f"- {p}" for p in problems))
    h = _headers()
    from .notify import live_enabled
    if h is not None and not dry_run and live_enabled():
        ensure_labels(h)
        num = find_open_issue(h, LABEL_OPS, "[radar ops]")
        if not num:
            create_issue(h, "[radar ops] collection needs attention", body, [LABEL_OPS])
        elif _last_problems(h, num) != set(problems):
            comment_issue(h, num, body)
        else:
            print(f"[watchdog] same problems already reported on #{num}; not commenting again")
    return 1 if strict else 0


def _last_problems(h, number) -> set:
    """Problem lines of the newest report on the open ops issue (its last comment, else its body)."""
    import requests
    from .notify import API, _repo
    try:
        r = requests.get(f"{API}/repos/{_repo()}/issues/{number}/comments", headers=h, params={"per_page": 100}, timeout=30)
        bodies = [c.get("body") or "" for c in r.json()] if r.status_code == 200 else []
        if not bodies:
            r = requests.get(f"{API}/repos/{_repo()}/issues/{number}", headers=h, timeout=30)
            bodies = [r.json().get("body") or ""] if r.status_code == 200 else []
    except (requests.RequestException, ValueError):
        return set()
    last = bodies[-1] if bodies else ""
    return {l[2:] for l in last.splitlines() if l.startswith("- ")}
