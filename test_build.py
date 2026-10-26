import copy,json,unittest,io,contextlib
from build import build,ROOT
class CalendarTests(unittest.TestCase):
 def setUp(self): self.e=json.loads((ROOT/'events.json').read_text())[0]
 def test_identity_survives_changes(self):
  a=build([self.e]); e=copy.deepcopy(self.e); e.update(interest='Going',status='CANCELLED',sequence=1,title='Moved, renamed; event')
  b=build([e]); uid=lambda s:next(x for x in s.split('\r\n') if x.startswith('UID:'))
  self.assertEqual(uid(a),uid(b));self.assertIn('STATUS:CANCELLED',b);self.assertIn('TRANSP:TRANSPARENT',b);self.assertNotIn('VALARM',b)
 def test_duplicates_rejected(self):
  with self.assertRaises(AssertionError): build([self.e,self.e])
  e=copy.deepcopy(self.e);e['id']='another-id'
  with self.assertRaises(AssertionError): build([self.e,e])
 def test_utf8_folding_and_utc(self):
  self.e['title']='🎻'*80
  result=build([self.e]);self.assertTrue(all(len(x.encode())<=75 for x in result.split('\r\n')));self.assertIn('DTSTART:20261030T020000Z',result)
if __name__=='__main__':unittest.main()

class RefreshTests(unittest.TestCase):
 def setUp(self):
  self.e=json.loads((ROOT/'events.json').read_text())[0]
 def test_unknown_end_is_omitted(self):
  self.e['end']=None
  text=build([self.e]);self.assertNotIn('DTEND:',text);self.assertIn('End time not published',text)
 def test_reschedule_and_cancellation_keep_uid(self):
  from build import update_schema
  data={'eventStatus':'https://schema.org/EventRescheduled','startDate':'2026-11-02T20:00:00-08:00'}
  changed=update_schema(self.e,data,'2026-10-21T04:00:00+00:00')
  self.assertEqual(self.e['id'],changed['id']);self.assertEqual(changed['sequence'],self.e['sequence']+1);self.assertIsNone(changed['end'])
  data['eventStatus']='https://schema.org/EventCancelled'
  cancelled=update_schema(changed,data,'2026-10-21T04:01:00+00:00')
  self.assertEqual(cancelled['id'],self.e['id']);self.assertIn('STATUS:CANCELLED',build([cancelled]))
 def test_missing_source_does_not_cancel(self):
  from unittest.mock import patch
  from build import refresh
  before=copy.deepcopy(self.e)
  with contextlib.redirect_stdout(io.StringIO()), patch('urllib.request.urlopen',side_effect=OSError('source unavailable')):
   records,health=refresh([self.e])
  self.assertEqual(records[0],before);self.assertEqual(health[0]['status'],'source-unavailable')
 def test_aliases_with_canonical_source_are_duplicates(self):
  e=copy.deepcopy(self.e);e['id']='alias';e['source']='https://another.example/alias';e['canonical_source']=self.e['source']
  with self.assertRaises(AssertionError):build([self.e,e])
 def test_local_time_requires_offset(self):
  from build import parse
  with self.assertRaises(ValueError):parse('2026-10-29T19:00:00')

class RefreshRevisionTests(unittest.TestCase):
 def test_unchanged_refresh_does_not_increment_revision(self):
  from build import update_schema
  e=json.loads((ROOT/'events.json').read_text())[0]
  data={'eventStatus':'https://schema.org/EventScheduled','startDate':e['start'],'endDate':e['end']}
  changed=update_schema(e,data,'2026-10-26T00:00:00+00:00')
  self.assertEqual(changed['sequence'],e['sequence']);self.assertEqual(changed['modified_at'],e['modified_at']);self.assertEqual(changed['verified_at'],'2026-10-26T00:00:00+00:00')
