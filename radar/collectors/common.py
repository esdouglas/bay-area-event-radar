"""Shared parsing helpers for collectors."""
import html
import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..normalize import clean_text

LD_RE = re.compile(r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.S | re.I)


def jsonld_blocks(html_text: str) -> list:
    out = []
    for block in LD_RE.findall(html_text):
        block = block.strip()
        if not block:
            continue
        try:
            out.append(json.loads(block))
        except json.JSONDecodeError:
            # some sites emit several objects or trailing commas; try a lenient repair
            try:
                out.append(json.loads(re.sub(r",\s*([}\]])", r"\1", block)))
            except json.JSONDecodeError:
                continue
    return out


def walk_events(obj):
    """Yield every schema.org *Event dict inside a JSON-LD structure (graphs, item lists, sub events)."""
    stack = [obj]
    seen = set()
    while stack:
        x = stack.pop()
        if isinstance(x, list):
            stack.extend(x)
        elif isinstance(x, dict):
            if id(x) in seen:
                continue
            seen.add(id(x))
            t = x.get("@type", "")
            t = " ".join(t) if isinstance(t, list) else str(t)
            if "Event" in t and (x.get("startDate") or x.get("start_date")):
                yield x
            for k in ("@graph", "itemListElement", "item", "subEvent", "events", "mainEntity", "hasPart"):
                if k in x:
                    stack.append(x[k])


def _name(v):
    if isinstance(v, dict):
        return clean_text(v.get("name") or v.get("@id") or "")
    if isinstance(v, list):
        return ", ".join(_name(i) for i in v if _name(i))
    return clean_text(v)


def _first(v):
    return v[0] if isinstance(v, list) and v else v


def raw_from_schema(ev: dict, base_url: str | None = None) -> dict:
    """Map a schema.org Event into the collector raw-event shape."""
    loc = _first(ev.get("location")) or {}
    if isinstance(loc, str):
        loc = {"name": loc}
    addr = loc.get("address") if isinstance(loc, dict) else None
    city = state = street = ""
    if isinstance(addr, dict):
        city = addr.get("addressLocality") or ""
        state = addr.get("addressRegion") or ""
        street = addr.get("streetAddress") or ""
    elif isinstance(addr, str):
        street = addr
    geo = loc.get("geo") if isinstance(loc, dict) else None
    performers = []
    perf = ev.get("performer") or ev.get("performers") or []
    if isinstance(perf, (dict, str)):
        perf = [perf]
    for p in perf:
        n = _name(p)
        if n:
            performers.append(n)
    offers = _first(ev.get("offers")) or {}
    price = ""
    if isinstance(offers, dict):
        if offers.get("price") not in (None, ""):
            price = f"{offers.get('price')} {offers.get('priceCurrency') or ''}".strip()
        elif offers.get("lowPrice") not in (None, ""):
            price = f"{offers.get('lowPrice')}-{offers.get('highPrice', '')} {offers.get('priceCurrency') or ''}".strip("- ")
    status = str(ev.get("eventStatus") or "").split("/")[-1]
    status_map = {"EventCancelled": "cancelled", "EventPostponed": "postponed", "EventRescheduled": "scheduled",
                  "EventScheduled": "scheduled", "": "scheduled"}
    url = ev.get("url") or (offers.get("url") if isinstance(offers, dict) else None)
    if url and base_url:
        url = urljoin(base_url, url)
    image = ev.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        image = image.get("url")
    return {
        "title": clean_text(ev.get("name")),
        "start": ev.get("startDate"),
        "end": ev.get("endDate"),
        "venue": _name(loc) if isinstance(loc, dict) else "",
        "city": clean_text(city),
        "state": clean_text(state),
        "address": clean_text(street),
        "url": url,
        "ticket_url": offers.get("url") if isinstance(offers, dict) else None,
        "performers": performers,
        "description": clean_text(ev.get("description") or "")[:1500],
        "price": price,
        "tags": [clean_text(g) for g in (_as_list(ev.get("genre")) + _as_list(ev.get("keywords")))],
        "status": status_map.get(status, "scheduled"),
        "image": image if isinstance(image, str) else None,
        "lat": (geo or {}).get("latitude") if isinstance(geo, dict) else None,
        "lon": (geo or {}).get("longitude") if isinstance(geo, dict) else None,
        "source_event_id": ev.get("@id") or ev.get("identifier"),
    }


def _as_list(v):
    if not v:
        return []
    if isinstance(v, str):
        return [p.strip() for p in v.split(",") if p.strip()]
    if isinstance(v, list):
        return [str(i) for i in v]
    return [str(v)]


def links(html_text: str, base_url: str, pattern: str) -> list[str]:
    rx = re.compile(pattern)
    out = []
    seen = set()
    for m in re.finditer(r"""(?:href|data-href|data-url)=["']([^"']+)["']""", html_text):
        u = urljoin(base_url, html.unescape(m.group(1)).strip())
        u = u.split("#")[0]
        if rx.search(u) and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def visible_text(html_text: str, max_chars: int = 60000) -> str:
    """Readable text with line structure preserved, navigation chrome removed."""
    soup = BeautifulSoup(html_text, "html.parser")
    for t in soup(["script", "style", "noscript", "svg", "iframe", "nav", "footer", "header", "form", "button"]):
        t.decompose()
    text = soup.get_text("\n")
    lines = [clean_text(l) for l in text.split("\n")]
    lines = [l for l in lines if l]
    out = "\n".join(lines)
    return out[:max_chars]
