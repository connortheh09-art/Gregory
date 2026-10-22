"""Replay real vectors through both isolated stores; report EVERY independent case.

Question bridge receives only the frozen question map and source catalog, never labels.
Strict evaluator labels remain separate from conservative adapter-boundary outcomes.
"""
from pathlib import Path
import argparse,copy,gzip,hashlib,json,math,sys,time,uuid
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'deployments/oldpc'))
from greg_events import EventFactory,TraceContext
from gregory_core.memory import MemoryStore,canonical,timestamp
from gregory_core.memory_v02 import MemoryV02,views
from gregory_core.embeddings import LocalNomic,unit_vector
ACTOR='synthetic-v02-evaluation-owner'
BASELINE_GATE=0.6769125518493936
CLAIM_KEYS={'subject','predicate','value','evidence_kind','evidence_ids','valid_from','valid_to'}
def uid(name):return str(uuid.uuid5(uuid.NAMESPACE_URL,'gregory-v02-fixture:'+name))
def save(path,data):path.write_text(json.dumps(data,indent=2)+'\n')
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def narrative(e,old):
 text=old['claim']
 if old['occurred']!=e['occurred']:
  before=datetime.fromisoformat(old['occurred'].replace('Z','+00:00')).strftime('%H:%M');after=datetime.fromisoformat(e['occurred'].replace('Z','+00:00')).strftime('%H:%M:%S');text=text.replace(before,after)
 return text

def shared_event(specs):
 if not any(e['spec'].get('shared_observation') for e in specs):return None
 first=specs[0]['spec'];factory=EventFactory(uid('shared-source'),first['session_id'],clock=lambda:int(timestamp(first['occurred'])*1e9)-1000000,mono=lambda:0);ev=factory.make('observation.accepted',{'fresh':True}).as_dict();ev['event_id']=uid('OBS-A');return ev

def expand(e,old):
 run,cid=e['run_id'],e['correlation_id'];base=timestamp(e['occurred']);events=[];factory=EventFactory(run,e['session_id'],clock=lambda:int(base*1e9)+len(events)*1000000,mono=lambda:0);trace=TraceContext(run,cid)
 def emit(kind,payload,refs=(),correlated=True):
  row=factory.make(kind,payload,trace=trace if correlated else None,observation_ids=refs).as_dict();row['event_id']=uid(e['id']+':'+str(len(events))+':'+kind);events.append(row);return row
 obs=emit('observation.accepted',{'fresh':True},correlated=False)
 claims=[]
 for c in e['claims']:
  row={k:copy.deepcopy(v) for k,v in c.items() if k in CLAIM_KEYS};row['evidence_ids']=[obs['event_id']];claims.append(row)
 initial=copy.deepcopy(claims)
 if e.get('superseded_claim'):
  for c in initial:c['value']=e['superseded_claim']['value']
 obs['payload']['memory_claims']=initial
 emit('decision.requested',{'origin':'deterministic'});emit('decision.applied',{})
 emit('action.dispatch',{'parameters_complete':True,'action':{'activity':'follow' if 'follow' in claims[0]['subject'] else 'explore'}})
 emit('controller.feedback',{'status':'arrived' if e['outcome']=='succeeded' else 'blocked' if e['outcome']=='failed' else 'idle'},[obs['event_id']])
 if e['outcome'] in ('succeeded','failed'):emit('outcome.evaluated',{'world_outcome':e['outcome'],'verdict':'pass' if e['outcome']=='succeeded' else 'fail','evaluator':'synthetic.v02'},[obs['event_id']])
 text=narrative(e,old);closed=emit('experience.closed',{'world_outcome':e['outcome'],'closure_reason':'verified_arrival' if e['outcome']=='succeeded' else 'timeout','memory_narrative':text},[obs['event_id']])
 # Synthetic adapter extension: PR1's unchanged producer allowlist drops v0.2 fields.
 # Attach these bounded fields to the test envelope, as with memory_claims above.
 closed['payload']['memory_narrative']=text
 correction_ids=[]
 if e['lifecycle']=='correct':
  correction=emit('observation.accepted',{'memory_narrative':e['correction_text']})
  correction['payload']['memory_narrative']=e['correction_text']
  for c in claims:c['evidence_ids']=[correction['event_id']]
  correction['payload']['memory_claims']=claims;correction_ids=[correction['event_id']]
 return {'spec':e,'events':events,'initial_claims':initial,'final_claims':claims,'summary':text,'correction_ids':correction_ids}

def bridge(mapping,store):
 """Conservative literal bridge. No answer key, case ID or disposition argument."""
 source=mapping['adapter_contract'];notes=[]
 if mapping['adapter_confidence']=='underdetermined':return None,['underdetermined_question_contract']
 subject,predicate=source['subject'],source['predicate']
 # Unique literal identifier-prefix resolution, not semantic subject guessing.
 subjects={r[0] for r in store.db.execute('SELECT DISTINCT subject FROM claims')}
 if subject not in subjects:
  tokens=set(subject.split('_'));compatible=[s for s in subjects if tokens<=set(s.split('_'))]
  if len(compatible)==1:subject=compatible[0];notes.append('unique_literal_subject_resolution')
 result={'subject':subject,'predicate':predicate,'reality':source['reality']};mode=source['time']['mode'];value=source['time']['value']
 if mode=='live':result['scope']='current'
 elif mode=='latest_recorded':result['selection']='latest_recorded'
 elif mode=='relative_later':result['selection']='latest_recorded'
 elif mode=='relative_before_change':result['selection']='earliest_recorded';notes.append('relative_before_change_approximation_not_transition_proof')
 elif mode=='as_of' and value:
  # Day words name a day; explicit at-ten/eleven questions name a minute window.
  text=mapping['question_text'].lower();seconds=86400 if 'on the ' in text else 60
  result['time_window']=[timestamp(value),timestamp(value)+seconds]
 for need in source['presuppositions']:
  obligation=need.get('obligation')
  if need.get('class')=='typed' and obligation:
   typed=copy.deepcopy(obligation)
   if typed['subject'] not in subjects:
    compatible=[s for s in subjects if set(typed['subject'].split('_'))<=set(s.split('_'))]
    if len(compatible)==1:typed['subject']=compatible[0]
   result.setdefault('requires',[]).append(typed)
  else:
   result.setdefault('requires',[]).append({'subject':'unresolved_obligation','predicate':hashlib.sha256(need['text'].encode()).hexdigest(),'value':True});notes.append('unresolved_presupposition:'+need['text'])
 return result,notes

def grade(case,result,episode_ids):
 actual=[episode_ids[m['memory_id']] for m in result['hits']];scored=[episode_ids[m['memory_id']] for m in result['candidates']] if case.get('score_layer')=='candidates' else actual;fail=[];disposition=case['disposition']
 if result.get('live_state_asserted') or not result['current_world_state'].startswith('unknown'):fail.append('LIVE_STATE_ASSERTED')
 if disposition in ('abstain','premise_rejected') and actual:fail.append('must_not_accept_any_memory')
 if disposition in ('retrieve','contested'):
  for expected in case['expected_ids']:
   if expected not in scored or scored.index(expected)>=case['min_rank']:fail.append('missing_or_late:'+expected)
 if disposition=='contested' and not (result.get('contested') or case.get('score_layer')=='candidates' and any(m['contested'] for m in result['candidates'])):fail.append('contested_flag_missing')
 for forbidden in case.get('forbidden_ids',[]):
  if forbidden in actual:fail.append('forbidden:'+forbidden)
 for forbidden in case.get('forbidden_above_rank',{}):
  if forbidden in actual and any(expected in actual and actual.index(forbidden)<actual.index(expected) for expected in case['expected_ids']):fail.append('forbidden_outranks_expected:'+forbidden)
 for required in case.get('must_remain_visible',[]):
  if required not in actual:fail.append('dissent_erased:'+required)
 for text in case.get('must_not_contain_text',[]):
  if any(text in m['summary'] for m in result['hits']):fail.append('obsolete_text_served')
 expected_status='unknown' if case['answer_status']=='unconfirmed_contract_underdetermined' else case['answer_status']
 if expected_status!=result['answer_status']:fail.append('answer_status:'+result['answer_status']+' expected:'+case['answer_status'])
 return actual,fail

def main():
 p=argparse.ArgumentParser();p.add_argument('--fixtures',type=Path,required=True);p.add_argument('--original',type=Path,required=True);p.add_argument('--contracts',type=Path,required=True);p.add_argument('--capture',type=Path,required=True);p.add_argument('--delta',type=Path);p.add_argument('--out',type=Path,required=True);args=p.parse_args();args.out.mkdir(parents=True,exist_ok=False)
 fixture=json.loads(args.fixtures.read_text());original=json.loads(args.original.read_text());mapping=json.loads(args.contracts.read_text());assert mapping['frozen_against_sha256']=='a58a6d42da670b37ef765ed02485bf2897a7509016b9c13f60063c4b2ea07694' and digest(args.fixtures)=='83ec6a431f58108370b97e77803d426285714aab1722b6895c65e9eb19be8ea9', 'declared v14 / actual v15 compatibility receipt required';cap=json.loads(gzip.decompress(args.capture.read_bytes()));assert cap['status']=='TESTED' and not cap['initial_loaded'] and not cap['final_loaded']
 captures=[cap]
 if args.delta:captures.append(json.loads(gzip.decompress(args.delta.read_bytes())))
 vectors={}
 for capture in captures:
  assert capture['gguf_sha256']==cap['gguf_sha256'] and capture['load_config']==cap['load_config']
  vectors.update({r['input']:r['vector'] for r in capture['documents']+capture['queries']})
 embed=LocalNomic(lambda texts:[vectors[t] for t in texts],revision=cap['gguf_sha256']+'-cpu512-same-full768-prefix-v1')
 old={e['id']:e for s in original['scenarios'] for e in s['episodes']};expanded={e['id']:expand(e,old[e['id']]) for s in fixture['scenarios'] for e in s['episodes']};maps={m['case_id']:m for m in mapping['contracts']};clock=[timestamp(fixture['clock']['before'])];retention=fixture['clock']['retention_seconds'];output=[];source_export=[]
 for row in expanded.values():source_export.extend(row['events'])
 for scenario in fixture['scenarios']:
  shared=shared_event([expanded[e['id']] for e in scenario['episodes']])
  if shared:source_export.append(shared)
 save(args.out/'SOURCE_EVENTS.json',source_export)
 for case in fixture['cases']:
  mapping_row=maps[case['id']];assert mapping_row['question_text']==case['query'];assert case['corpus_scope']=='scenario'
  specs=[expanded[e] for e in case['eligible_episode_ids']];clock[0]=timestamp(fixture['clock']['before']);v2path=args.out/(case['id']+'-v02.sqlite');v1path=args.out/(case['id']+'-v01.sqlite');v2=MemoryV02(v2path,owner_id=ACTOR,retention_seconds=retention,clock=lambda:clock[0]);v1=MemoryStore(v1path,owner_id=ACTOR,retention_seconds=retention,clock=lambda:clock[0]);ids2={};ids1={};baseline_errors=[];restart={}
  try:
   all_events=[e for spec in specs for e in spec['events']];shared=None
   ev=shared_event(specs)
   if ev:shared=ev['event_id'];all_events.append(ev)
   v2.ingest(all_events,actor=ACTOR);v1.ingest(all_events,actor=ACTOR,source_label='independent-synthetic-v02')
   for spec in specs:
    e=spec['spec'];context=case['scenario'];reality='fictional' if 'fictional' in spec['summary'].lower() else 'real'
    mid=v2.consolidate(e['run_id'],e['correlation_id'],actor=ACTOR,domain=e['domain'],context=context,reality=reality,summary=spec['summary'],claims=spec['initial_claims'],extra_evidence_ids=[shared] if shared else [])
    ids2[e['id']]=mid
    if e['lifecycle']=='correct':v2.correct(mid,e['correction_text'],spec['final_claims'],actor=ACTOR,reason='independent fixture correction',evidence_ids=spec['correction_ids'])
    v2.index(mid,embed,actor=ACTOR)
    try:
     baseline=v1.consolidate(e['run_id'],e['correlation_id'],actor=ACTOR,domain=e['domain']);ids1[e['id']]=baseline;v1.correct(baseline,e.get('correction_text',spec['summary']),actor=ACTOR,reason='synthetic fixture narrative');v1.index(baseline,embed,actor=ACTOR)
    except ValueError as exc:baseline_errors.append(str(exc))
    if e['lifecycle']=='forget':v2.forget(mid,actor=ACTOR);v1.forget(ids1[e['id']],actor=ACTOR)
   if 'forget_evidence' in case.get('setup',''):
    removed=v2.forget_evidence(shared,actor=ACTOR);assert len(removed)==2
    # v0.1 has no explicit cross-run dependency attachment; do not forge citations.
    v1.forget_evidence(shared,actor=ACTOR);restart['baseline_shared_dependency_not_represented']=True
   if any(word in case.get('setup','') for word in ['reopen','across a reopen']):
    v2.close();v1.close();v2=MemoryV02(v2path,owner_id=ACTOR,retention_seconds=retention,clock=lambda:clock[0]);v1=MemoryStore(v1path,owner_id=ACTOR,retention_seconds=retention,clock=lambda:clock[0]);v2.ingest(all_events,actor=ACTOR);v1.ingest(all_events,actor=ACTOR,source_label='independent-synthetic-v02')
    for spec in specs:
     e=spec['spec'];again=v2.consolidate(e['run_id'],e['correlation_id'],actor=ACTOR,domain=e['domain'],context=case['scenario'],reality='real',summary=spec['summary'],claims=spec['initial_claims']);assert again==ids2[e['id']]
    restart['v02_episode_count']=v2.db.execute('SELECT count(*) FROM episodes').fetchone()[0];restart['stable_ids']=True
   clock[0]=timestamp(fixture['clock']['after']);expired2=v2.expire(actor=ACTOR);expired1=v1.expire(actor=ACTOR);expected_expiry=1 if any(e['spec']['lifecycle']=='expire' for e in specs) else 0;assert len(expired2)==expected_expiry and expired1==expected_expiry
   contract,notes=bridge(mapping_row,v2);result=v2.search(case['query'],actor=ACTOR,embedder=embed,domain=case['filters'].get('domain'),context=case['scenario'],contract=contract)
   reverse2={v:k for k,v in ids2.items()};actual,failures=grade(case,result,reverse2)
   # Baseline is semantic-only, NOT the legacy method's automatic keyword fusion.
   q=unit_vector(embed.query(case['query']),768);rank=[];reverse1={v:k for k,v in ids1.items()}
   for row in v1.db.execute('SELECT memory_id,vector FROM vectors JOIN memories USING(memory_id) WHERE expires>?',(clock[0],)):
    v=unit_vector(json.loads(row['vector']),768);rank.append((sum(a*b for a,b in zip(q,v)),reverse1[row['memory_id']]))
   rank.sort(key=lambda x:(-x[0],x[1]));accepted1=[e for _,e in rank[:5]] if rank and rank[0][0]>=BASELINE_GATE else []
   row={'case_id':case['id'],'category':case['category'],'query':case['query'],'corpus_scope':'scenario','eligible_episode_ids':case['eligible_episode_ids'],'expected_ids':case['expected_ids'],'expected_disposition':case['disposition'],'expected_answer_status':case['answer_status'],'score_layer':case.get('score_layer','hits'),'adapter_confidence':mapping_row['adapter_confidence'],'actual_contract':contract,'adapter_notes':notes,'candidate_ids':[reverse2[m['memory_id']] for m in result['candidates']],'candidates':[{'episode_id':reverse2[m['memory_id']],'score':m['relevance'],'matching_view':m['matching_view'],'contested':m['contested'],'claims':m['claims']} for m in result['candidates']],'accepted_ids':actual,'answer_status':result['answer_status'],'answer_uncertainty':result['answer_uncertainty'],'contested':result.get('contested',False),'live_state_asserted':result['live_state_asserted'],'current_world_state':result['current_world_state'],'hits':[{'episode_id':reverse2[m['memory_id']],'revision':m['revision'],'summary':m['summary'],'claims':m['claims'],'contested_with':[reverse2[x] for x in m['contested_with']],'evidence_ids':[e['event_id'] for e in m['evidence']]} for m in result['hits']],'strict_pass':not failures,'failures':failures,'adapter_safety_pass':not result['hits'] and result['answer_status']=='unknown' if mapping_row['adapter_confidence']=='underdetermined' else None,'restart':restart,'expired_count':len(expired2),'v01_raw_ranked_ids':[e for _,e in rank[:5]],'v01_raw_scores':[s for s,_ in rank[:5]],'v01_accepted_ids':accepted1,'v01_setup_errors':baseline_errors,'v02_integrity':v2.db.execute('PRAGMA integrity_check').fetchone()[0],'v02_foreign_keys':[list(r) for r in v2.db.execute('PRAGMA foreign_key_check')]}
   output.append(row)
  finally:v2.close();v1.close()
 evidence={'kind':'GREGORY_MEMORY_V02_INDEPENDENT_CASE_REPLAY','fixture_sha256':digest(args.fixtures),'contract_map_sha256':digest(args.contracts),'capture_sha256':digest(args.capture),'baseline_gate_frozen_from_v01_benchmark':BASELINE_GATE,'scope':'synthetic scenario-scoped typed-contract prototype; not a general NL parser, not production','cases':output,'strict_passed':sum(x['strict_pass'] for x in output),'strict_total':len(output),'live_state_violations':sum(x['live_state_asserted'] for x in output),'failures':[{'id':x['case_id'],'accepted_ids':x['accepted_ids'],'failures':x['failures']} for x in output if not x['strict_pass']]}
 save(args.out/'GREGORY_MEMORY_V02_EVIDENCE.json',evidence);print(json.dumps({k:v for k,v in evidence.items() if k!='cases'},indent=2))
if __name__=='__main__':main()
