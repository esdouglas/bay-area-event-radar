"""Stage F: detect stale or broken collection and raise a radar-ops issue.

Exit code is non-zero when something is wrong so the workflow itself turns red. A successful process
run is not success: this also checks that the inventory actually grew recently and that the key
grassroots sources are returning events."""
import datetime as dt

from . import config, store
from .collect import load_sources
from .notify import LABEL_OPS, _headers, comment_issue, create_issue, ensure_labels, find_open_issue

KEY_SOURCES = ["little-hill-lounge", "cafe-du-nord", "songkick-bay-area", "bluegrass-signal", "california-bluegrass-association",
               "back-room-berkeley", "fifth-street-farms", "sf-folk-music-club", "kalx-entertainment-calendar"]


def run(dry_run=False, max_stale_hours=14):
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
    enabled = {s["id"] for s in load_sources() if s.get("enabled", True)}
    broken = [k for k, v in health.items() if k in enabled and v.get("consecutive_failures", 0) >= 3]
    if broken:
        problems.append(f"sources failing 3+ runs in a row: {', '.join(sorted(broken))}")
    for k in KEY_SOURCES:
        h = health.get(k)
        if k in enabled and h and h.get("last_status") == "ok" and h.get("last_count", 0) == 0:
            problems.append(f"key source {k} returned ok but zero events (parser drift?)")
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
        if num:
            comment_issue(h, num, body)
        else:
            create_issue(h, "[radar ops] collection needs attention", body, [LABEL_OPS])
    return 1
