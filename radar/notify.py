"""Stage E: alerts as GitHub Issues (immediate exceptional finds; weekly digest).

Why GitHub Issues: zero secrets (GITHUB_TOKEN is provided to every workflow run), GitHub e-mails the
assignee/mentioned user, every alert is a permanent, searchable record with a comment thread, and the
same code path can later fan out to e-mail or push by adding a channel. data/alerts.json remembers
what was already announced so unchanged events are never re-alerted, while the digest keeps every
still-upcoming flagged event on the shortlist until it happens.
"""
import datetime as dt
import os

import requests

from . import config, llm, store
from .normalize import TZ

API = "https://api.github.com"
LABEL_ALERT = "radar-alert"
LABEL_DIGEST = "radar-digest"
LABEL_OPS = "radar-ops"


def _repo():
    return os.environ.get("GITHUB_REPOSITORY", "esdouglas/bay-area-event-radar")


def _owner():
    return _repo().split("/")[0]


def _headers():
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not tok:
        return None
    return {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


def ensure_labels(h):
    for name, color, desc in ((LABEL_ALERT, "d93f0b", "Immediate exceptional discovery"),
                              (LABEL_DIGEST, "0e8a16", "Weekly discovery digest"),
                              (LABEL_OPS, "5319e7", "Collection health / operations")):
        r = requests.get(f"{API}/repos/{_repo()}/labels/{name}", headers=h, timeout=20)
        if r.status_code == 404:
            requests.post(f"{API}/repos/{_repo()}/labels", headers=h, json={"name": name, "color": color, "description": desc}, timeout=20)


def create_issue(h, title, body, labels, dry_run=False):
    if dry_run or h is None:
        print(f"--- [dry-run issue] {title}\n{body[:1500]}\n---")
        return None
    r = requests.post(f"{API}/repos/{_repo()}/issues", headers=h, timeout=30,
                      json={"title": title, "body": body, "labels": labels, "assignees": [_owner()]})
    if r.status_code >= 300:
        print(f"[notify] issue create failed {r.status_code}: {r.text[:200]}")
        return None
    return r.json().get("number")


def comment_issue(h, number, body, dry_run=False):
    if dry_run or h is None or not number:
        print(f"--- [dry-run comment on #{number}]\n{body[:800]}\n---")
        return
    requests.post(f"{API}/repos/{_repo()}/issues/{number}/comments", headers=h, json={"body": body}, timeout=30)


def find_open_issue(h, label, title_prefix):
    if h is None:
        return None
    r = requests.get(f"{API}/repos/{_repo()}/issues", headers=h, params={"labels": label, "state": "open", "per_page": 50}, timeout=30)
    if r.status_code != 200:
        return None
    for it in r.json():
        if it.get("title", "").startswith(title_prefix):
            return it.get("number")
    return None


# ----------------------------------------------------------------------------- formatting
def _when(e):
    try:
        d = dt.datetime.fromisoformat(e["start"]).astimezone(TZ)
        return d.strftime("%a %b %-d, %Y · %-I:%M %p").replace(":00 ", " ")
    except (ValueError, TypeError):
        return e.get("date", "?")


def _why(e):
    enr = e.get("enrichment") or {}
    deep = enr.get("deep") or {}
    fast = enr.get("fast") or {}
    if deep.get("why"):
        return deep["why"]
    if fast.get("why"):
        return fast["why"]
    return "; ".join(e.get("score_reasons", [])[:3]) or "matches the taste profile"


def _uncertainty(e):
    enr = e.get("enrichment") or {}
    deep = enr.get("deep") or {}
    bits = []
    if deep.get("uncertainty") and deep["uncertainty"].lower() != "none":
        bits.append(deep["uncertainty"])
    if e.get("region") == "unknown":
        bits.append("location not resolved from the listing")
    if len({s["source"] for s in e["sources"]}) == 1:
        bits.append(f"single source ({e['sources'][0]['source']})")
    if not e.get("enrichment"):
        bits.append("rules-only score (no model research yet)")
    return "; ".join(bits) or "none noted"


def event_card(e) -> str:
    enr = e.get("enrichment") or {}
    deep = enr.get("deep") or {}
    head = deep.get("headline") or ""
    links = [f"[source]({e['url']})"] if e.get("url") else []
    if e.get("ticket_url") and e["ticket_url"] != e.get("url"):
        links.append(f"[tickets]({e['ticket_url']})")
    for s in e["sources"]:
        if s.get("url") and s["url"] != e.get("url"):
            links.append(f"[{s['source']}]({s['url']})")
    lines = [f"### {e['title']}",
             f"**{_when(e)}** · {e.get('venue') or e.get('venue_raw') or '?'}{', ' + e['city'] if e.get('city') else ''}"
             + (f" · {e['price']}" if e.get("price") else ""),
             (f"*{head}*" if head else ""),
             f"Why: {_why(e)}",
             (f"Background: {deep['background']}" if deep.get("background") else ""),
             (f"Scarcity: {deep['scarcity']}" if deep.get("scarcity") else ""),
             f"Uncertainty: {_uncertainty(e)}",
             f"Score {e.get('final_score', e.get('score'))} (rules {e.get('score')}" + (f", model fit {enr.get('fit')}" if enr.get("fit") is not None else "") + f") · tier **{e.get('tier')}** · first seen {e['first_seen'][:10]}",
             " · ".join(links[:6])]
    return "\n".join(l for l in lines if l)


# ----------------------------------------------------------------------------- immediate alerts
def immediate(events, alerts, h, dry_run):
    today = dt.datetime.now(TZ).date().isoformat()
    sent = 0
    for e in sorted(events.values(), key=lambda x: x["date"]):
        if e.get("tier") != "exceptional" or e.get("status") != "scheduled" or e["date"] < today:
            continue
        rec = alerts["alerted"].get(e["id"])
        changed = rec and (rec.get("date") != e["date"] or rec.get("status") != e["status"])
        if rec and rec.get("via") == "digest" and rec.get("tier") != "exceptional":
            rec = None  # only mentioned in a digest as strong; promotion to exceptional deserves its own alert
        if rec and not changed:
            continue
        if rec and changed:
            comment_issue(h, rec.get("issue"), f"Update: now **{_when(e)}**, status {e['status']}.\n\n{event_card(e)}", dry_run)
            rec.update({"date": e["date"], "status": e["status"], "updated": config.now_iso()})
            continue
        title = f"[radar] {e['title'][:70]} — {e['date']} @ {e.get('venue') or e.get('venue_raw') or '?'}"
        body = (f"@{_owner()} new exceptional discovery.\n\n{event_card(e)}\n\n"
                f"<sub>Event id `{e['id']}`. Reply here with notes; close the issue to dismiss. "
                f"Inventory: https://{_owner()}.github.io/{_repo().split('/')[1]}/</sub>")
        num = create_issue(h, title, body, [LABEL_ALERT], dry_run)
        alerts["alerted"][e["id"]] = {"at": config.now_iso(), "issue": num, "date": e["date"], "status": e["status"], "tier": e["tier"]}
        sent += 1
    return sent


# ----------------------------------------------------------------------------- weekly digest
def digest(events, alerts, h, dry_run, horizon_days=75):
    """Weekly digest. "New" means not announced in any earlier alert or digest (so an event that was
    merely in the inventory last week and became strong this week counts as new). Every strong-or-better
    event still upcoming is listed, so nothing drops off the shortlist just because it was mentioned."""
    today = dt.datetime.now(TZ).date()
    end = today + dt.timedelta(days=horizon_days)
    last = alerts["digests"][-1]["at"][:10] if alerts["digests"] else "never"
    week = today.isocalendar()
    upcoming = [e for e in events.values() if e.get("status") == "scheduled" and today.isoformat() <= e["date"] <= end.isoformat()]
    strong = sorted([e for e in upcoming if e.get("tier") in ("exceptional", "strong")], key=lambda x: (-(x.get("final_score") or 0), x["date"]))
    new_since = [e for e in strong if e["id"] not in alerts["alerted"]]
    still = [e for e in strong if e["id"] in alerts["alerted"]]
    soon = sorted([e for e in upcoming if e["date"] <= (today + dt.timedelta(days=14)).isoformat() and e.get("tier") in ("exceptional", "strong", "inventory") and (e.get("final_score") or 0) >= 40], key=lambda x: x["date"])
    inv_total = sum(1 for e in events.values() if e.get("status") == "scheduled")
    health = store.load_health()
    failing = sorted(k for k, v in health.items() if v.get("last_status") not in ("ok", None, "partial"))
    cost = llm.cost_summary(7)
    parts = [f"@{_owner()} weekly discovery digest for week {week.year}-W{week.week:02d}.",
             f"Inventory: **{inv_total}** upcoming events from {len(health)} registered sources; {len(strong)} rated strong or better in the next {horizon_days} days; "
             f"{len(new_since)} not announced before (last digest {last}). Model spend last 7 days: ${cost['usd']}.",
             ""]
    shown = set()
    if new_since:
        parts.append(f"## New ({len(new_since)})")
        for e in new_since[:60]:
            parts.append(event_card(e))
            shown.add(e["id"])
        if len(new_since) > 60:
            parts.append(f"- ...and {len(new_since) - 60} more new strong candidates on the site, sorted by score.")
        parts.append("")
    parts.append(f"## Next 14 days worth considering ({len(soon)})")
    parts += [f"- **{e['date']}** {e['title'][:70]} · {e.get('venue') or '?'} · {e.get('tier')} {e.get('final_score', e.get('score'))} · [source]({e.get('url')})" for e in soon[:80]] or ["- nothing above the bar in the next two weeks"]
    parts.append("")
    if still:
        parts.append(f"## Still upcoming, announced earlier ({len(still)})")
        parts += [f"- **{e['date']}** {e['title'][:70]} · {e.get('venue') or '?'} · {e.get('tier')} {e.get('final_score', e.get('score'))} · [source]({e.get('url')})" for e in still[:200]]
        parts.append("")
    if failing:
        parts.append(f"## Sources needing attention: {', '.join(failing)}")
    parts.append(f"<sub>Browse everything: https://{_owner()}.github.io/{_repo().split('/')[1]}/ · coverage dashboard on the same site.</sub>")
    body = "\n".join(parts)
    title = f"[radar digest] {week.year}-W{week.week:02d} — {len(strong)} strong candidates, {len(new_since)} new"
    num = create_issue(h, title, body, [LABEL_DIGEST], dry_run)
    alerts["digests"].append({"at": config.now_iso(), "issue": num, "strong": len(strong), "new": len(new_since)})
    for e in new_since:
        if e["id"] in shown:
            alerts["alerted"][e["id"]] = {"at": config.now_iso(), "issue": num, "date": e["date"], "status": e["status"], "tier": e["tier"], "via": "digest"}
    return len(strong)


def run(digest_flag=False, dry_run=False):
    events = store.load_events()
    alerts = store.load_alerts()
    if not dry_run and not live_enabled():
        print("[notify] not on main and RADAR_NOTIFY_LIVE unset: dry run")
        dry_run = True
    h = _headers()
    if h is None and not dry_run:
        print("[notify] no GITHUB_TOKEN; printing instead of posting")
        dry_run = True
    if h is not None and not dry_run:
        ensure_labels(h)
    n = immediate(events, alerts, h, dry_run)
    print(f"[notify] immediate alerts sent: {n}")
    if digest_flag:
        k = digest(events, alerts, h, dry_run)
        print(f"[notify] digest posted with {k} strong candidates")
    if not dry_run:
        store.save_alerts(alerts)
