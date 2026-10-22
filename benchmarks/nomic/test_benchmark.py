import copy,json,tempfile,unittest
from pathlib import Path
from run_benchmark import fit_threshold,aggregate,prepare,ACTOR
F=json.loads(Path(__file__).with_name('fixtures.json').read_text())
def captures():
 rows=[{'input':'search_document: '+t,'vector':[1.0]+[0.0]*767} for t in sorted({e[k] for e in F['episodes'] for k in ('summary','before_summary')})]
 return {n:{'documents':rows,'load_config':{'gpu':{'ratio':0},'contextLength':512},'gguf_sha256':n} for n in ('v15','v2')}
class Benchmark(unittest.TestCase):
 def test_calibration_rejects_test_labels(self):
  with self.assertRaises(AssertionError):fit_threshold([dict(split='test',expected_ids=['E001'],gate_score=1,ranked_ids=['E001'])])
 def test_calibration_balanced_and_conservative(self):
  rows=[dict(split='dev',expected_ids=['E001'],gate_score=.8,ranked_ids=['E001']),dict(split='dev',expected_ids=[],gate_score=.2,ranked_ids=['E002'])]
  self.assertEqual(fit_threshold(rows)['threshold'],.8)
 def test_metrics_multi_target_and_assertion_exclusion(self):
  base=dict(retrieval_seconds=[.1]*3,embedding_seconds=[],historical_only=True,current_world_state='unknown; test',wrong_ids=[])
  rows=[dict(base,expected_ids=['A','B'],retrieved_ids=['B'],class_name='supported'),dict(base,expected_ids=[],retrieved_ids=['A'],class_name='unsupported'),dict(base,expected_ids=[],retrieved_ids=['B'],class_name='historical_state_assertion',retrieval_scored=False)]
  m=aggregate(rows);self.assertEqual(m['recall@1'],.5);self.assertEqual(m['MRR'],1);self.assertEqual(m['false_retrieval_rate'],1);self.assertEqual(m['no_evidence_count'],1)
 def test_lifecycle_real_core_and_space_separation(self):
  with tempfile.TemporaryDirectory() as d:
   store,ids,active,life,enc=prepare(F,Path(d)/'memory.sqlite',captures())
   try:
    self.assertEqual(life['expired'],['E061','E062','E066']);self.assertEqual(len(active),61)
    self.assertNotEqual(enc['v15'].space.key,enc['v2'].space.key)
    self.assertEqual(store.db.execute('SELECT count(*) FROM vectors').fetchone()[0],122)
    self.assertEqual(len(store.inspect(ids['E059'],actor=ACTOR)['claims']),1)
   finally:store.close()
 def test_clock_drift_aborts_instead_of_misscoring(self):
  f=copy.deepcopy(F);f['clock_after']-=7200
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaisesRegex(AssertionError,'EXACT EXPIRY'):prepare(f,Path(d)/'memory.sqlite',captures())
if __name__=='__main__':unittest.main()
