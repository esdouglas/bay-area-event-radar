"""HTTP fetching with per-host pacing, retries, challenge detection and a small on-disk cache.

Every fetch is recorded on the collector's stats so a run can report exactly what was requested and
what came back; a Cloudflare challenge page is a *failure*, never silently treated as "no events".
"""
import hashlib
import json
import random
import threading
import time
from urllib.parse import urlparse

import requests

from . import config

_session = requests.Session()
_session.headers.update({
    "User-Agent": config.USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml,application/json,text/calendar;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
})
_lock = threading.Lock()
_last_hit: dict[str, float] = {}
HOST_PACING = {  # seconds between requests to the same host
    "www.songkick.com": 4.5,
    "www.eventbriteapi.com": 0.3,
    "events.humanitix.com": 1.0,
    "buytickets.at": 1.0,
    "default": 0.8,
}
CHALLENGE_MARKERS = ("just a moment", "cf-chl", "attention required", "verify you are human", "cf_chl_opt",
                     "challenge-platform", "access denied")


class FetchError(Exception):
    def __init__(self, msg, status=None, kind="error"):
        super().__init__(msg)
        self.status = status
        self.kind = kind


def _pace(host):
    wait = HOST_PACING.get(host, HOST_PACING["default"])
    with _lock:
        last = _last_hit.get(host, 0)
        delay = max(0.0, last + wait - time.time())
        _last_hit[host] = time.time() + delay
    if delay:
        time.sleep(delay)


def get(url, *, params=None, headers=None, retries=2, timeout=None, stats=None, json_body=None, method="GET"):
    host = urlparse(url).netloc
    last_err = None
    for attempt in range(retries + 1):
        _pace(host)
        try:
            if method == "POST":
                r = _session.post(url, params=params, headers=headers, json=json_body,
                                  timeout=timeout or config.FETCH_TIMEOUT)
            else:
                r = _session.get(url, params=params, headers=headers, timeout=timeout or config.FETCH_TIMEOUT)
        except requests.RequestException as e:
            last_err = FetchError(f"{type(e).__name__}: {str(e)[:160]}", kind="network")
            time.sleep(1.5 * (attempt + 1))
            continue
        if stats is not None:
            stats["requests"] = stats.get("requests", 0) + 1
            stats["bytes"] = stats.get("bytes", 0) + len(r.content)
        text_head = r.text[:4000].lower() if r.content else ""
        if r.status_code in (403, 503, 429, 405, 406) and any(m in text_head for m in CHALLENGE_MARKERS):
            raise FetchError(f"bot challenge (HTTP {r.status_code})", status=r.status_code, kind="blocked")
        if r.status_code == 406 and not r.content:
            # Songkick-style: origin refuses non-browser clients unless the CDN already holds the page.
            raise FetchError("HTTP 406 (origin refuses automated clients; only CDN-cached pages are served)", status=406, kind="partial")
        if r.status_code in (429, 503):
            last_err = FetchError(f"HTTP {r.status_code}", status=r.status_code, kind="ratelimited")
            time.sleep(6 + 4 * attempt + random.random() * 2)
            continue
        if r.status_code >= 400:
            kind = "blocked" if r.status_code in (403, 405) else "http"
            raise FetchError(f"HTTP {r.status_code}", status=r.status_code, kind=kind)
        return r
    raise last_err or FetchError("fetch failed")


def text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()


def cache_path(key: str):
    config.ensure_dirs()
    return config.CACHE / (hashlib.sha1(key.encode()).hexdigest()[:16] + ".json")


def cache_get(key: str, max_age_hours: float | None = None):
    p = cache_path(key)
    if not p.exists():
        return None
    try:
        with open(p, encoding="utf-8") as f:
            obj = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if max_age_hours is not None and time.time() - obj.get("ts", 0) > max_age_hours * 3600:
        return None
    return obj


def cache_put(key: str, value: dict):
    value = dict(value, ts=time.time(), key=key)
    with open(cache_path(key), "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False)
