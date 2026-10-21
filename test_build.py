import copy,json,unittest
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
