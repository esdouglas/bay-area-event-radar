"""Stage E (browsing) + F (monitoring): static site = searchable inventory, coverage dashboard, ICS feed.

radar.ics keeps the v1 UIDs for the 36 hand-curated records (so an existing calendar subscription keeps
working) and adds every event rated strong or better."""
import datetime as dt
import html
import json
import re

from . import config, llm, store
from .collect import load_sources
from .normalize import TZ, parse_dt


ICS_MIN_STRONG_SCORE = 65  # keep the calendar feed readable; the site holds everything


def _fold(line):
    out, part = [], ""
    for ch in line:
        if len((part + ch).encode()) > 75:
            out.append(part)
            part = " " + ch
        else:
            part += ch
    return "\r\n".join(out + [part])


def _esc(v):
    return str(v).replace("\\", "\\\\").replace("\r", "").replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")


def _stamp(d):
    return d.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_ics(events: dict, legacy: list) -> str:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Bay Area Event Radar//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             "X-WR-CALNAME:Bay Area Event Radar", "X-WR-TIMEZONE:America/Los_Angeles"]
    seen_keys = set()
    # v1 curated records first, unchanged UIDs
    for e in sorted(legacy, key=lambda x: x["id"]):
        start = parse_dt(e["start"])
        if not start:
            continue
        desc = f"Source: {e['source']}\n[curated v1 record]" + (f"\n{e.get('notes')}" if e.get("notes") else "")
        lines += ["BEGIN:VEVENT", f"UID:{e['id']}@bay-area-event-radar.esdouglas.github.io", f"DTSTAMP:{_stamp(parse_dt(e['modified_at']))}",
                  f"SEQUENCE:{e.get('sequence', 0)}"]
        if e.get("all_day"):
            lines.append(f"DTSTART;VALUE=DATE:{start:%Y%m%d}")
            if e.get("end"):
                lines.append(f"DTEND;VALUE=DATE:{parse_dt(e['end']):%Y%m%d}")
        else:
            lines.append(f"DTSTART:{_stamp(start)}")
            if e.get("end"):
                lines.append(f"DTEND:{_stamp(parse_dt(e['end']))}")
        lines += [f"SUMMARY:{_esc('[' + e['interest'] + '] ' + e['title'])}", f"STATUS:{e['status']}", "TRANSP:TRANSPARENT",
                  f"LOCATION:{_esc(e['location'])}", f"URL:{e['source']}", f"DESCRIPTION:{_esc(desc)}", "END:VEVENT"]
        seen_keys.add((start.date().isoformat(), re.sub(r"[^a-z0-9]", "", e["title"].lower())[:16]))
    for e in sorted(events.values(), key=lambda x: x["start"]):
        if e.get("status") != "scheduled" or e.get("tier") not in ("exceptional", "strong"):
            continue
        if e["tier"] == "strong" and (e.get("final_score") or 0) < ICS_MIN_STRONG_SCORE:
            continue
        start = parse_dt(e["start"])
        k = (e["date"], re.sub(r"[^a-z0-9]", "", e["title"].lower())[:16])
        if k in seen_keys:
            continue
        seen_keys.add(k)
        enr = e.get("enrichment") or {}
        why = (enr.get("deep") or {}).get("why") or (enr.get("fast") or {}).get("why") or "; ".join(e.get("score_reasons", [])[:3])
        desc = f"{why}\nScore {e.get('final_score', e.get('score'))} · tier {e['tier']}\nSource: {e.get('url')}\nTicket availability unverified."
        lines += ["BEGIN:VEVENT", f"UID:{e['id']}@bay-area-event-radar.esdouglas.github.io", f"DTSTAMP:{_stamp(parse_dt(e['last_seen']))}",
                  f"SEQUENCE:0", f"DTSTART:{_stamp(start)}"]
        if e.get("end"):
            lines.append(f"DTEND:{_stamp(parse_dt(e['end']))}")
        lines += [f"SUMMARY:{_esc('[' + e['tier'][:3].upper() + '] ' + e['title'])}", "STATUS:CONFIRMED", "TRANSP:TRANSPARENT",
                  f"LOCATION:{_esc((e.get('venue') or e.get('venue_raw') or '') + (', ' + e['city'] if e.get('city') else ''))}",
                  f"URL:{e.get('url') or ''}", f"DESCRIPTION:{_esc(desc)}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(l) for l in lines) + "\r\n"


CSS = """body{max-width:1100px;margin:30px auto;padding:0 18px;font:15px/1.5 system-ui,-apple-system,sans-serif;color:#172d3d;background:#f7f5ee}
a{color:#075e69}h1{margin:.2em 0}h2{margin-top:1.6em}table{width:100%;border-collapse:collapse;font-size:14px}
td,th{text-align:left;vertical-align:top;padding:7px 6px;border-bottom:1px solid #d7ddd8}th{position:sticky;top:0;background:#f7f5ee}
.tier-exceptional{background:#fff2d6}.tier-strong{background:#f1f7ee}.tier-noise{color:#8a9a9d}
.badge{display:inline-block;padding:1px 7px;border-radius:9px;font-size:12px;background:#dfe7e3;margin-right:4px}
.ok{color:#0a7a3b}.bad{color:#b4231a}.warn{color:#a15c00}small{color:#52686c}
input,select{font:inherit;padding:6px 8px;margin:4px 6px 4px 0;border:1px solid #b8c3bd;border-radius:6px;background:#fff}
.why{color:#3b5560;font-size:13px}.nav a{margin-right:14px}code{overflow-wrap:anywhere}
"""


def build_index(events: dict, summary: dict) -> str:
    today = dt.datetime.now(TZ).date().isoformat()
    rows = []
    for e in events.values():
        if e.get("status") in ("past",) or (e.get("date") or "") < today:
            continue
        enr = e.get("enrichment") or {}
        why = (enr.get("deep") or {}).get("why") or (enr.get("fast") or {}).get("why") or "; ".join(e.get("score_reasons", [])[:3])
        rows.append({"id": e["id"], "date": e["date"], "time": (e.get("start") or "")[11:16], "title": e["title"], "venue": e.get("venue") or e.get("venue_raw") or "",
                     "city": e.get("city") or "", "tier": e.get("tier") or "inventory", "score": e.get("final_score", e.get("score")) or 0,
                     "cat": e.get("category") or "", "url": e.get("url") or "", "why": why[:400], "sources": sorted({s["source"] for s in e["sources"]}),
                     "status": e.get("status"), "first_seen": e["first_seen"][:10], "price": e.get("price") or "",
                     "performers": e.get("performers", [])[:6], "tags": e.get("tags", [])[:8]})
    rows.sort(key=lambda r: (r["date"], r["time"]))
    data = json.dumps(rows, ensure_ascii=False)
    counts = {}
    for r in rows:
        counts[r["tier"]] = counts.get(r["tier"], 0) + 1
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Bay Area Event Radar</title><style>{CSS}</style>
<h1>Bay Area Event Radar</h1>
<p class="nav"><a href="dashboard.html">Coverage dashboard</a><a href="radar.ics">Calendar feed (.ics)</a><a href="events.json">events.json</a><a href="https://github.com/esdouglas/bay-area-event-radar/issues?q=label%3Aradar-alert">Alerts</a><a href="https://github.com/esdouglas/bay-area-event-radar/issues?q=label%3Aradar-digest">Digests</a></p>
<p><strong>{len(rows)}</strong> upcoming events in the inventory · {counts.get('exceptional', 0)} exceptional · {counts.get('strong', 0)} strong · {counts.get('inventory', 0)} inventory · {counts.get('noise', 0)} noise (hidden by default). Last collection {html.escape(summary.get('ts', '?'))}.</p>
<p><input id="q" placeholder="search title, venue, performers, tags" size="40"> <select id="tier"><option value="">tier ≥ inventory</option><option value="exceptional">exceptional</option><option value="strong">strong+</option><option value="all">everything incl. noise</option></select>
<select id="cat"><option value="">all categories</option><option>music</option><option>theater</option><option>dance</option><option>arts</option><option>mixed</option><option>comedy</option><option>other</option></select>
<select id="days"><option value="">any date</option><option value="14">next 14 days</option><option value="30">next 30 days</option><option value="60">next 60 days</option></select>
<select id="sort"><option value="date">sort by date</option><option value="score">sort by score</option><option value="new">newest first</option></select> <span id="n"></span></p>
<table><thead><tr><th>When</th><th>Event</th><th>Where</th><th>Tier / score</th></tr></thead><tbody id="rows"></tbody></table>
<p><small>Scores are explainable rules plus optional model research; a listing does not confirm ticket availability. Built by <a href="https://github.com/esdouglas/bay-area-event-radar">bay-area-event-radar</a>.</small></p>
<script>
const DATA={data};const order={{exceptional:0,strong:1,inventory:2,noise:3}};
function esc(s){{return String(s).replace(/[&<>"]/g,c=>({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}}[c]))}}
function render(){{const q=document.getElementById('q').value.toLowerCase().trim();const tier=document.getElementById('tier').value;const cat=document.getElementById('cat').value;const days=document.getElementById('days').value;const sort=document.getElementById('sort').value;
const today=new Date().toISOString().slice(0,10);const lim=days?new Date(Date.now()+days*864e5).toISOString().slice(0,10):null;
let rows=DATA.filter(r=>{{if(tier==='all'){{}}else if(tier==='exceptional'){{if(r.tier!=='exceptional')return false}}else if(tier==='strong'){{if(order[r.tier]>1)return false}}else{{if(r.tier==='noise')return false}}
if(cat&&r.cat!==cat)return false;if(lim&&(r.date>lim))return false;if(r.date<today)return false;
if(q){{const hay=(r.title+' '+r.venue+' '+r.city+' '+r.performers.join(' ')+' '+r.tags.join(' ')+' '+r.why+' '+r.sources.join(' ')).toLowerCase();if(!hay.includes(q))return false}}return true}});
if(sort==='score')rows.sort((a,b)=>b.score-a.score||a.date.localeCompare(b.date));else if(sort==='new')rows.sort((a,b)=>b.first_seen.localeCompare(a.first_seen)||a.date.localeCompare(b.date));else rows.sort((a,b)=>a.date.localeCompare(b.date)||a.time.localeCompare(b.time));
document.getElementById('n').textContent=rows.length+' shown';
document.getElementById('rows').innerHTML=rows.slice(0,1500).map(r=>`<tr class="tier-${{r.tier}}"><td><b>${{r.date}}</b><br><small>${{r.time}}</small></td><td><a href="${{esc(r.url)}}">${{esc(r.title)}}</a>${{r.status!=='scheduled'?' <span class="badge">'+esc(r.status)+'</span>':''}}${{r.price?' <small>'+esc(r.price)+'</small>':''}}<div class="why">${{esc(r.why)}}</div><small>${{r.sources.map(s=>'<span class="badge">'+esc(s)+'</span>').join('')}} first seen ${{r.first_seen}}</small></td><td>${{esc(r.venue)}}<br><small>${{esc(r.city)}}</small></td><td><b>${{r.tier}}</b><br>${{r.score}}<br><small>${{esc(r.cat)}}</small></td></tr>`).join('')}}
for(const id of ['q','tier','cat','days','sort'])document.getElementById(id).addEventListener('input',render);render();
</script></html>"""


def build_dashboard(events: dict, health: dict, summary: dict, sources: list, runs: list, benchmark_summary: dict | None) -> str:
    today = dt.datetime.now(TZ).date().isoformat()
    upcoming = [e for e in events.values() if e.get("status") == "scheduled" and e["date"] >= today]
    by_source = {}
    for e in upcoming:
        for s in e["sources"]:
            by_source[s["source"]] = by_source.get(s["source"], 0) + 1
    rows = []
    for s in sources:
        h = health.get(s["id"], {})
        st = h.get("last_status") or ("disabled" if not s.get("enabled", True) else "never run")
        if st == "blocked" and s.get("expected_blocked"):
            st = "blocked (known gap)"
        cls = "ok" if st == "ok" else ("warn" if st in ("partial", "never run", "disabled", "blocked (known gap)") else "bad")
        rows.append(f"<tr><td><b>{html.escape(s['name'])}</b><br><small>{html.escape(s['id'])} · {html.escape(s.get('kind', ''))} · {html.escape(s['method'])}</small></td>"
                    f"<td class='{cls}'>{html.escape(st)}{'<br><small>' + html.escape(str(h.get('last_error') or '')[:140]) + '</small>' if h.get('last_error') else ''}"
                    f"{'<br><small class=warn>' + html.escape('; '.join(h.get('last_warnings', []))[:200]) + '</small>' if h.get('last_warnings') else ''}</td>"
                    f"<td>{html.escape((h.get('last_ok') or '')[:16])}</td><td>{h.get('last_count', '')}</td><td>{by_source.get(s['id'], 0)}</td><td>{h.get('consecutive_failures', 0)}</td>"
                    f"<td><small>{html.escape(str(s.get('expected_coverage') or ''))}</small>{'<br><small>' + html.escape(str(s.get('notes') or ''))[:400] + '</small>' if s.get('notes') else ''}</td></tr>")
    # run history (last 30 runs)
    by_run = {}
    for r in runs[-2000:]:
        by_run.setdefault(r.get("started", "")[:16], []).append(r)
    hist = sorted(by_run.items())[-40:]
    hist_rows = "".join(f"<tr><td>{html.escape(ts)}</td><td>{sum(1 for x in rs if x.get('status') == 'ok')}/{len(rs)}</td><td>{sum(x.get('new', 0) for x in rs)}</td><td>{sum(x.get('raw_events', 0) for x in rs)}</td><td>{round(sum(x.get('seconds', 0) for x in rs))}s</td><td><small>{html.escape(', '.join(x['source'] for x in rs if x.get('status') != 'ok')[:200])}</small></td></tr>" for ts, rs in hist)
    cost = llm.cost_summary(30)
    venues = {}
    for e in upcoming:
        v = e.get("venue") or e.get("venue_raw") or "?"
        venues[v] = venues.get(v, 0) + 1
    top_venues = sorted(venues.items(), key=lambda x: -x[1])[:60]
    tiers = {}
    for e in upcoming:
        tiers[e.get("tier") or "unscored"] = tiers.get(e.get("tier") or "unscored", 0) + 1
    bm = ""
    if benchmark_summary:
        bm = f"<h2>Historical benchmark</h2><p>{html.escape(benchmark_summary.get('headline', ''))}</p><pre>{html.escape(benchmark_summary.get('table', ''))}</pre>"
    multi = sum(1 for e in upcoming if len({s['source'] for s in e['sources']}) > 1)
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Radar coverage dashboard</title><style>{CSS}</style>
<h1>Coverage dashboard</h1><p class="nav"><a href="index.html">Inventory</a><a href="https://github.com/esdouglas/bay-area-event-radar/actions">Actions</a><a href="https://github.com/esdouglas/bay-area-event-radar/issues?q=label%3Aradar-ops">Ops issues</a></p>
<p>Last collection <b>{html.escape(summary.get('ts', '?'))}</b>: {summary.get('sources_ok', '?')} of {summary.get('sources_due', '?')} sources ok, {summary.get('new_events', '?')} new events, {summary.get('merged_sources', '?')} cross-source merges, {summary.get('seconds', '?')}s. Failed: {html.escape(', '.join(summary.get('sources_failed', [])) or 'none')}.</p>
<p>Upcoming inventory: <b>{len(upcoming)}</b> events · {multi} confirmed by 2+ sources · tiers {html.escape(json.dumps(tiers))} · model spend last 30 days <b>${cost['usd']}</b> ({cost['calls']} calls).</p>
<h2>Sources ({len(sources)}; {sum(1 for s in sources if s.get('enabled', True))} enabled)</h2>
<table><thead><tr><th>Source</th><th>Last status</th><th>Last ok</th><th>Last kept</th><th>Upcoming events citing it</th><th>Consecutive failures</th><th>Expected coverage / notes</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<h2>Venues represented ({len(venues)})</h2><p>{' · '.join(f'{html.escape(v)} <b>{n}</b>' for v, n in top_venues)}</p>
{bm}
<h2>Recent runs</h2><table><thead><tr><th>Run (UTC)</th><th>Sources ok</th><th>New</th><th>Raw</th><th>Time</th><th>Failures</th></tr></thead><tbody>{hist_rows}</tbody></table>
<p><small>Every collection attempt is logged in <code>data/runs/*.jsonl</code>; source health in <code>data/source_health.json</code>.</small></p></html>"""


def run():
    config.SITE.mkdir(exist_ok=True)
    events = store.load_events()
    health = store.load_health()
    summary = store._load(config.RUN_SUMMARY_FILE, {})
    legacy = store._load(config.LEGACY_EVENTS_FILE, [])
    sources = load_sources()
    runs = store.read_run_logs(2)
    bm = store._load(config.DATA / "benchmark_summary.json", None)
    (config.SITE / "index.html").write_text(build_index(events, summary), encoding="utf-8")
    (config.SITE / "dashboard.html").write_text(build_dashboard(events, health, summary, sources, runs, bm), encoding="utf-8")
    (config.SITE / "radar.ics").write_bytes(build_ics(events, legacy).encode())
    (config.SITE / "events.json").write_text(json.dumps([e for e in events.values() if e.get("status") == "scheduled"], ensure_ascii=False), encoding="utf-8")
    (config.SITE / "health.json").write_text(json.dumps(health, indent=1), encoding="utf-8")
    n = sum(1 for e in events.values() if e.get("status") == "scheduled")
    print(f"[site] built _site/ with {n} upcoming events, {len(sources)} sources")
