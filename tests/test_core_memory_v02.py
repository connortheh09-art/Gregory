import copy,json,sys,tempfile,unittest,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gregory_core.memory_v02 import MemoryV02,views
from gregory_core.memory import MemoryStore,project_event
from _core_fixtures import experience,FixtureEmbedder
ACTOR='synthetic-owner'
class V02(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'v02.sqlite';self.now=[1700000100.];self.store=MemoryV02(self.path,owner_id=ACTOR,retention_seconds=1000,clock=lambda:self.now[0]);self.embed=FixtureEmbedder()
 def tearDown(self):self.store.close();self.tmp.cleanup()
 def fixture(self,value='locked',kind='observed',start=1700000000.,end=1700000050.,subject='station_hatch',summary=None,context='station',reality='game',time=None):
  events,run,cid=experience(start=time or start);obs=events[0];claim={'subject':subject,'predicate':'state','value':value,'evidence_kind':kind,'evidence_ids':[obs['event_id']],'valid_from':start,'valid_to':end};obs['payload']['memory_claims']=[claim];summary=summary or 'I found the station hatch '+value+'. This is a synthetic inspection.';events[-1]['payload']['memory_narrative']=summary
  self.store.ingest(events,actor=ACTOR);mid=self.store.consolidate(run,cid,actor=ACTOR,domain='station',summary=summary,claims=[claim],context=context,reality=reality);self.store.index(mid,self.embed,actor=ACTOR);return mid,events,claim,summary
 def test_overlapping_incompatible_reports_contested_both_sides(self):
  a,*_=self.fixture(kind='reported');b,*_=self.fixture('open',kind='reported');r=self.store.search('hatch',actor=ACTOR,embedder=self.embed,limit=1,contract={'subject':'station_hatch','predicate':'state'});self.assertEqual({m['memory_id'] for m in r['hits']},{a,b});self.assertEqual(r['answer_uncertainty'],'contested')
 def test_touching_intervals_not_contested(self):
  a,*_=self.fixture(end=1700000050.);b,*_=self.fixture('open',start=1700000050.,end=1700000090.);self.assertFalse(self.store.inspect(a,actor=ACTOR)['contested']);self.assertFalse(self.store.inspect(b,actor=ACTOR)['contested'])
 def test_context_and_reality_prevent_false_contest(self):
  a,*_=self.fixture();self.fixture('open',context='different');self.fixture('open',reality='fictional');self.assertFalse(self.store.inspect(a,actor=ACTOR)['contested'])
 def test_conflict_disappears_after_forget(self):
  a,*_=self.fixture();b,*_=self.fixture('open');self.store.forget(b,actor=ACTOR);self.assertFalse(self.store.inspect(a,actor=ACTOR)['contested'])
 def test_similarity_is_not_answer_support(self):
  self.fixture();r=self.store.search('totally unrelated',actor=ACTOR,embedder=self.embed);self.assertTrue(r['candidates']);self.assertFalse(r['hits']);self.assertEqual(r['answer_status'],'unknown')
 def test_supported_contract_and_wrong_subject_abstention(self):
  self.fixture();r=self.store.search('hatch',actor=ACTOR,embedder=self.embed,contract={'subject':'station_hatch','predicate':'state'});self.assertEqual(r['answer_status'],'supported');r=self.store.search('hatch',actor=ACTOR,embedder=self.embed,contract={'subject':'nonexistent','predicate':'state'});self.assertFalse(r['hits'])
 def test_reported_not_promoted_to_observed(self):
  self.fixture(kind='reported');r=self.store.search('hatch',actor=ACTOR,embedder=self.embed,contract={'subject':'station_hatch','predicate':'state'});self.assertEqual(r['answer_status'],'uncertain');self.assertEqual(r['answer_claims'][0]['evidence_kind'],'reported')
 def test_current_position_never_established(self):
  self.fixture();r=self.store.search('where am I now?',actor=ACTOR,embedder=self.embed,contract={'scope':'current','subject':'station_hatch','predicate':'state'});self.assertFalse(r['hits']);self.assertFalse(r['live_state_asserted']);self.assertEqual(r['answer_uncertainty'],'live_state_unknown')
 def test_false_premise_does_not_get_adopted(self):
  self.fixture();r=self.store.search('after hatch repaired?',actor=ACTOR,embedder=self.embed,contract={'subject':'station_hatch','predicate':'state','requires':[{'subject':'station_hatch','predicate':'repaired','value':True}]});self.assertFalse(r['hits']);self.assertEqual(r['answer_uncertainty'],'premise_unverified')
 def test_fictional_claim_cannot_answer_real_query(self):
  self.fixture(reality='fictional');r=self.store.search('hatch',actor=ACTOR,embedder=self.embed,contract={'subject':'station_hatch','predicate':'state','reality':'real'});self.assertFalse(r['hits'])
 def test_later_observation_not_retroactive_proof(self):
  self.fixture(start=1700000000.,end=1700000090.,time=1700000030.);r=self.store.search('hatch earlier',actor=ACTOR,embedder=self.embed,contract={'subject':'station_hatch','predicate':'state','as_of':1700000000.});self.assertFalse(r['hits']);r=self.store.search('hatch during minute',actor=ACTOR,embedder=self.embed,contract={'subject':'station_hatch','predicate':'state','time_window':[1700000000.,1700000060.]});self.assertTrue(r['hits'])
 def test_restart_identity_and_no_duplicate(self):
  mid,events,c,text=self.fixture();self.store.close();self.store=MemoryV02(self.path,owner_id=ACTOR,retention_seconds=1000,clock=lambda:self.now[0]);self.store.ingest(events,actor=ACTOR);self.assertEqual(self.store.consolidate(events[0]['run_id'],events[1]['correlation_id'],actor=ACTOR,domain='station',summary=text,claims=[c],context='station'),mid);self.assertEqual(self.store.db.execute('SELECT count(*) FROM episodes').fetchone()[0],1)
 def test_deleted_cannot_resurrect_after_restart(self):
  mid,events,c,text=self.fixture();self.store.forget(mid,actor=ACTOR);self.store.close();self.store=MemoryV02(self.path,owner_id=ACTOR,retention_seconds=1000,clock=lambda:self.now[0]);self.store.ingest(events,actor=ACTOR);self.assertIsNone(self.store.consolidate(events[0]['run_id'],events[1]['correlation_id'],actor=ACTOR,domain='station',summary=text,claims=[c],context='station'));self.assertEqual(self.store.db.execute('SELECT count(*) FROM vectors').fetchone()[0],0)
 def test_expiry_after_restart(self):
  mid,*_=self.fixture();self.store.close();self.now[0]+=2000;self.store=MemoryV02(self.path,owner_id=ACTOR,retention_seconds=1000,clock=lambda:self.now[0]);self.assertEqual(self.store.expire(actor=ACTOR),[mid]);self.assertFalse(self.store.search('hatch',actor=ACTOR,embedder=self.embed)['candidates'])
 def test_source_hash_and_claim_validation(self):
  mid,events,c,text=self.fixture();m=self.store.inspect(mid,actor=ACTOR);byid={e['event_id']:e for e in events};self.assertTrue(all(e['envelope_sha256']==project_event(byid[e['event_id']])['envelope_sha256'] for e in m['evidence']));bad=copy.deepcopy(c);bad['value']='invented'
  with self.assertRaises(ValueError):self.store.correct(mid,text,[bad],actor=ACTOR,reason='not real')
 def test_wrong_owner_and_v01_database_rejected(self):
  with self.assertRaises(PermissionError):self.store.ingest([],actor='guest')
  p=Path(self.tmp.name)/'v01.sqlite'
  with MemoryStore(p,owner_id=ACTOR,retention_seconds=1000):pass
  with self.assertRaises(ValueError):MemoryV02(p,owner_id=ACTOR,retention_seconds=1000)
 def test_exact_source_spans_no_synthetic_aliases(self):
  text='I wheeled the cart. Its wheels snagged. I carried the crates. More evidence remains.';self.assertEqual(len(views(text)),4);self.assertTrue(all(v in text for v in views(text)))
 def test_stale_index_callback_rejected(self):
  mid,*_=self.fixture();outer=self
  class Forgetting(FixtureEmbedder):
   def document(self,text):outer.store.forget(mid,actor=ACTOR);return (1,0,0)
  with self.assertRaises(ValueError):self.store.index(mid,Forgetting(),actor=ACTOR)
 def test_shared_observation_removes_all_dependents(self):
  a,events,_,_=self.fixture();shared=events[0]['event_id']
  events2,run,cid=experience(start=1700000020.);claim={'subject':'station_rail','predicate':'state','value':'broken','evidence_kind':'observed','evidence_ids':[events2[0]['event_id']],'valid_from':1700000020.,'valid_to':1700000060.};events2[0]['payload']['memory_claims']=[claim];text='A station rail was broken.';events2[-1]['payload']['memory_narrative']=text;self.store.ingest(events2,actor=ACTOR)
  b=self.store.consolidate(run,cid,actor=ACTOR,domain='station',summary=text,claims=[claim],extra_evidence_ids=[shared]);self.store.index(b,self.embed,actor=ACTOR)
  self.assertEqual(set(self.store.forget_evidence(shared,actor=ACTOR)),{a,b});self.assertEqual(self.store.db.execute('SELECT count(*) FROM episodes').fetchone()[0],0);self.assertEqual(self.store.db.execute('SELECT count(*) FROM vectors').fetchone()[0],0)
 def test_correction_has_new_evidence_and_purges_all_views(self):
  mid,events,old,text=self.fixture();replacement,_,_=experience(start=1700000030.);claim=copy.deepcopy(old);claim['value']='open';claim['evidence_ids']=[replacement[0]['event_id']];replacement[0]['payload']['memory_claims']=[claim];newtext='Correction: the hatch was open.';replacement[-1]['payload']['memory_narrative']=newtext;self.store.ingest(replacement,actor=ACTOR)
  self.store.correct(mid,newtext,[claim],actor=ACTOR,reason='new source record',evidence_ids=[e['event_id'] for e in replacement]);self.assertEqual(self.store.db.execute('SELECT count(*) FROM vectors WHERE memory_id=?',(mid,)).fetchone()[0],0)
  self.store.index(mid,self.embed,actor=ACTOR);m=self.store.inspect(mid,actor=ACTOR);self.assertEqual(m['revision'],2);self.assertEqual(m['claims'][0]['value'],'open');self.assertTrue(all(text not in row[0] for row in self.store.db.execute('SELECT view_text FROM vectors')))
 def test_claim_or_narrative_cannot_be_invented(self):
  mid,_,c,text=self.fixture()
  with self.assertRaisesRegex(ValueError,'narrative'):self.store.correct(mid,'I have secret unsupported knowledge.',[c],actor=ACTOR,reason='not a source narrative')
 def test_ingest_identity_collision_not_silently_ignored(self):
  _,events,_,_=self.fixture();changed=copy.deepcopy(events[0]);changed['event_id']=str(uuid.uuid4())
  with self.assertRaises(Exception):self.store.ingest([changed],actor=ACTOR)
 def test_conflict_outside_query_time_not_contested_answer(self):
  a,*_=self.fixture(start=1700000000.,end=1700000090.);self.fixture('open',start=1700000050.,end=1700000070.)
  r=self.store.search('hatch earlier',actor=ACTOR,embedder=self.embed,contract={'subject':'station_hatch','predicate':'state','as_of':1700000020.});self.assertEqual([m['memory_id'] for m in r['hits']],[a]);self.assertEqual(r['answer_status'],'supported')
 def test_observation_prioritized_but_report_not_erased(self):
  a,*_=self.fixture(kind='reported');b,*_=self.fixture('open',kind='observed');r=self.store.search('hatch',actor=ACTOR,embedder=self.embed,contract={'subject':'station_hatch','predicate':'state'});self.assertEqual(r['hits'][0]['memory_id'],b);self.assertEqual({m['memory_id'] for m in r['hits']},{a,b});self.assertTrue(r['contested']);self.assertEqual(r['answer_status'],'uncertain')
 def test_explicit_obligation_can_be_satisfied_without_a_value(self):
  self.fixture();r=self.store.search('hatch',actor=ACTOR,embedder=self.embed,contract={'subject':'station_hatch','predicate':'state','requires':[{'subject':'station_hatch','predicate':'state'}]});self.assertTrue(r['hits']);self.assertEqual(r['answer_status'],'supported')
 def test_report_cannot_silently_establish_a_presupposition(self):
  self.fixture(kind='reported');r=self.store.search('hatch',actor=ACTOR,embedder=self.embed,contract={'subject':'station_hatch','predicate':'state','requires':[{'subject':'station_hatch','predicate':'state','value':'locked'}]});self.assertFalse(r['hits']);self.assertEqual(r['premise_status'],'unverified')
 def test_future_observation_cannot_prove_a_historical_presupposition(self):
  self.fixture();self.fixture(subject='repair_record',start=1700000030.,end=1700000080.);r=self.store.search('hatch after repair',actor=ACTOR,embedder=self.embed,contract={'subject':'station_hatch','predicate':'state','as_of':1700000020.,'requires':[{'subject':'repair_record','predicate':'state','value':'locked'}]});self.assertFalse(r['hits']);self.assertEqual(r['premise_status'],'unverified')
 def test_contested_observation_cannot_satisfy_a_presupposition(self):
  self.fixture();self.fixture(subject='repair_record');self.fixture('open',subject='repair_record');r=self.store.search('hatch after repair',actor=ACTOR,embedder=self.embed,contract={'subject':'station_hatch','predicate':'state','requires':[{'subject':'repair_record','predicate':'state','value':'locked'}]});self.assertFalse(r['hits']);self.assertEqual(r['premise_status'],'unverified')
 def test_conflict_expansion_does_not_admit_later_observation(self):
  a,*_=self.fixture(end=1700000100.);self.fixture('open',end=1700000100.,time=1700000070.);r=self.store.search('hatch during first minute',actor=ACTOR,embedder=self.embed,contract={'subject':'station_hatch','predicate':'state','time_window':[1700000000.,1700000060.]});self.assertEqual([m['memory_id'] for m in r['hits']],[a]);self.assertEqual(r['answer_status'],'supported')
if __name__=='__main__':unittest.main()
