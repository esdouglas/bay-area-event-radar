"""Reproducible retrospective extraction benchmark. Never fabricates lead time."""
import datetime as dt, json
from radar import ROOT, read, save, extract, norm, now

def evaluate():
 cases=read(ROOT/'tests/historical_cases.json',[]);manifest={m['file']:m for m in read(ROOT/'tests/fixtures/manifest.json',[])};cache={};results=[]
 for c in cases:
  f=c['fixture'];m=manifest[f]
  if f not in cache:cache[f]=extract((ROOT/'tests/fixtures'/f).read_text(),m['url'],m['adapter'],2026)[0]
  matches=[e for e in cache[f] if norm(c['title']) in norm(e['title']) and c['date']==e['date'] and norm(c['venue'])==norm(e['venue'])]
  results.append(dict(**c,recovered=bool(matches),match_count=len(matches),proven_early_discovery=False,actual_test_observed_at=m['captured_at'],source_url=m['url']))
 pos=[r for r in results if 'positive' in r['relevance']];neg=[r for r in results if 'negative' in r['relevance']]
 result=dict(evaluated_at=now(),status='NOT VALIDATED',positive_cases=len(pos),positive_recovered=sum(r['recovered'] for r in pos),retrospective_extraction_recall=sum(r['recovered'] for r in pos)/len(pos),named_misses_recovered=sum(r['recovered'] for r in pos if r['relevance']=='user-positive'),negative_controls_retained=sum(r['recovered'] for r in neg),negative_controls=len(neg),proven_early_discoveries=0,end_to_end_alert_recall=None,alert_false_positive_rate=None,alert_precision=None,limitations=['Retrospective fixtures captured after the shows; no successful pre-event collection or alert proven.','20 additional positive labels are provisional assistant judgments; only three named misses are user-confirmed.','KALX dominates; convenience/seeded sample, not representative held-out recall.','Direct Songkick/Bandsintown event pages test parsing, not autonomous enumeration from historical indexes.','Low-fit events SHOULD remain in inventory; alert false positives cannot be measured until independently labeled ranking predictions and delivery exist.','A date/venue match to an aggregator is not primary ticket or cancellation verification.'],cases=results)
 save(ROOT/'data/benchmark.json',result);return result
if __name__=='__main__':
 r=evaluate();print(json.dumps({k:v for k,v in r.items() if k!='cases'},indent=2))
