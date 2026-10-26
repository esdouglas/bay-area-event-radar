"""Broad discovery inventory. Standard library only; never writes curated events.json."""
import argparse, concurrent.futures, datetime as dt, gzip, hashlib, html, json, os
import pathlib, re, urllib.request, urllib.parse, uuid, unicodedata
from html.parser import HTMLParser
ROOT=pathlib.Path(__file__).resolve().parent
UTC=dt.timezone.utc

def now(): return dt.datetime.now(UTC).isoformat()
def digest(s): return hashlib.sha256(s.encode()).hexdigest()
def norm(s): return re.sub(r'[^a-z0-9]+',' ',unicodedata.normalize('NFKD',html.unescape(s)).encode('ascii','ignore').decode().lower()).strip()
def read(p,default): return json.loads(p.read_text()) if p.exists() else default
def save(p,value):
 p.parent.mkdir(parents=True,exist_ok=True); temp=p.with_suffix(p.suffix+'.tmp')
 temp.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n');temp.replace(p)
def append(p,value):
 p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('a') as f:f.write(json.dumps(value,ensure_ascii=False)+'\n')

class Page(HTMLParser):
 def __init__(self):
  super().__init__(); self.parts=[];self.links=[];self.schemas=[];self.script=None;self.buf=[];self.skip=0
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if tag=='script':self.script=a.get('type','');self.buf=[];self.skip+=1
  elif tag in ('style','nav','footer'):self.skip+=1
  if tag=='a' and a.get('href'): self.links.append(a['href'])
  if tag in ('br','p','div','li','h1','h2','h3','h4','h5','article','time','tr'):self.parts.append('\n')
 def handle_endtag(self,tag):
  if tag=='script':
   if self.script=='application/ld+json':
    try:self.schemas.append(json.loads(''.join(self.buf)))
    except ValueError:pass
   self.script=None;self.skip=max(0,self.skip-1)
  elif tag in ('style','nav','footer'):self.skip=max(0,self.skip-1)
  if tag in ('p','div','li','h1','h2','h3','h4','h5','article','time','tr'):self.parts.append('\n')
 def handle_data(self,data):
  if self.script is not None:self.buf.append(data)
  elif not self.skip:self.parts.append(data)
 @property
 def lines(self):return [re.sub(r'\s+',' ',html.unescape(x)).strip('\u200b \t') for x in ''.join(self.parts).splitlines() if x.strip('\u200b \t')]

def walk(x):
 if isinstance(x,list):
  for v in x:yield from walk(v)
 elif isinstance(x,dict):
  t=x.get('@type',[]); t=[t] if isinstance(t,str) else t
  if any(v.endswith('Event') for v in t):yield x
  for k,v in x.items():
   if k!='@type':yield from walk(v)

def event(title,date,venue,url,**kw):
 dt.date.fromisoformat(date[:10])
 return dict(title=html.unescape(title).strip(),date=date[:10],venue=venue.strip(),url=url,**kw)

def extract(body,url,adapter='auto',year=None):
 p=Page();p.feed(body);out=[];year=year or dt.datetime.now().year
 for x in walk(p.schemas):
  try:
   loc=x.get('location',{}); loc=loc.get('name','') if isinstance(loc,dict) else str(loc)
   out.append(event(x['name'],x['startDate'],loc,urllib.parse.urljoin(url,x.get('url') or url),start=x['startDate'],description=re.sub('<[^>]+>',' ',x.get('description',''))[:5000],event_status=x.get('eventStatus','unverified')))
  except (ValueError,KeyError,TypeError):continue
 lines=p.lines
 if adapter=='tickettailor':
  for i,line in enumerate(lines):
   m=re.match(r'^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) ([A-Z][a-z]{2}) (\d{1,2}), (20\d\d) ',line)
   if m and i>0:
    date=dt.datetime.strptime(f'{m[1]} {m[2]} {m[3]}','%b %d %Y').date().isoformat()
    out.append(event(lines[i-1],date,lines[i+1] if i+1<len(lines) else '',url,description=' | '.join(lines[i-1:i+2])))
 if adapter=='cafedunord':
  for i,line in enumerate(lines):
   m=re.fullmatch(r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) ([A-Z][a-z]{2}) (\d{1,2})',line)
   if not m:continue
   date=dt.date(year,dt.datetime.strptime(m[1],'%b').month,int(m[2])).isoformat()
   # Source headings omit year. Rollover only when month is earlier than current month.
   if int(date[5:7]) < dt.date.today().month:date=str(year+1)+date[4:]
   block=lines[i+1:i+6];title=None
   for j,t in enumerate(block):
    if t.endswith(' presents') and j+1<len(block):title=block[j+1];break
   if title:out.append(event(title,date,'Cafe du Nord / Swedish American Hall, San Francisco',url,description=' | '.join(block),date_basis='source month/day; year inferred; verify before alert'))
 if adapter=='oldtime':
  active=False;blocks=[];block=None
  for line in lines:
   if line=='UPCOMING':active=True;continue
   if not active:continue
   if line.startswith('ONGOING SESSIONS'):break
   m=re.match(r'^(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\.?\s+)?(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+(\d{1,2})\s+(20\d\d)(?:\s|$)',line,re.I)
   if m:
    if block:blocks.append(block)
    try:date=dt.date(int(m[3]),dt.datetime.strptime(m[1][:3].title(),'%b').month,int(m[2])).isoformat()
    except ValueError:block=None;continue
    block=[date,[]];continue
   if block:block[1].append(line)
  if block:blocks.append(block)
  for date,content in blocks:
   meaningful=[t for t in content if not t.startswith(('http','====','----'))]
   if meaningful:
    title=meaningful[0];venue=next((t for t in meaningful[1:] if re.search(r'Berkeley|Oakland|Monterey|Santa Cruz|Freight|Back Room|Ashkenaz|SF|Chapel|Albany',t)), 'See source; venue unverified')
    out.append(event(title,date,venue,url,description=' | '.join(content)[:5000],date_basis='explicit dated block; venue and lineup need primary verification'))
 if adapter=='kalx':
  date=None; region=''
  for line in lines:
   m=re.fullmatch(r'(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday) ([A-Za-z]+ \d{1,2}, \d{4})',line)
   if m: date=dt.datetime.strptime(m[1],'%B %d, %Y').date().isoformat();continue
   if line in ('East Bay','San Francisco','North Bay','South Bay'):region=line;continue
   if date and ': ' in line:
    venue,title=line.split(': ',1)
    if len(venue)<100 and len(title)>1:out.append(event(title,date,venue,url,region=region,description=line))
 if adapter=='bluegrass':
  active=False;artist=''
  for line in lines:
   if line.startswith('CONCERTS and'):active=True;continue
   if not active:continue
   if re.search(r'2027 FESTIVALS',line):break
   y=re.search(r'~ (20\d\d) ~',line)
   if y:year=int(y[1]);continue
   m=re.match(r'^-?\s*(Jan\.?|Feb\.?|Mar(?:ch)?\.?|Apr(?:il)?\.?|May|Jun(?:e)?\.?|Jul(?:y)?\.?|Aug\.?|Sep(?:t)?\.?|Oct\.?|Nov\.?|Dec\.?)\s+(\d{1,2})(?:\s*\([^)]*\))?:\s*(.+)',line)
   if m:
    month=dt.datetime.strptime(m[1][:3],'%b').month;date=f'{year}-{month:02}-{int(m[2]):02}'
    rest=m[3];multi=line.startswith('-')
    if multi and artist:title,venue=artist,rest
    elif ' - ' in rest:title,venue=rest.split(' - ',1)
    else:title,venue=rest,''
    out.append(event(title,date,venue,url,description=line,region='Northern California'))
   elif line.endswith(' -'):artist=line[:-2].strip()
 if adapter=='hicks':
  date=None
  for line in lines:
   m=re.fullmatch(r'(?:MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY|SUNDAY) ([A-Z]+) (\d{1,2})',line)
   if m:
    try:date=dt.datetime.strptime(f'{m[1]} {m[2]} {year}','%B %d %Y').date().isoformat()
    except ValueError:date=None
   elif date and ' @ ' in line:
    title,venue=line.split(' @ ',1);out.append(event(title,date,venue,url,description=line))
 return out,p

# Only public calendar/event URL shapes are followed, not arbitrary web links.
LINK_PATTERN=r'(/event[s]?/|/e/|/shows?/|/concerts?/|/tickets/|buytickets.at/|tickettailor.com/events/|events.humanitix.com/|eventim.us/event/|ticketweb.com/event/)'
def links(p,url,pattern=LINK_PATTERN):
 return sorted({urllib.parse.urljoin(url,x).split('#')[0] for x in p.links if re.search(pattern,urllib.parse.urljoin(url,x)) and urllib.parse.urljoin(url,x).startswith('https://')})

def fetch(url):
 req=urllib.request.Request(url,headers={'User-Agent':'BayAreaEventRadar/2.0 (+https://github.com/esdouglas/bay-area-event-radar)'})
 with urllib.request.urlopen(req,timeout=18) as r:
  b=r.read(3_000_001)
  if len(b)>3_000_000:raise ValueError('page exceeds 3MB limit')
  return b.decode('utf-8',errors='replace'),r.geturl()

def collect_source(source,capture):
 rows=[];records=[];queue=[source['url']];seen=set();limit=source.get('page_limit',12)
 while queue and len(seen)<limit:
  url=queue.pop(0)
  if url in seen:continue
  seen.add(url);record=dict(source_id=source['id'],url=url,fetched_at=now())
  try:
   body,final=fetch(url);sha=digest(body);capture.mkdir(parents=True,exist_ok=True)
   with gzip.open(capture/(sha+'.html.gz'),'wt') as f:f.write(body)
   adapter=source.get('adapter','auto')
   if adapter=='kalx' and '/event/' not in final:adapter='auto'
   parsed,p=extract(body,final,adapter)
   for e in parsed:e.update(source_id=source['id'],evidence_hash=sha,observed_at=record['fetched_at']);rows.append(e)
   follow=links(p,final,source.get('link_pattern',LINK_PATTERN)) if source.get('follow',True) else []
   # A source index's ticket links may lead to other domains; detail pages are leaves.
   if url==source['url'] or source.get('adapter')=='kalx':
    queue.extend(sorted((x for x in follow if x not in seen and x not in queue), key=lambda x: source.get('last_fetched',{}).get(x,'')))
   record.update(final_url=final,sha256=sha,bytes=len(body.encode()),min_event_date=min((e['date'] for e in parsed),default=None),max_event_date=max((e['date'] for e in parsed),default=None),events_extracted=len(parsed),status='extracted' if parsed else 'fetched-no-events',links_found=len(follow))
   if re.search(r'loading upcoming shows|enable javascript|just a moment|captcha',body,re.I) and not parsed:record['status']='dynamic-or-blocked'
  except Exception as ex:record.update(status='failed',error=f'{type(ex).__name__}: {ex}')
  records.append(record)
 return rows,dict(source_id=source['id'],pages=records,pending_links=len(set(queue)-seen),truncated=bool(set(queue)-seen),events_extracted=len(rows),coverage_state='partial-or-unverified',requested_horizon_days=source.get('target_horizon_days',180),verified_full_horizon=False)

def time_key(value):
 # Keep local performance times separate; missing times remain date-only leads.
 m=re.search(r'T(\d{2}:\d{2})',value or '')
 return m[1] if m else ''
def venue_key(value):
 return norm(value.split(',')[0])
def title_key(value):
 value=re.split(r'\s+@\s+|--|–|—',value)[0]
 value=re.sub(r'\b(?:DEC\.?|JAN\.?|FEB\.?|MAR\.?|APR\.?|OCT\.?|NOV\.?)\s+\d+.*$','',value,flags=re.I)
 return norm(value).removeprefix('the ')
def merge(inventory,rows,run_id):
 # Conservative identity. Aliases remain visible; do not merge different performances by fuzzy name.
 keys={(title_key(e['title']),e['date'],venue_key(e['venue']),time_key(e.get('start'))):k for k,e in sorted(inventory.items(),key=lambda kv:kv[1]['first_seen'],reverse=True)}
 for row in rows:
  key=(title_key(row['title']),row['date'],venue_key(row['venue']),time_key(row.get('start')));eid=keys.get(key) or digest('|'.join(key))[:24];keys[key]=eid
  if eid not in inventory:inventory[eid]=dict(id=eid,title=row['title'],date=row['date'],venue=row['venue'],first_seen=row['observed_at'],observations=[],research_status='pending')
  e=inventory[eid];e['last_seen']=max(e.get('last_seen',''),row['observed_at'])
  observation={k:row[k] for k in ('url','source_id','evidence_hash','observed_at')};observation['run_id']=run_id
  # Every collection is an observation even when content unchanged.
  
  previous=next((o for o in e['observations'] if o['url']==observation['url']),None)
  if previous is None or observation['observed_at']>previous['observed_at']:
   observation['collection_count']=(previous or {}).get('collection_count',1 if previous else 0)+1
   e['observations']=[o for o in e['observations'] if o['url']!=observation['url']]+[observation]
  e['description']=row.get('description','');e['start']=row.get('start') or e.get('start');e['source_status']=row.get('event_status','unverified');e['date_basis']=row.get('date_basis','source supplies explicit year')
 return inventory

def report_html(inventory,coverage,outbox):
 esc=html.escape
 rows=''.join('<tr><td>'+esc(e['date'])+'</td><td>'+esc(e['title'])+'<br>'+esc(e['venue'])+'</td><td>'+esc(e.get('research_status','pending'))+'</td><td>'+esc(e['first_seen'])+'</td><td>'+''.join('<a href="'+esc(u,quote=True)+'">source</a> ' for u in sorted({o['url'] for o in e['observations']}))+'</td></tr>' for e in sorted(inventory.values(),key=lambda x:(x['date'],x['title'])))
 return '<!doctype html><meta charset="utf-8"><title>Radar inventory and coverage</title><style>body{font:16px system-ui;margin:30px}td{padding:10px;border-bottom:1px solid #ccc}pre{white-space:pre-wrap}</style><h1>Broad discovery inventory</h1><p>Shadow system: NOT VALIDATED. Date-only leads are unverified; listing is not ticket availability. First seen is actual collection time, never announcement time. No inventory entry implies attendance.</p><p><a href="radar.ics">Existing curated calendar</a> · <a href="coverage.json">Source coverage</a> · <a href="outbox.json">Undelivered alert outbox</a> · <a href="inventory.json">Full inventory</a></p><h2>Actual latest coverage</h2><pre>'+esc(json.dumps(coverage,indent=2))+'</pre><h2>'+str(len(inventory))+' retained candidates</h2><table><tr><th>Date</th><th>Event / venue</th><th>Research</th><th>First seen</th><th>Evidence</th></tr>'+rows+'</table>'

def run(root=ROOT,enrich=False):
 started=now();run_id=str(uuid.uuid4());sources=read(root/'sources.json',[]);inventory=read(root/'data/inventory.json',{})
 results=[];rows=[]
 frontiers=read(root/'data/frontiers.json',{})
 for source in sources:source['last_fetched']=frontiers.get(source['id'],{})
 with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
  for rs,result in pool.map(lambda s:collect_source(s,root/'.capture'),sources):rows.extend(rs);results.append(result)
 for result in results:
  frontier=frontiers.setdefault(result['source_id'],{})
  for page in result['pages']:frontier[page['url']]=page['fetched_at']
 save(root/'data/frontiers.json',frontiers)
 for row in read(root/'data/manual-events.json',[]):
  if all(k in row for k in ('title','date','venue','url','source_id','observed_at','evidence_hash')):rows.append(row)
 week=dt.datetime.now(UTC).strftime('%G-W%V')
 for row in rows:
  append(root/'data/observations'/(week+'.jsonl'),dict(run_id=run_id,**row))
 merge(inventory,rows,run_id)
 research_errors=[]
 if enrich:
  from research import enrich_inventory
  research_errors=enrich_inventory(inventory,root)
 from research import make_outbox
 groups={}
 for e in sorted(inventory.values(),key=lambda e:e['first_seen']):
  key=(title_key(e['title']),e['date'],venue_key(e['venue']),time_key(e.get('start')))
  if key in groups:e['duplicate_of']=groups[key]
  else:groups[key]=e['id']
 outbox=make_outbox(inventory,read(root/'data/outbox.json',{}))
 future=[e for e in inventory.values() if e['date']>=dt.date.today().isoformat() and not e.get('duplicate_of') and (e.get('research_status')!='complete')]
 def priority(e):
  text=e['title']+' '+e.get('description','')
  rare=bool(re.search(r'Holy Modal|Fugs|reunion|first.*(?:years|decades)|only.*appearance|world premiere|clawhammer|old.time',text,re.I))
  small=any(t in e['venue'].lower() for t in ('little hill','fifth street','back room','hillside','down home','otter','house concert'))
  return (e.get('research',{}).get('researched_at',''),not rare,not small,e['first_seen'],e['date'],e['id'])
 future.sort(key=priority)
 queue=[{k:e.get(k) for k in ('id','title','date','venue','description','date_basis','first_seen','research_status')} | {'source_urls':sorted({o['url'] for o in e['observations']})} for e in future]
 for item in queue:item['description']=(item.get('description') or '')[:1400]
 save(root/'data/research-queue.json',queue)
 fifo=sorted(queue,key=lambda e:(e['first_seen'],e['date'],e['id']))[:20]
 batch=queue[:40]+[e for e in fifo if e['id'] not in {v['id'] for v in queue[:40]}]
 save(root/'data/next-research.json',batch)
 gaps=[{'source_id':r['source_id'],'url':r['pages'][0]['url'] if r['pages'] else '', 'events_extracted':r['events_extracted'],'pending_links':r['pending_links'],'pages':[p for p in r['pages'] if p['status']!='extracted']} for r in results if not r['events_extracted'] or any(p['status'] in ('failed','dynamic-or-blocked') for p in r['pages'])]
 save(root/'data/extraction-queue.json',gaps)
 coverage=dict(run_id=run_id,started_at=started,completed_at=now(),validation='NOT VALIDATED',configured_sources=len(sources),attempted_sources=len(results),sources_with_events=sum(bool(r['events_extracted']) for r in results),sources_without_events=sum(not r['events_extracted'] for r in results),fetched_pages=sum(p['status']!='failed' for r in results for p in r['pages']),failed_pages=sum(p['status']=='failed' for r in results for p in r['pages']),extracted_candidates=len(rows),inventory_count=len(inventory),pending_research=sum(e.get('research_status')!='complete' for e in inventory.values()),research_errors=research_errors,sources=results)
 save(root/'data/inventory.json',inventory);save(root/'data/outbox.json',outbox);save(root/'data/coverage.json',coverage);append(root/'data/runs'/(week+'.jsonl'),coverage);append(root/'data/runs.jsonl',{k:v for k,v in coverage.items() if k not in ('sources','research_errors')})
 (root/'inventory.html').write_text(report_html(inventory,coverage,outbox));print(json.dumps({k:v for k,v in coverage.items() if k!='sources'},indent=2))
 return coverage

if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--enrich',action='store_true');args=a.parse_args();run(enrich=args.enrich)
