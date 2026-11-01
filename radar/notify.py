"""Stage E: alerts as GitHub Issues (weekly Monday email; between Mondays only exceptional shows in small rooms).

Why GitHub Issues: zero secrets (GITHUB_TOKEN is provided to every workflow run), GitHub e-mails the
assignee/mentioned user, every alert is a permanent, searchable record with a comment thread, and the
same code path can later fan out to e-mail or push by adding a channel. data/alerts.json remembers
what was already announced so unchanged events are never re-alerted, while the digest keeps every
still-upcoming flagged event on the shortlist until it happens.
"""
import datetime as dt
import os
import re

import requests

from . import config, store
from .normalize import TZ, region_of

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
    for name, color, desc in ((LABEL_ALERT, "d93f0b", "Exceptional show in a small room (book ahead)"),
                              (LABEL_DIGEST, "0e8a16", "Weekly Monday email"),
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


def _lead(e) -> str:
    """Lead time and ticket status line. Ticket availability is never inferred from a listing."""
    try:
        fs = dt.datetime.fromisoformat(e["first_seen"]).astimezone(TZ).date()
        d = dt.date.fromisoformat(e["date"])
        today = dt.datetime.now(TZ).date()
        lead = f"first seen {fs:%b %-d} ({(d - fs).days} days before the show); {(d - today).days} days from today"
    except (ValueError, KeyError):
        lead = ""
    research = e.get("research") or {}
    ts = research.get("ticket_status") or "unverified (check the source link)"
    return f"Lead time: {lead} · Tickets: {ts}"


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
             _lead(e),
             f"Score {e.get('final_score', e.get('score'))} (rules {e.get('score')}" + (f", model fit {enr.get('fit')}" if enr.get("fit") is not None else "") + f") · tier **{e.get('tier')}** · first seen {e['first_seen'][:10]}",
             " · ".join(links[:6])]
    return "\n".join(l for l in lines if l)


# ----------------------------------------------------------------------------- small rooms
_BOOK = None


def book_ahead(e) -> bool:
    """Is this show in a small room that can sell out (taste.yaml venues.book_ahead / book_ahead_patterns)?"""
    global _BOOK
    if _BOOK is None:
        from .normalize import fold
        from .rank import load_taste
        v = load_taste().get("venues", {})
        names = [re.sub(r"^the ", "", fold(x)) for x in v.get("book_ahead", [])]
        pats = [fold(x) for x in v.get("book_ahead_patterns", [])]
        _BOOK = (fold, [x for x in names + pats if x])
    fold, keys = _BOOK
    text = fold(" ".join(str(x) for x in (e.get("venue"), e.get("venue_raw")) if x))
    return any(k in text for k in keys)


def _tickets(e) -> str:
    return (e.get("research") or {}).get("ticket_status") or "unverified"


def _one_liner(e) -> str:
    """One line per show; research reason when there is one."""
    r = e.get("research") or {}
    why = (r.get("reason") or "").split(". ")[0].strip()
    if why:
        return why + ("" if why.endswith(".") else ".")
    reasons = [re.sub(r"\s*\(\+\d+\)", "", x).replace("_", " ") for x in e.get("score_reasons", [])[:2]]
    return "Rules match (not yet researched): " + "; ".join(reasons) if reasons else ""


def _row(e, alerts, today, why=False) -> str:
    d = dt.date.fromisoformat(e["date"])
    when = _when(e).split(" · ")
    t = when[1] if len(when) > 1 and when[1] != "12 AM" else ""
    day = f"{d:%a %b %-d}" + (f", {d.year}" if d.year != today.year else "") + (f" · {t}" if t else "")
    links = [f"[source]({e['url']})"] if e.get("url") else []
    if e.get("ticket_url") and e["ticket_url"] != e.get("url"):
        links.append(f"[tickets]({e['ticket_url']})")
    flags = []
    if e["id"] not in alerts["alerted"]:
        flags.append("**NEW**")
    if _tickets(e) != "unverified":
        flags.append(f"tickets: {_tickets(e)}")
    head = (f"- **{day}** · {e['title'][:80]} · {e.get('venue') or e.get('venue_raw') or '?'}"
            + (f", {e['city']}" if e.get("city") and e["city"].lower() not in (e.get("venue") or "").lower() else "")
            + f" · {e.get('tier')} {round(e.get('final_score') or e.get('score') or 0)}"
            + (" · " + " · ".join(flags) if flags else "") + (" · " + " ".join(links) if links else ""))
    if why:
        w = _one_liner(e)
        if w:
            head += f"\n  {w}"
    return head


# ----------------------------------------------------------------------------- immediate alerts
def bootstrap(events, alerts):
    """First live run: record what is already exceptional in a small room WITHOUT posting, so going live
    does not send a burst. The first Monday email lists all of it in "Book now"."""
    today = dt.datetime.now(TZ).date().isoformat()
    for e in events.values():
        if e.get("tier") == "exceptional" and e.get("status") == "scheduled" and e["date"] >= today and book_ahead(e):
            alerts["alerted"][e["id"]] = {"at": config.now_iso(), "issue": None, "date": e["date"], "status": e["status"],
                                          "tier": "exceptional", "via": "bootstrap"}
    alerts["bootstrapped"] = config.now_iso()
    return 0


def immediate(events, alerts, h, dry_run):
    """The only alerts between Mondays: an exceptional show in a small room (book_ahead) that has not been
    announced before. Everything else waits for the weekly email. Date/status changes to an alerted show
    are added as a comment on its issue (no new email thread)."""
    today = dt.datetime.now(TZ).date().isoformat()
    sent = 0
    if not alerts.get("bootstrapped"):
        return bootstrap(events, alerts)
    for e in sorted(events.values(), key=lambda x: x["date"]):
        if e.get("tier") != "exceptional" or e.get("status") != "scheduled" or e["date"] < today or not book_ahead(e):
            continue
        rec = alerts["alerted"].get(e["id"])
        changed = rec and (rec.get("date") != e["date"] or rec.get("status") != e["status"])
        if rec and not changed:
            continue
        if rec and changed:
            if rec.get("issue"):
                comment_issue(h, rec.get("issue"), f"Update: now **{_when(e)}**, status {e['status']}.\n\n{event_card(e)}", dry_run)
            rec.update({"date": e["date"], "status": e["status"], "updated": config.now_iso()})
            continue
        title = f"[radar] Book ahead: {e['title'][:60]} · {e['date']} @ {e.get('venue') or e.get('venue_raw') or '?'}"
        body = (f"@{_owner()} an exceptional show in a small room that can sell out.\n\n{event_card(e)}\n\n"
                f"<sub>Event id `{e['id']}`. This is the only kind of alert sent between Monday emails. "
                f"Inventory: https://{_owner()}.github.io/{_repo().split('/')[1]}/</sub>")
        num = create_issue(h, title, body, [LABEL_ALERT], dry_run)
        alerts["alerted"][e["id"]] = {"at": config.now_iso(), "issue": num, "date": e["date"], "status": e["status"], "tier": e["tier"]}
        sent += 1
    return sent


# ----------------------------------------------------------------------------- weekly digest
SHORTLIST_MIN = 70  # strong shows below this stay on the site and calendar feed (feed bar is 65); keeps the email to ~60 lines


def digest(events, alerts, h, dry_run, horizon_days=75):
    """The Monday email, ordered by when Erik has to act:
    The shortlist is exceptional shows plus strong ones scoring SHORTLIST_MIN or more.
    1. Book now: shortlist shows in small rooms (book_ahead) more than two weeks out, any distance ahead.
    2. This week and next: shortlist shows in the next 14 days.
    3. Further out: the rest of the shortlist up to the horizon.
    NEW marks a show not in any earlier email or alert."""
    today = dt.datetime.now(TZ).date()
    soon_end = (today + dt.timedelta(days=13)).isoformat()
    end = (today + dt.timedelta(days=horizon_days)).isoformat()
    week = today.isocalendar()
    last = alerts["digests"][-1]["at"][:10] if alerts["digests"] else "never"
    up = [e for e in events.values() if e.get("status") == "scheduled" and e["date"] >= today.isoformat()
          and e.get("tier") in ("exceptional", "strong") and e.get("region") != "outside"
          and region_of(e.get("city")) != "outside"]  # region is set at first ingest; recheck with today's city list
    by_date = lambda x: (x["date"], x.get("start", ""))
    shortlist = lambda e: e.get("tier") == "exceptional" or (e.get("final_score") or 0) >= SHORTLIST_MIN
    up = [e for e in up if shortlist(e)]
    book = sorted([e for e in up if e["date"] > soon_end and book_ahead(e) and _tickets(e) != "sold-out"], key=by_date)
    soon = sorted([e for e in up if e["date"] <= soon_end], key=by_date)
    later = sorted([e for e in up if soon_end < e["date"] <= end and not book_ahead(e) and shortlist(e)], key=by_date)
    listed = book + soon + later
    new = [e for e in listed if e["id"] not in alerts["alerted"]]
    health = store.load_health()
    failing = sorted(k for k, v in health.items() if v.get("last_status") not in ("ok", None, "partial"))
    parts = [f"@{_owner()} radar for the week of {today:%b %-d}: {len(book)} to book ahead, {len(soon)} in the next two weeks, "
             f"{len(later)} further out; {len(new)} new since {last}.", ""]
    parts.append(f"## Book now: small rooms that can sell out ({len(book)})")
    parts.append("Top picks in small rooms, however far ahead; each stays listed until it happens or is marked sold out.")
    parts += [_row(e, alerts, today, why=True) for e in book] or ["- nothing in small rooms right now"]
    parts.append("")
    parts.append(f"## This week and next ({len(soon)})")
    parts += [_row(e, alerts, today, why=e["id"] not in alerts["alerted"]) for e in soon] or ["- nothing above the bar in the next two weeks"]
    parts.append("")
    parts.append(f"## Further out, through {dt.date.fromisoformat(end):%b %-d} ({len(later)})")
    parts += [_row(e, alerts, today, why=e["id"] not in alerts["alerted"]) for e in later[:150]] or ["- nothing yet"]
    if len(later) > 150:
        parts.append(f"- ...and {len(later) - 150} more on the site")
    parts.append("")
    if failing:
        parts.append(f"Sources needing attention: {', '.join(failing)}")
    parts.append(f"<sub>Everything, including lower-rated shows: https://{_owner()}.github.io/{_repo().split('/')[1]}/ · "
                 f"calendar feed: https://{_owner()}.github.io/{_repo().split('/')[1]}/radar.ics</sub>")
    body = "\n".join(parts)
    title = f"[radar] Week of {today:%b %-d}: {len(book)} to book ahead, {len(new)} new"
    num = create_issue(h, title, body, [LABEL_DIGEST], dry_run)
    alerts["digests"].append({"at": config.now_iso(), "issue": num, "strong": len(listed), "new": len(new)})
    for e in new:
        alerts["alerted"][e["id"]] = {"at": config.now_iso(), "issue": num, "date": e["date"], "status": e["status"], "tier": e["tier"], "via": "digest"}
    return len(listed)


def live_enabled() -> bool:
    """Real issues are only posted from main (or when RADAR_NOTIFY_LIVE=1); branch runs print instead."""
    if os.environ.get("RADAR_NOTIFY_LIVE") == "1":
        return True
    return os.environ.get("GITHUB_REF", "") == "refs/heads/main"


def test_alert(event_id=None, dry_run=False):
    """One clearly labelled test issue, posted by the Actions bot so GitHub emails the owner."""
    events = store.load_events()
    today = dt.datetime.now(TZ).date().isoformat()
    ex = [e for e in events.values() if e.get("tier") == "exceptional" and e.get("status") == "scheduled" and e["date"] >= today]
    e = events.get(event_id) if event_id else sorted(ex, key=lambda x: -(x.get("final_score") or 0))[0]
    title = "[radar] TEST ALERT: please confirm this email reached you"
    body = (f"@{_owner()} this is a delivery test from the Bay Area Event Radar (branch radar-v2). If you got this by email, "
            f"reply here with \"received\" or tell Claude. It shows exactly what a real alert looks like:\n\n{event_card(e)}\n\n"
            f"<sub>Test only. Real alerts use the same path: posted by github-actions, assigned to you, label radar-alert.</sub>")
    h = _headers()
    if not dry_run:
        ensure_labels(h)
    num = create_issue(h, title, body, [LABEL_ALERT], dry_run)
    print(f"[notify] test alert issue #{num}")
    return title, body


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
