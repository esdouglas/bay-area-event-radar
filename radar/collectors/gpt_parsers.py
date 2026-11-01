"""Line-oriented parsers ported verbatim from the GPT-built collector on main (radar.py @ 72a37ed).

Kept as-is (indentation style included) so behaviour matches what ran in production on main; the
adapters are: tickettailor, cafedunord, oldtime (David Brown's SF old-time list), kalx (weekly
entertainment calendar), bluegrass (Bluegrass Signal), hicks (Hicks with Sticks), plus recursive
JSON-LD for everything. Wrapped by collectors/gpt.py.

Exception: the oldtime adapter was rewritten on radar-v2 (2026-11-01) as oldtime_events() below, to
read headers with no year ("Nov. 15 1 pm"), day ranges ("Nov 5-8 2026", "Apr 28-May 2 2027",
"Friday, November 20 - Sunday, November 22") and month-only headers ("Nov 2026", "Spring 2027"),
which the original folded into the previous event.
"""
import datetime as dt, html, json, re, urllib.parse
from html.parser import HTMLParser

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
 if adapter=='oldtime':out.extend(oldtime_events(lines,url,year))
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



# ---------------------------------------------------------------- oldtime (David Brown's list)
_MON = r'(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?'
_WD = r'(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*[.,]?\s+)'
_HEADER = re.compile(
    rf'^{_WD}?{_MON}\s+(\d{{1,2}})(?:,?\s+(20\d\d))?'
    rf'(?:\s*-\s*{_WD}?(?:{_MON}\s+)?(\d{{1,2}})(?:,?\s+(20\d\d))?)?(?=[\s(?,]|$)(.*)$', re.I)
_UNDATED = re.compile(rf'^(?:{_WD}?{_MON}(?:\s+or\s+{_MON}|\s*-\s*{_MON})?|Spring|Summer|Fall|Autumn|Winter)\s+20\d\d\b', re.I)
_TIMEISH = re.compile(r'[\d:\s\-–apmAPM().,]*')
_SUBDATE = re.compile(r'^(\d{1,2})/(\d{1,2})\s+(.*)$')
_OLD_VENUE = re.compile(r'Berkeley|Oakland|Monterey|Santa Cruz|Freight|Back Room|Ashkenaz|SF|Chapel|Albany')
_bay_re = None


def _month(name):
    return dt.datetime.strptime(name[:3].title(), '%b').month


def _bay(line):
    """True when a line names a Bay Area / NorCal place the radar covers."""
    global _bay_re
    if _bay_re is None:
        from ..normalize import BAY_AREA_CITIES
        _bay_re = re.compile(r'\b(?:' + '|'.join(re.escape(c) for c in sorted(BAY_AREA_CITIES, key=len, reverse=True)) + r')\b', re.I)
    return bool(_OLD_VENUE.search(line) or _bay_re.search(line))


def oldtime_events(lines, url, year):
    """Blocks between date headers in the UPCOMING section. Single dated blocks are kept as before;
    multi-day ranges are kept only when the block names a Bay Area place (the list covers festivals
    nationwide); month-only blocks yield only their "M/D time venue" sub-lines (tour dates)."""
    blocks, block, active = [], None, False
    last = None  # date of the previous dated header, for year inference
    for line in lines:
        if line == 'UPCOMING':
            active = True
            continue
        if not active:
            continue
        if line.startswith(('ONGOING', 'PENDING OR DEFUNCT')):
            break
        m = _HEADER.match(line)
        if m and (m[3] or m[6] or _TIMEISH.fullmatch(m[7] or '') and len(m[7] or '') <= 20):
            if block:
                blocks.append(block)
            y = int(m[3] or m[6] or (last.year if last else year))
            inferred = not (m[3] or m[6])
            try:
                start = dt.date(y, _month(m[1]), int(m[2]))
                if inferred and last and start < last - dt.timedelta(days=60):
                    start = start.replace(year=y + 1)
                end = None
                if m[5]:
                    ey = int(m[6] or start.year)
                    end = dt.date(ey, _month(m[4] or m[1]), int(m[5]))
                    if end < start:
                        end = end.replace(year=end.year + 1) if not m[6] else None
                    if end and (end - start).days > 21:
                        end = None
            except ValueError:
                block = None
                continue
            last = start
            block = {'start': start, 'end': end, 'inferred': inferred, 'lines': []}
            continue
        if _UNDATED.match(line):
            if block:
                blocks.append(block)
            yr = re.search(r'20\d\d', line)
            block = {'start': None, 'year': int(yr[0]), 'lines': []}
            continue
        if block:
            block['lines'].append(line)
    if block:
        blocks.append(block)

    out = []
    for b in blocks:
        meaningful = [t for t in b['lines'] if not t.startswith(('http', '====', '----')) and not re.fullmatch(r'\(.*\)', t)]
        if not meaningful:
            continue
        title = meaningful[0].rstrip(';,. ')
        desc = ' | '.join(b['lines'])[:5000]
        if b['start'] is None:
            for t in meaningful[1:]:
                s = _SUBDATE.match(t)
                if not s:
                    continue
                try:
                    d = dt.date(b['year'], int(s[1]), int(s[2])).isoformat()
                except ValueError:
                    continue
                venue = re.sub(r'^\d{1,2}(?::\d\d)?\s*(?:am|pm)\s*', '', s[3], flags=re.I).strip() or 'See source; venue unverified'
                out.append(event(title, d, venue, url, description=desc,
                                 date_basis='tour-date line under a month-only header; verify before alert'))
            continue
        if b['end'] and not any(_bay(t) for t in meaningful):
            continue
        venue = next((t for t in meaningful[1:] if _bay(t)), 'See source; venue unverified')
        basis = ('source month/day; year inferred; verify before alert' if b['inferred']
                 else 'explicit dated block; venue and lineup need primary verification')
        kw = {'end': b['end'].isoformat()} if b['end'] else {}
        out.append(event(title, b['start'].isoformat(), venue, url, description=desc, date_basis=basis, **kw))
    return out
