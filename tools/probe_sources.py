"""Feasibility probe: can each candidate source be fetched from a plain HTTP client,
and what structured data does it expose? Output is a JSON report, one row per URL."""
import concurrent.futures as cf
import json
import re
import sys
import time

import requests

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36 BayAreaEventRadar/0.1 (+https://github.com/esdouglas/bay-area-event-radar)"

def probe(url):
    row = {"url": url}
    t0 = time.time()
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/json,text/calendar,*/*;q=0.8"}, timeout=25, allow_redirects=True)
        row["status"] = r.status_code
        row["final_url"] = r.url
        row["bytes"] = len(r.content)
        row["server"] = r.headers.get("server", "")
        row["ctype"] = r.headers.get("content-type", "")[:40]
        text = r.text
        low = text.lower()
        row["challenge"] = any(k in low for k in ["just a moment", "cf-chl", "attention required", "access denied", "verify you are human", "captcha", "cloudflare"]) and r.status_code in (403, 503, 429)
        # JSON-LD
        blocks = re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', text, re.S | re.I)
        ev = 0
        types = set()
        for b in blocks:
            try:
                d = json.loads(b.strip())
            except Exception:
                continue
            stack = [d]
            while stack:
                x = stack.pop()
                if isinstance(x, list):
                    stack.extend(x)
                elif isinstance(x, dict):
                    t = str(x.get("@type", ""))
                    if t:
                        types.add(t[:30])
                    if "Event" in t:
                        ev += 1
                    for k in ("@graph", "itemListElement", "item", "subEvent"):
                        if k in x:
                            stack.append(x[k])
        row["jsonld_blocks"] = len(blocks)
        row["jsonld_events"] = ev
        row["jsonld_types"] = sorted(types)[:8]
        row["ics_links"] = len(set(re.findall(r'href="([^"]*\.ics[^"]*)"', text, re.I)))
        row["rss_links"] = len(re.findall(r'type="application/(?:rss|atom)\+xml"', text, re.I))
        row["tribe_events"] = ("tribe-events" in low) or ("/wp-json/tribe" in low)
        row["wordpress"] = "wp-content" in low
        row["squarespace"] = "squarespace" in low
        row["wix"] = "wix.com" in low or "wixstatic" in low
        row["weebly"] = "weebly" in low
        row["eventbrite_embed"] = "eventbrite" in low
        row["tickettailor"] = "tickettailor" in low or "buytickets.at" in low
        row["humanitix"] = "humanitix" in low
        row["tixr"] = "tixr" in low
        row["dice"] = "dice.fm" in low
        row["etix"] = "etix.com" in low
        row["seetickets"] = "seetickets" in low
        row["ticketweb"] = "ticketweb" in low
        row["axs"] = "axs.com" in low
        row["prekindle"] = "prekindle" in low
        row["instagram_only"] = ("instagram.com" in low) and ev == 0 and row["bytes"] < 20000
        row["title"] = (re.search(r'<title[^>]*>(.*?)</title>', text, re.S | re.I) or [None, ""])[1].strip()[:80]
    except Exception as e:
        row["status"] = "ERR"
        row["error"] = str(e)[:160]
    row["secs"] = round(time.time() - t0, 1)
    return row

if __name__ == "__main__":
    urls = [u.strip() for u in open(sys.argv[1]) if u.strip() and not u.startswith("#")]
    out = []
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for row in ex.map(probe, urls):
            out.append(row)
            print(json.dumps({k: row.get(k) for k in ("url", "status", "bytes", "jsonld_events", "ics_links", "tribe_events", "challenge", "error", "title")}), flush=True)
    json.dump(out, open(sys.argv[2], "w"), indent=1)
