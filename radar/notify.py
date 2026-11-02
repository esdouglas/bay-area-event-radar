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
from . import mailer
from .picks import book_ahead, cfg, one_per_act, pick_score, zone

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


# ----------------------------------------------------------------------------- formatting helpers
def _tickets(e) -> str:
    return (e.get("research") or {}).get("ticket_status") or "unverified"


# ----------------------------------------------------------------------------- immediate alerts
def _alertable(e, today) -> bool:
    s = pick_score(e)
    return (e.get("status") == "scheduled" and e["date"] >= today and book_ahead(e)
            and s is not None and s >= cfg()["digest"]["alert_min"])


def bootstrap(events, alerts):
    """First live run: record what already qualifies for an alert WITHOUT posting, so going live does
    not send a burst. The first Monday email covers it."""
    today = dt.datetime.now(TZ).date().isoformat()
    for e in events.values():
        if _alertable(e, today):
            alerts["alerted"][e["id"]] = {"at": config.now_iso(), "issue": None, "date": e["date"], "status": e["status"],
                                          "tier": e.get("tier"), "via": "bootstrap"}
    alerts["bootstrapped"] = config.now_iso()
    return 0


def immediate(events, alerts, h, dry_run):
    """The only alerts between Mondays: a show in a small room (book_ahead) whose pick score reaches
    digest.alert_min, not announced before. Date/status changes go on its issue as a comment."""
    today = dt.datetime.now(TZ).date().isoformat()
    sent = 0
    if not alerts.get("bootstrapped"):
        return bootstrap(events, alerts)
    for e in sorted(events.values(), key=lambda x: x["date"]):
        if not _alertable(e, today):
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
        title = f"Book ahead: {_short_name(e['title'], 50)}, {e['date']} at {e.get('venue') or e.get('venue_raw') or '?'}"
        body = (f"@{_owner()} a top pick in a small room that can sell out.\n\n{event_card(e)}\n\n"
                f"<sub>Event id `{e['id']}`. This is the only kind of alert sent between Monday emails. "
                f"Inventory: https://{_owner()}.github.io/{_repo().split('/')[1]}/</sub>")
        num = None
        if not dry_run and mailer.configured():
            c = {"title": _clean_title(e["title"])[:90], "when": _day(e, dt.datetime.now(TZ).date()),
                 "where": (e.get("venue") or e.get("venue_raw") or "?") + (f", {e['city']}" if e.get("city") else ""),
                 "tags": ["small room, can sell out"], "why": " ".join(re.split(r"(?<=[.!?])\s+", ((e.get("research") or {}).get("reason") or _why(e)).strip())[:3]),
                 "links": [("Details", e.get("url"))] + ([("Tickets", e["ticket_url"])] if e.get("ticket_url") and e["ticket_url"] != e.get("url") else [])}
            secs = [{"title": "Book ahead", "cards": [c]}]
            intro = "A top pick in a small room that can sell out. This is the only kind of note sent between Monday emails."
            site = f"https://{_owner()}.github.io/{_repo().split('/')[1]}/"
            subj = f"Book ahead: {_short_name(e['title'], 50)}, {_day(e, dt.datetime.now(TZ).date()).split(',')[0]} at {e.get('venue') or e.get('venue_raw') or '?'}"
            if mailer.send(subj, mailer.render_html(_short_name(e["title"], 60), intro, secs, [("Everything the radar found", site)]),
                           mailer.render_text(subj, intro, secs, [("Everything the radar found", site)])):
                num = "email"
        if num is None:
            num = create_issue(h, title, body, [LABEL_ALERT], dry_run)
        alerts["alerted"][e["id"]] = {"at": config.now_iso(), "issue": num, "date": e["date"], "status": e["status"], "tier": e.get("tier")}
        alerts.setdefault("picked", {})[e["id"]] = {"at": config.now_iso(), "date": e["date"]}
        sent += 1
    return sent


# ----------------------------------------------------------------------------- weekly digest
def digest(events, alerts, h, dry_run, horizon_days=120):
    """The Monday email: a handful of picks, not a list (Erik goes to about one show every two weeks).
      Next two weeks   up to max_soon picks in the next 14 days, best first
      New, book ahead  up to max_new_ahead picks further out not in an earlier email; small rooms get +5
      Still ahead      earlier picks still to come, one line each, soonest first
      Also nearby      up to max_also near/mid shows in the next 14 days just under the pick bar
    Picks are one per act (the nearest/best date of a touring act). Settings: taste.yaml `digest`."""
    D = cfg()["digest"]
    today = dt.datetime.now(TZ).date()
    soon_end = (today + dt.timedelta(days=13)).isoformat()
    end = (today + dt.timedelta(days=horizon_days)).isoformat()
    picked = alerts.setdefault("picked", {})
    last = alerts["digests"][-1]["at"][:10] if alerts["digests"] else None
    up = [e for e in events.values() if e.get("status") == "scheduled" and today.isoformat() <= e["date"] <= end
          and e.get("region") != "outside" and region_of(e.get("city")) != "outside"]
    scored = [(e, pick_score(e)) for e in up]
    picks = one_per_act([e for e, s in scored if s is not None and s >= D["pick_min"]], key=pick_score)
    pick_ids = {e["id"] for e in picks}
    by_score = lambda e: -pick_score(e)
    by_date = lambda e: (e["date"], e.get("start", ""))
    soon = sorted(sorted([e for e in picks if e["date"] <= soon_end], key=by_score)[:D["max_soon"]], key=by_date)
    later = [e for e in picks if e["date"] > soon_end]
    new_ahead = sorted([e for e in later if e["id"] not in picked], key=lambda e: -(pick_score(e) + (5 if book_ahead(e) else 0)))[:D["max_new_ahead"]]
    still = sorted([e for e in later if e["id"] in picked], key=by_date)[:D["max_still_ahead"]]
    shown = {e["id"] for e in soon + new_ahead + still}
    also = one_per_act([e for e, s in scored if s is not None and 65 <= s < D["pick_min"] and e["date"] <= soon_end
                        and zone(e) != "far" and e["id"] not in pick_ids], key=pick_score)
    also = sorted(sorted(also, key=by_score)[:D["max_also"]], key=by_date)

    def links(e):
        out = [("Details", e.get("url"))] if e.get("url") else []
        if e.get("ticket_url") and e["ticket_url"] != e.get("url"):
            out.append(("Tickets", e["ticket_url"]))
        return out

    def where(e):
        v = e.get("venue") or e.get("venue_raw") or "?"
        return v + (f", {e['city']}" if e.get("city") and e["city"].lower() not in v.lower() else "")

    def card(e):
        r = e.get("research") or {}
        why = (r.get("reason") or "").strip() or "A seed artist is on the bill; not researched yet."
        why = " ".join(re.split(r"(?<=[.!?])\s+", why)[:2])
        t = _tickets(e)
        tags = [x for x in ("small room, can sell out" if book_ahead(e) else "",
                            ("sold out at the box office" if t == "sold-out" else f"tickets {t}") if t != "unverified" else "",
                            {"mid": "a drive", "far": "a trip, but special"}.get(zone(e), "")) if x]
        return {"title": _clean_title(e["title"])[:90], "when": _day(e, today), "where": where(e), "tags": tags, "why": why, "links": links(e)}

    def line(e):
        return {"when": _day(e, today), "title": _clean_title(e["title"])[:70], "where": where(e),
                "tag": "small room" if book_ahead(e) else "", "url": e.get("url")}

    sections = [{"title": "Next two weeks", "cards": [card(e) for e in soon], "empty": "Nothing clears the bar. A quiet fortnight."},
                {"title": "New, book ahead", "cards": [card(e) for e in new_ahead]},
                {"title": "Still ahead, from earlier emails", "lines": [line(e) for e in still]},
                {"title": "Also nearby, just under the bar", "lines": [line(e) for e in also]}]
    n_soon, n_new = len(soon), len(new_ahead)
    intro = (f"{n_soon} worth considering in the next two weeks" if n_soon else "Nothing pressing in the next two weeks") + \
            (f", and {n_new} new to book ahead." if n_new else ".")
    health = store.load_health()
    failing = sorted(k for k, v in health.items() if v.get("last_status") not in ("ok", None, "partial"))
    note = f"Sources needing attention: {', '.join(failing)}" if failing else ""
    site = f"https://{_owner()}.github.io/{_repo().split('/')[1]}/"
    footer = [("Everything the radar found", site), ("Source health", site + "dashboard.html")]
    heads = [_short_name(e["title"]) for e in (soon + new_ahead)[:2]]
    rest = n_soon + n_new - len(heads)
    subject = (f"Shows for the week of {today:%b %-d}: " + (" & ".join(heads) if len(heads) < 2 else f"{heads[0]}, {heads[1]}")
               + (f" + {rest} more" if rest > 0 else "")) if heads else f"Shows for the week of {today:%b %-d}: a quiet week"
    num = None
    emailed = False
    if not dry_run and mailer.configured():
        emailed = mailer.send(subject, mailer.render_html(f"Week of {today:%B %-d}", intro, sections, footer, note),
                              mailer.render_text(f"Week of {today:%B %-d}", intro, sections, footer, note))
    if dry_run:
        print(mailer.render_text(subject, intro, sections, footer, note))
    elif not emailed:
        num = create_issue(h, subject, f"@{_owner()} " + mailer.render_markdown(intro, sections, footer, note), [LABEL_DIGEST], dry_run)
    alerts["digests"].append({"at": config.now_iso(), "issue": num, "emailed": emailed, "subject": subject, "soon": len(soon), "new_ahead": len(new_ahead)})
    for e in soon + new_ahead:
        picked.setdefault(e["id"], {"at": config.now_iso(), "date": e["date"]})
        alerts["alerted"].setdefault(e["id"], {"at": config.now_iso(), "issue": num, "date": e["date"], "status": e["status"],
                                               "tier": e.get("tier"), "via": "digest"})
    return len(shown)


def _clean_title(t):
    """Drop a date the venue repeats in the title ("KENDL WINTER -- SATURDAY, DECEMBER 12", "... DEC. 16 2026")."""
    t = re.sub(r"\s*(?:--|[\u2014\u2013-])?\s*(?:(?:mon|tues?|wed(?:nes)?|thu(?:rs)?|fri|sat(?:ur)?|sun)(?:day)?\.?,?\s+)?"
               r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:,?\s+20\d\d)?\s*$", "", t, flags=re.I)
    t = t.strip(" -\u2014\u2013") or t
    if t.isupper() and len(t) > 4:
        t = re.sub(r"\b(\w)(\w*)", lambda m: m.group(1) + m.group(2).lower(), t)
    return t


def _short_name(t, n=40):
    """Subject-line name: no repeated date, no subtitle after a colon or dash, cut at a word boundary."""
    t = re.split(r"\s*(?::|\s[-\u2013\u2014|]\s)\s*", _clean_title(t))[0].strip()
    t = re.sub(r"^(?:Ms|Mr|Mrs|Dr)\.\s+", "", t)
    if len(t) > n:
        t = t[:n].rsplit(" ", 1)[0].rstrip(",&+ ") + "..."
    return t


def _day(e, today):
    d = dt.date.fromisoformat(e["date"])
    when = _when(e).split(" · ")
    t = when[1] if len(when) > 1 and when[1] != "12 AM" else ""
    return f"{d:%a %b %-d}" + (f", {d.year}" if d.year != today.year else "") + (f", {t}" if t else "")


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
