"""Google Calendar sync into ONE dedicated calendar ("Erik event FYIs") via a service account.

Safety rules enforced in code, not just docs:
* Writes only to ALLOWED_CALENDAR_ID. Any other id, "primary", or an address-style id is refused.
* Events are transparent (free), have no reminders and no attendees.
* Event ids are deterministic ("radar" + sha1 hex of our id, valid base32hex), so re-running never
  duplicates: insert, and on 409 fetch + patch.
* Interest is never downgraded: if the calendar copy already says [Going]/[Interested] (set by you in
  Google Calendar or by the curated events.json), a later sync keeps it.
* Nothing is deleted. A cancelled listing is set to status "cancelled".

Credentials: GOOGLE_SERVICE_ACCOUNT_JSON (the key file's JSON text, from a GitHub secret).
Commands: python -m radar gcal test   (one event: create, read, update, dedup check)
          python -m radar gcal sync [--limit N] [--dry-run]
"""
import datetime as dt
import hashlib
import json
import os

import requests

from . import config, store
from .normalize import TZ, parse_dt

ALLOWED_CALENDAR_ID = "f3b3ddeec53f0e0b356d08e6084986db71205d675d22ece758d57ba450fd03da@group.calendar.google.com"
API = "https://www.googleapis.com/calendar/v3"
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
STATE_FILE = config.DATA / "gcal_state.json"
MIN_STRONG_SCORE = 65
INTERESTS = ("Going", "Interested", "FYI")


class GCalError(Exception):
    pass


def calendar_id() -> str:
    cid = os.environ.get("GCAL_CALENDAR_ID", ALLOWED_CALENDAR_ID).strip()
    if cid != ALLOWED_CALENDAR_ID:
        raise GCalError(f"refusing to write to calendar {cid!r}: only the dedicated FYIs calendar is allowed")
    return cid


def _session():
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        raise GCalError("GOOGLE_SERVICE_ACCOUNT_JSON not set")
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account
    creds = service_account.Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
    creds.refresh(Request())
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"})
    s.sa_email = creds.service_account_email
    return s


def gcal_id(our_id: str) -> str:
    return "radar" + hashlib.sha1(our_id.encode()).hexdigest()  # [0-9a-f] is a subset of base32hex


# ----------------------------------------------------------------------------- what to sync
def curated_items() -> list[dict]:
    """The hand-curated v1 records (events.json): Going / Interested / FYI, tombstones included."""
    out = []
    today = dt.datetime.now(TZ).date().isoformat()
    for e in store._load(config.LEGACY_EVENTS_FILE, []):
        if (e.get("end") or e["start"])[:10] < today:
            continue
        out.append({"id": e["id"], "title": e["title"], "interest": e.get("interest", "FYI"), "start": e["start"], "end": e.get("end"),
                    "all_day": e.get("all_day", False), "location": e.get("location", ""), "url": e.get("source"),
                    "why": e.get("notes") or "", "cancelled": e.get("status") == "CANCELLED", "kind": "curated"})
    return out


def radar_items() -> list[dict]:
    today = dt.datetime.now(TZ).date().isoformat()
    out = []
    for e in store.load_events().values():
        if e.get("date", "") < today:
            continue
        cancelled = e.get("status") in ("cancelled", "postponed")
        if not cancelled and e.get("status") != "scheduled":
            continue
        if e.get("tier") == "exceptional" or (e.get("tier") == "strong" and (e.get("final_score") or 0) >= MIN_STRONG_SCORE):
            enr = e.get("enrichment") or {}
            why = (enr.get("deep") or {}).get("why") or (enr.get("fast") or {}).get("why") or (e.get("research") or {}).get("reason") \
                or "; ".join(e.get("score_reasons", [])[:3])
            out.append({"id": e["id"], "title": e["title"], "interest": "FYI", "start": e["start"], "end": e.get("end"),
                        "all_day": e["start"][11:16] in ("", "00:00"), "location": ", ".join(x for x in (e.get("venue") or e.get("venue_raw"), e.get("city")) if x),
                        "url": e.get("url"), "why": why, "cancelled": cancelled, "kind": "radar", "tier": e.get("tier"),
                        "score": e.get("final_score"), "sources": [s.get("url") for s in e.get("sources", []) if s.get("url")][:5],
                        "run_end": e.get("run_end")})
    return out


def body_for(item: dict, keep_interest: str | None = None) -> dict:
    interest = keep_interest if keep_interest in ("Going", "Interested") and item["interest"] == "FYI" else item["interest"]
    start = parse_dt(item["start"])
    if item["all_day"]:
        end = parse_dt(item["end"]) if item.get("end") else start + dt.timedelta(days=1)
        if end.date() <= start.date():
            end = start + dt.timedelta(days=1)
        when = {"start": {"date": start.date().isoformat()}, "end": {"date": end.date().isoformat()}}
    else:
        end = parse_dt(item["end"]) if item.get("end") else start + dt.timedelta(hours=2)
        when = {"start": {"dateTime": start.isoformat(), "timeZone": config.LOCAL_TZ},
                "end": {"dateTime": end.isoformat(), "timeZone": config.LOCAL_TZ}}
    lines = [item.get("why") or ""]
    if item.get("run_end"):
        lines.append(f"Run closes {item['run_end']}.")
    if item.get("tier"):
        lines.append(f"Radar tier: {item['tier']} ({item.get('score')})")
    lines.append(f"Source: {item.get('url') or '-'}")
    lines += [f"Also: {u}" for u in (item.get("sources") or []) if u != item.get("url")]
    if item["kind"] == "radar":
        lines.append("Ticket availability unverified. End time estimated unless the source gives one.")
    return {
        **when,
        "id": gcal_id(item["id"]),
        "summary": f"[{interest}] {item['title']}",
        "location": item.get("location") or "",
        "description": "\n".join(l for l in lines if l),
        "source": {"title": "Bay Area Event Radar", "url": item.get("url") or "https://esdouglas.github.io/bay-area-event-radar/"},
        "transparency": "transparent",
        "reminders": {"useDefault": False, "overrides": []},
        "status": "cancelled" if item.get("cancelled") else "confirmed",
        "extendedProperties": {"private": {"radar_id": item["id"], "radar_kind": item["kind"], "interest": interest}},
    }


def _existing_interest(ev: dict) -> str | None:
    p = (ev.get("extendedProperties") or {}).get("private") or {}
    summ = ev.get("summary") or ""
    for i in ("Going", "Interested"):
        if summ.startswith(f"[{i}]") or p.get("interest") == i:
            return i
    return None


def upsert(s, item: dict, dry_run=False) -> str:
    cid = calendar_id()
    gid = gcal_id(item["id"])
    r = s.get(f"{API}/calendars/{requests.utils.quote(cid)}/events/{gid}", timeout=30)
    if r.status_code == 200:
        cur = r.json()
        body = body_for(item, _existing_interest(cur))
        if dry_run:
            return "would-update"
        rr = s.patch(f"{API}/calendars/{requests.utils.quote(cid)}/events/{gid}", data=json.dumps(body), timeout=30)
        if rr.status_code >= 300:
            raise GCalError(f"patch {gid}: HTTP {rr.status_code} {rr.text[:200]}")
        return "updated"
    if r.status_code not in (404, 410):
        raise GCalError(f"get {gid}: HTTP {r.status_code} {r.text[:200]}")
    if item.get("cancelled"):
        return "skipped-cancelled"  # never create an entry just to cancel it
    body = body_for(item)
    if dry_run:
        return "would-create"
    rr = s.post(f"{API}/calendars/{requests.utils.quote(cid)}/events", data=json.dumps(body), timeout=30)
    if rr.status_code == 409:  # created concurrently or previously deleted-but-remembered: patch instead
        rr = s.patch(f"{API}/calendars/{requests.utils.quote(cid)}/events/{gid}", data=json.dumps(body), timeout=30)
    if rr.status_code >= 300:
        raise GCalError(f"insert {gid}: HTTP {rr.status_code} {rr.text[:200]}")
    return "created"


def _fingerprint(item):
    return hashlib.sha1(json.dumps(body_for(item), sort_keys=True).encode()).hexdigest()[:16]


def sync(limit=None, dry_run=False, only=None):
    state = store._load(STATE_FILE, {})
    items = curated_items() + radar_items()
    if only:
        items = [i for i in items if i["id"] in only]
    todo = [i for i in items if state.get(i["id"], {}).get("fp") != _fingerprint(i)]
    if limit:
        todo = todo[:limit]
    print(f"[gcal] {len(items)} items eligible, {len(todo)} changed since last sync; calendar {calendar_id()[:12]}...")
    s = _session()
    counts = {}
    for i in todo:
        try:
            res = upsert(s, i, dry_run)
        except GCalError as e:
            res = "error"
            print(f"  ! {i['id']}: {e}")
        counts[res] = counts.get(res, 0) + 1
        if res in ("created", "updated"):
            state[i["id"]] = {"fp": _fingerprint(i), "gcal_id": gcal_id(i["id"]), "synced_at": config.now_iso()}
    if not dry_run:
        store._save(STATE_FILE, state)
    print(f"[gcal] {counts}")
    return counts


def test(item_id="cal-kentridge-2026-12"):
    """Prove create/read/update/dedup on ONE event before any backfill."""
    s = _session()
    cid = calendar_id()
    print(f"[gcal test] service account {s.sa_email}; calendar {cid}")
    item = next(i for i in curated_items() + radar_items() if i["id"] == item_id)
    gid = gcal_id(item_id)
    print("  1 create/upsert:", upsert(s, item))
    r = s.get(f"{API}/calendars/{requests.utils.quote(cid)}/events/{gid}", timeout=30).json()
    print("  2 read back:", r.get("summary"), "| start", r.get("start"), "| transparency", r.get("transparency"),
          "| reminders", r.get("reminders"), "| attendees", r.get("attendees"))
    item2 = dict(item, why=(item.get("why") or "") + " [sync test: description updated]")
    print("  3 update:", upsert(s, item2))
    r2 = s.get(f"{API}/calendars/{requests.utils.quote(cid)}/events/{gid}", timeout=30).json()
    print("    updated description ends with:", (r2.get("description") or "")[-60:].replace("\n", " / "))
    print("  4 re-run (dedup):", upsert(s, item))
    lst = s.get(f"{API}/calendars/{requests.utils.quote(cid)}/events", params={"privateExtendedProperty": f"radar_id={item_id}", "showDeleted": "false"}, timeout=30).json()
    n = len(lst.get("items", []))
    print(f"  5 copies of this event in the calendar: {n} ({'OK' if n == 1 else 'DUPLICATES'})")
    state = store._load(STATE_FILE, {})
    state[item_id] = {"fp": _fingerprint(item), "gcal_id": gid, "synced_at": config.now_iso()}
    store._save(STATE_FILE, state)
    return n == 1
