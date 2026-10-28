"""Line-oriented parsers ported verbatim from the GPT-built collector on main (radar.py @ 72a37ed).

Kept as-is (indentation style included) so behaviour matches what ran in production on main; the
adapters are: tickettailor, cafedunord, oldtime (David Brown's SF old-time list), kalx (weekly
entertainment calendar), bluegrass (Bluegrass Signal), hicks (Hicks with Sticks), plus recursive
JSON-LD for everything. Wrapped by collectors/gpt.py.
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

