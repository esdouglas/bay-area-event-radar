"""Collector method `gpt`: GPT's adapters (gpt_parsers.extract) driven by this repo's fetch layer.

Follows links breadth-first like the original (index page -> detail pages) up to page_limit, and
records a per-page audit row (url, final url, sha256 of the body, events extracted, status), which
collect.py writes to data/coverage/<run>.json. Source keys: adapter, page_limit, follow,
link_pattern, user_agent ("plain" sends a bare bot UA, which some CDNs accept from datacenter IPs
where a browser-like UA is challenged; verified for Humanitix on GitHub runners, 2026-10-28)."""
import hashlib
import re

from .. import config, fetch
from .gpt_parsers import LINK_PATTERN, extract, links

PLAIN_UA = "BayAreaEventRadar/2.0 (+https://github.com/esdouglas/bay-area-event-radar)"
JAMBASE = re.compile(r"^(.+?) - ([^-]+?) - (.+?) - [A-Z][a-z]{2} \d{1,2}, 20\d\d$")
DYNAMIC = re.compile(r"loading upcoming shows|enable javascript|just a moment|captcha", re.I)


def _plain_get(url, stats):
    """Exactly the request main's collector made (urllib, bot UA, no other headers)."""
    import urllib.error
    import urllib.request
    fetch._pace(url.split("/")[2])
    req = urllib.request.Request(url, headers={"User-Agent": PLAIN_UA})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            b = r.read(3_000_001)
            stats["requests"] = stats.get("requests", 0) + 1
            return b.decode("utf-8", errors="replace"), r.geturl()
    except urllib.error.HTTPError as e:
        raise fetch.FetchError(f"HTTP {e.code}", status=e.code, kind="blocked" if e.code in (403, 405) else "http")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise fetch.FetchError(f"{type(e).__name__}: {str(e)[:120]}", kind="network")


def collect_gpt(source: dict, stats: dict) -> list[dict]:
    headers = {"User-Agent": PLAIN_UA} if source.get("user_agent") == "plain" else None
    queue, seen, out, pages = [source["url"]], set(), [], []
    limit = int(source.get("page_limit", 8))
    adapter = source.get("adapter", "auto")
    while queue and len(seen) < limit:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        rec = {"url": url, "fetched_at": config.now_iso()}
        try:
            if headers:
                body, final = _plain_get(url, stats)
            else:
                r = fetch.get(url, stats=stats)
                body, final = r.text, r.url
            sha = hashlib.sha256(body.encode("utf-8", "ignore")).hexdigest()
            a = "auto" if adapter == "kalx" and "/event/" not in final else adapter
            parsed, page = extract(body, final, a)
            for e in parsed:
                city = None
                m = JAMBASE.match(e["title"])
                if m:  # "Artist - City - Venue - Mon D, YYYY"
                    e["title"], city, e["venue"] = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
                out.append({
                    "city": city,
                    "title": e["title"], "start": e.get("start") or e["date"], "venue": e.get("venue") or None,
                    "url": e.get("url") or final, "description": (e.get("description") or "")[:1500],
                    "evidence_hash": sha, "date_basis": e.get("date_basis"),
                    "heuristic": bool(e.get("date_basis") and "infer" in e["date_basis"]),
                    "status": "cancelled" if "Cancel" in str(e.get("event_status", "")) else "scheduled",
                })
            follow = links(page, final, source.get("link_pattern", LINK_PATTERN)) if source.get("follow", True) else []
            if url == source["url"] or adapter == "kalx":
                queue.extend(x for x in follow if x not in seen and x not in queue)
            status = "extracted" if parsed else ("dynamic-or-blocked" if DYNAMIC.search(body) else "fetched-no-events")
            rec.update(final_url=final, sha256=sha, bytes=len(body), events=len(parsed), status=status, links=len(follow))
        except fetch.FetchError as ex:
            rec.update(status="failed", error=str(ex))
            if url == source["url"]:
                pages.append(rec)
                stats["pages_audit"] = pages
                raise
        pages.append(rec)
    stats["pages_audit"] = pages
    stats["pending_links"] = len(set(queue) - seen)
    if stats["pending_links"]:
        stats.setdefault("warnings", []).append(f"truncated: {stats['pending_links']} linked pages not fetched this run (page_limit {limit})")
    return out
