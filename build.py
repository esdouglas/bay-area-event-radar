"""Build a subscribable calendar from a persistent verified-event registry."""
import datetime as dt
import hashlib
import html
import json
import pathlib
import re
import sys
import urllib.request
from html.parser import HTMLParser
ROOT = pathlib.Path(__file__).resolve().parent
UTC = dt.timezone.utc

def parse(value):
    result = dt.datetime.fromisoformat(re.sub(r'([+-]\d{2})(\d{2})$',r'\1:\2',value).replace('Z','+00:00'))
    if result.tzinfo is None:
        raise ValueError('Event time must include a UTC offset')
    return result

def stamp(value):
    return parse(value).astimezone(UTC).strftime('%Y%m%dT%H%M%SZ')

def escape(value):
    return str(value).replace('\\','\\\\').replace('\r','').replace('\n','\\n').replace(';','\\;').replace(',','\\,')

def fold(line):
    result=[]; part=''
    for char in line:
        if len((part+char).encode()) > 75:
            result.append(part); part=' '+char
        else: part+=char
    return '\r\n'.join(result+[part])

def identity(e):
    # A shared canonical source identity catches aliases across discovery methods.
    return (e.get('canonical_source',e['source']).split('?')[0].rstrip('/'),stamp(e['start']))

def build(records):
    lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Bay Area Event Radar//EN','CALSCALE:GREGORIAN','METHOD:PUBLISH','X-WR-CALNAME:Bay Area Event Radar','X-WR-TIMEZONE:America/Los_Angeles']
    ids=set(); occurrences=set()
    for e in sorted(records,key=lambda x:x['id']):
        assert e['id'] not in ids,'Duplicate immutable ID'
        assert identity(e) not in occurrences,'Duplicate occurrence'
        ids.add(e['id']); occurrences.add(identity(e))
        assert re.fullmatch(r'[a-zA-Z0-9._-]+',e['id']),'Invalid immutable ID'
        assert e['interest'] in ['FYI','Interested','Going']
        assert e['status'] in ['CONFIRMED','CANCELLED','TENTATIVE']
        assert e['source'].startswith('https://')
        assert isinstance(e['sequence'],int) and e['sequence']>=0
        if e.get('end'): assert parse(e['end'])>parse(e['start'])
        desc='Source: '+e['source']+'\nTicket inventory: unverified; check organizer.\nVerified: '+e['verified_at']
        if not e.get('end'): desc+='\nEnd time not published; no duration assumed.'
        if e.get('notes'): desc+='\n'+e['notes']
        lines+=['BEGIN:VEVENT','UID:'+e['id']+'@bay-area-event-radar.esdouglas.github.io','DTSTAMP:'+stamp(e['modified_at']),'LAST-MODIFIED:'+stamp(e['modified_at']),'SEQUENCE:'+str(e['sequence']),'DTSTART:'+stamp(e['start'])]
        if e.get('end'): lines.append('DTEND:'+stamp(e['end']))
        lines+=['SUMMARY:'+escape('['+e['interest']+'] '+e['title']),'CATEGORIES:'+e['interest'],'STATUS:'+e['status'],'TRANSP:TRANSPARENT','LOCATION:'+escape(e['location']),'URL:'+e['source'],'DESCRIPTION:'+escape(desc),'END:VEVENT']
    return '\r\n'.join(map(fold,lines+['END:VCALENDAR']))+'\r\n'

class Schemas(HTMLParser):
    def __init__(self): super().__init__(); self.active=False; self.buffer=''; self.values=[]
    def handle_starttag(self,tag,attrs):
        if tag=='script' and dict(attrs).get('type')=='application/ld+json':self.active=True;self.buffer=''
    def handle_data(self,data):
        if self.active:self.buffer+=data
    def handle_endtag(self,tag):
        if tag=='script' and self.active:
            self.active=False
            try:self.values.append(json.loads(self.buffer))
            except json.JSONDecodeError:pass

def walk(value):
    if isinstance(value,list):
        for item in value:yield from walk(item)
    elif isinstance(value,dict):
        if 'Event' in str(value.get('@type','')):yield value
        if '@graph' in value:yield from walk(value['@graph'])

def update_schema(e,data,now):
    status=data.get('eventStatus','').split('/')[-1]
    if status not in ['EventScheduled','EventCancelled','EventRescheduled','EventPostponed']:
        raise ValueError('Missing or unsupported event status')
    start=data.get('startDate')
    parse(start)
    if status=='EventPostponed':
        # Preserve the existing UID/date as an explicit cancelled occurrence until a replacement is verified.
        changed=dict(e,status='CANCELLED',notes='Organizer marks this performance postponed. Replacement date unverified.')
    else:
        changed=dict(e,start=start,status='CANCELLED' if status=='EventCancelled' else 'CONFIRMED')
        end=data.get('endDate')
        if end:
            parse(end)
            if parse(end)<=parse(start):raise ValueError('Invalid source end time')
        changed['end']=end
        loc=data.get('location',{})
        if isinstance(loc,dict) and loc.get('name'):
            address=loc.get('address',{})
            address=address.get('streetAddress','') if isinstance(address,dict) else address
            changed['location']=html.unescape(loc['name'])+(', '+address if address and address!=loc['name'] else '')
    changed['verified_at']=now
    if any(changed.get(k)!=e.get(k) for k in ('start','end','location','status','notes')):changed.update(sequence=e['sequence']+1,modified_at=now)
    return changed

def refresh(records):
    now=dt.datetime.now(UTC).isoformat(); health=[]; pages={}
    for e in records:
        if parse(e.get('end') or e['start']) < dt.datetime.now(UTC):continue
        if e.get('refresh_mode','jsonld')!='jsonld':
            health.append({'id':e['id'],'status':'editorial-review','verified_at':e['verified_at']});continue
        try:
            if e['source'] not in pages:
                req=urllib.request.Request(e['source'],headers={'User-Agent':'BayAreaEventRadar/1.0'})
                text=urllib.request.urlopen(req,timeout=30).read().decode()
                parser=Schemas();parser.feed(text);pages[e['source']]=list(walk(parser.values))
            candidates=[d for d in pages[e['source']] if html.unescape(d.get('name',''))==e.get('schema_name',e['title'])]
            if len(candidates)!=1:raise ValueError('Expected exactly one matching organizer event')
            e.update(update_schema(e,candidates[0],now))
            health.append({'id':e['id'],'status':'refreshed','verified_at':now})
        except Exception as error:
            # Outages and missing listings are not evidence of cancellation.
            print('::warning::Source refresh unavailable for '+e['id']+': '+str(error))
            health.append({'id':e['id'],'status':'source-unavailable','verified_at':e['verified_at'],'error':str(error)})
    return records,health

def site(records):
    future=sorted([e for e in records if parse(e.get('end') or e['start'])>=dt.datetime.now(UTC)],key=lambda e:parse(e['start']))
    rows=''.join('<tr><td>'+html.escape(e['start'][:16].replace('T',' '))+'</td><td><a href="'+html.escape(e['source'],quote=True)+'">'+html.escape(e['title'])+'</a><br><small>'+html.escape(e['location'])+'</small></td><td>'+e['interest']+(' · cancelled' if e['status']=='CANCELLED' else '')+'</td></tr>' for e in future)
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Bay Area Event Radar</title><style>body{max-width:960px;margin:45px auto;padding:24px;font:17px/1.6 system-ui;color:#172d3d;background:#f7f5ee}a{color:#075e69}td,th{text-align:left;vertical-align:top;padding:12px 8px;border-bottom:1px solid #d7ddd8}small{color:#52686c}code{overflow-wrap:anywhere}table{width:100%;border-collapse:collapse}</style><h1>Bay Area Event Radar</h1><p><a href="inventory.html">Broad discovery inventory and actual source coverage (shadow validation)</a></p><p><a href="webcal://esdouglas.github.io/bay-area-event-radar/radar.ics">Subscribe to the calendar</a></p><p>Google Calendar: Other calendars → + → From URL. Paste:</p><code>https://esdouglas.github.io/bay-area-event-radar/radar.ics</code><p>Subscribe once. Your calendar app controls refresh timing. All entries show as free; the feed includes no alarms. A listing does not confirm ticket availability.</p><p><strong>'''+str(len(future))+''' upcoming performances</strong>. Multiple dates are separate choices, not attendance commitments. All times in the calendar reflect the venue’s local time; only verified end times are included.</p><table><thead><tr><th>Date</th><th>Performance</th><th>Interest</th></tr></thead><tbody>'''+rows+'''</tbody></table><p>Known structured sources refresh every six hours in GitHub Actions. Other sources require an editorial check. <a href="https://github.com/esdouglas/bay-area-event-radar/actions">Publishing history</a> · <a href="https://github.com/esdouglas/bay-area-event-radar">Source and maintenance notes</a></p></html>'''

if __name__=='__main__':
    p=ROOT/'events.json';records=json.loads(p.read_text())
    if '--refresh' in sys.argv:
        records,health=refresh(records)
        (ROOT/'health.json').write_text(json.dumps(health,indent=2)+'\n')
    output=build(records)
    p.write_text(json.dumps(records,indent=2,ensure_ascii=False)+'\n')
    (ROOT/'radar.ics').write_bytes(output.encode())
    (ROOT/'index.html').write_text(site(records))
    print(f'Validated {len(records)} events; sha256 {hashlib.sha256(output.encode()).hexdigest()}')
