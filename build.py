"""Verified-source radar publisher; standard library only."""
import json, pathlib, datetime as dt, re, urllib.request, html, hashlib
ROOT=pathlib.Path(__file__).resolve().parent
UTC=dt.timezone.utc

def parse(value):
    return dt.datetime.fromisoformat(re.sub(r"([+-]\d{2})(\d{2})$",r"\1:\2",value).replace("Z","+00:00"))
def stamp(value):
    return parse(value).astimezone(UTC).strftime('%Y%m%dT%H%M%SZ')
def escape(s):
    return str(s).replace('\\','\\\\').replace('\n','\\n').replace(';','\\;').replace(',','\\,').replace('\r','')
def fold(s):
    parts=[]; line=''
    for c in s:
        if len((line+c).encode())>75:
            parts.append(line); line=' '+c
        else: line+=c
    return '\r\n'.join(parts+[line])
def build(records):
    lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Bay Area Event Radar//EN','CALSCALE:GREGORIAN','METHOD:PUBLISH','X-WR-CALNAME:Bay Area Event Radar','X-WR-TIMEZONE:America/Los_Angeles']
    seen=set(); occurrences=set()
    for e in sorted(records,key=lambda x:x['id']):
        assert e['id'] not in seen, 'Duplicate immutable ID'
        seen.add(e['id'])
        key=(e['source'],e['start'])
        assert key not in occurrences, 'Duplicate occurrence'
        occurrences.add(key)
        assert e['interest'] in ['FYI','Interested','Going']
        assert e['status'] in ['CONFIRMED','CANCELLED']
        assert parse(e['end'])>parse(e['start'])
        uid=e['id']+'@bay-area-event-radar.esdouglas.github.io'
        desc='Source: '+e['source']+'\nTicket inventory: unverified; check organizer.\nVerified: '+e['verified_at']
        lines+=['BEGIN:VEVENT','UID:'+uid,'DTSTAMP:'+stamp(e['modified_at']),'LAST-MODIFIED:'+stamp(e['modified_at']),'SEQUENCE:'+str(e['sequence']),'DTSTART:'+stamp(e['start']),'DTEND:'+stamp(e['end']),'SUMMARY:'+escape('['+e['interest']+'] '+e['title']),'CATEGORIES:'+e['interest'],'STATUS:'+e['status'],'TRANSP:TRANSPARENT','LOCATION:'+escape(e['location']),'URL:'+e['source'],'DESCRIPTION:'+escape(desc),'END:VEVENT']
    return '\r\n'.join(map(fold,lines+['END:VCALENDAR']))+'\r\n'
def refresh(records):
    now=dt.datetime.now(UTC).isoformat()
    for e in records:
        if parse(e['end'])<dt.datetime.now(UTC): continue
        req=urllib.request.Request(e['source'],headers={'User-Agent':'BayAreaEventRadar/1.0'})
        page=urllib.request.urlopen(req,timeout=30).read().decode()
        candidates=[json.loads(s) for s in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',page,re.S)]
        data=next(d for d in candidates if isinstance(d,dict) and d.get('@type')=='Event' and d.get('url')==e['source'])
        # A missing/failed page is never interpreted as cancellation.
        status=data.get('eventStatus','').split('/')[-1]
        assert status in ['EventScheduled','EventCancelled','EventRescheduled'], 'Unsupported status; review required'
        changed=dict(e,title=html.unescape(data['name']),start=data['startDate'],end=data['endDate'],location=html.unescape(data['location']['name'])+', '+data['location']['address']['streetAddress'],status='CANCELLED' if status=='EventCancelled' else 'CONFIRMED')
        if changed!=e:
            changed.update(sequence=e['sequence']+1,modified_at=now)
        changed['verified_at']=now
        e.update(changed)
    return records
if __name__=='__main__':
    import sys
    p=ROOT/'events.json'; records=json.loads(p.read_text())
    if '--refresh' in sys.argv: records=refresh(records)
    output=build(records)
    p.write_text(json.dumps(records,indent=2)+'\n')
    (ROOT/'radar.ics').write_bytes(output.encode())
    print(f'Validated {len(records)} events; sha256 {hashlib.sha256(output.encode()).hexdigest()}')
