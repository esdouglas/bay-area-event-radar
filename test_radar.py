import copy, datetime as dt, json, pathlib, tempfile, unittest
from unittest.mock import patch
import radar
from research import make_outbox, enrich_inventory
class DiscoveryTests(unittest.TestCase):
 def row(self,**kw):
  r=dict(title='Unfamiliar act',date='2027-01-01',venue='Little Hill Lounge',url='https://venue.example/events/1',source_id='s',observed_at='2026-10-25T10:00:00+00:00',evidence_hash='abc');r.update(kw);return r
 def test_collect_unknown_without_filter_and_history(self):
  inv={};radar.merge(inv,[self.row()],'r1');radar.merge(inv,[self.row(observed_at='2026-10-26T10:00:00+00:00')],'r2');e=next(iter(inv.values()))
  self.assertEqual(e['first_seen'],'2026-10-25T10:00:00+00:00');self.assertEqual(e['observations'][0]['collection_count'],2);self.assertEqual(e['research_status'],'pending')
 def test_multiple_bills_preserved(self):
  inv={};radar.merge(inv,[self.row(),self.row(title='Other performer')],'run');self.assertEqual(len(inv),2)
 def test_kalx_does_not_infer_year_from_fetch(self):
  r,_=radar.extract('<h2>Saturday October 24, 2026</h2><p>Little Hill Lounge: A completely unknown name</p>','https://example.org','kalx',2030)
  self.assertEqual(r[0]['date'],'2026-10-24')
 def test_schema_nested_itemlist(self):
  b='<script type="application/ld+json">'+json.dumps({'@type':'ItemList','itemListElement':[{'item':{'@type':'MusicEvent','name':'X','startDate':'2027-02-01','location':{'name':'Room'}}}]})+'</script>'
  r,_=radar.extract(b,'https://example.org');self.assertEqual(len(r),1)
 def test_bluegrass_multiple_dates_and_year_rollover(self):
  b='<div>CONCERTS and a few dances<br>A band -<br>- Dec. 22: Room A<br>~ 2027 ~<br>- Jan. 6: Room B</div>'
  r,_=radar.extract(b,'https://example.org','bluegrass',2026);self.assertEqual([(x['title'],x['date']) for x in r],[('A band','2026-12-22'),('A band','2027-01-06')])
 def test_dynamic_shell_not_coverage(self):
  with tempfile.TemporaryDirectory() as d,patch('radar.fetch',return_value=('<p>Loading upcoming shows…</p>','https://example.org')):
   rows,result=radar.collect_source({'id':'test','url':'https://example.org'},pathlib.Path(d));self.assertEqual(rows,[]);self.assertEqual(result['pages'][0]['status'],'dynamic-or-blocked')
 def test_failed_source_recorded(self):
  with tempfile.TemporaryDirectory() as d,patch('radar.fetch',side_effect=OSError('outage')):
   rows,result=radar.collect_source({'id':'test','url':'https://example.org'},pathlib.Path(d));self.assertEqual(result['pages'][0]['status'],'failed')
 def test_frontier_rotates_and_truncation_visible(self):
  body='<a href="/events/a">A</a><a href="/events/b">B</a>'
  with tempfile.TemporaryDirectory() as d,patch('radar.fetch',side_effect=lambda u:(body,u)) as f:
   rows,result=radar.collect_source({'id':'s','url':'https://e.org','page_limit':2,'last_fetched':{'https://e.org/events/a':'2026-01-01'}},pathlib.Path(d));self.assertEqual(f.call_args_list[1].args[0],'https://e.org/events/b');self.assertTrue(result['truncated'])
 def test_alert_not_created_for_unresearched_event(self):
  inv={};radar.merge(inv,[self.row()],'r');self.assertEqual(make_outbox(inv,{}),{})
 def test_alert_idempotence_and_delivery_separate(self):
  inv={};radar.merge(inv,[self.row()],'r');e=next(iter(inv.values()));e['research']={'tier':'exceptional','reason':'Evidence supports fit','researched_at':'2026-10-25','event_verified_at':'2026-10-25','primary_event_url':'https://example.org','evidence':[{'url':'https://example.org','finding':'String band'}]}
  out=make_outbox(inv,{});self.assertEqual(len(make_outbox(inv,out)),1);self.assertIsNone(next(iter(out.values()))['delivered_at'])
 def test_invalid_research_does_not_mark_complete(self):
  inv={};radar.merge(inv,[self.row()],'r');eid=next(iter(inv))
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d);radar.save(root/'data/research.json',{eid:{'tier':'exceptional','reason':'just trust me'}})
   with patch.dict('os.environ',{'RADAR_AI_KEY':''}):errors=enrich_inventory(inv,root)
  self.assertTrue(errors);self.assertEqual(inv[eid]['research_status'],'pending')

class AliasTests(unittest.TestCase):
 def test_same_venue_city_suffix_and_ticket_title_merge(self):
  t=DiscoveryTests();inv={}
  radar.merge(inv,[t.row(title='The Crooked Jades',venue='Fifth Street Farms, Berkeley'),t.row(title='THE CROOKED JADES--Sunday, December 6',venue='Fifth Street Farms')],'r')
  self.assertEqual(len(inv),1)

class OccurrenceTests(unittest.TestCase):
 def test_two_performances_same_day_stay_separate(self):
  t=DiscoveryTests();inv={}
  radar.merge(inv,[t.row(start='2027-01-01T16:30:00-08:00'),t.row(start='2027-01-01T19:30:00-08:00')],'r')
  self.assertEqual(len(inv),2)
