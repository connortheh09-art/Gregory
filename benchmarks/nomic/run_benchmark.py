"""Reproducible offline replay of captured real embeddings and MemoryStore indexes.

Never calls a model or changes the v0.1 core. Calibration writes before test labels
are scored. Output paths must be new, so a result cannot be silently overwritten.
"""
from pathlib import Path
import argparse,gzip,hashlib,json,math,re,sqlite3,statistics,sys,time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from gregory_core.memory import MemoryStore,canonical,project_event
from gregory_core.embeddings import LocalNomic,unit_vector
ACTOR='synthetic-benchmark-owner'
CONFIGS=['fts5','semantic-v15','semantic-v2','hybrid-v15','hybrid-v2']
def sha(data):return hashlib.sha256(data).hexdigest()
def save(path,data):path.write_text(json.dumps(data,indent=2,ensure_ascii=True)+'\n',encoding='utf-8')
def percentile_summary(values):
 return {'count':len(values),'median_ms':statistics.median(values)*1000,'max_ms':max(values)*1000} if values else None

def prepare(f,path,captures):
 clock=[f['clock_before']];store=MemoryStore(path,owner_id=ACTOR,retention_seconds=f['retention_seconds'],clock=lambda:clock[0])
 try:
  ids={};derivations={}
  for e in f['episodes']:
   store.ingest(e['events'],actor=ACTOR,source_label='synthetic-fixture-v2')
   key=store.consolidate(e['run_id'],e['correlation_id'],actor=ACTOR,domain=e['domain']);ids[e['id']]=key
   original=store.inspect(key,actor=ACTOR);claims=original['claims'];outcome=next((c['text'] for c in claims if c['text'].startswith('Outcome:')),None)
   # Keep derived claims before attaching curated reported text; independently auditable.
   derivations[e['id']]={'claims':claims,'uncertainty':original['uncertainty'],'declared_outcome':e['outcome']}
   if e['outcome']=='unknown':assert 'outcome_not_established' in original['uncertainty']
   else:assert any(c['kind']=='inferred' and ('successful' if e['outcome']=='succeeded' else 'failed') in c['text'] for c in claims)
   store.correct(key,e['before_summary'],actor=ACTOR,reason='fixture-authored synthetic narrative; retrieval benchmark only')
  encoders={};index_times={}
  for name,cap in captures.items():
   vectors={r['input']:r['vector'] for r in cap['documents']}
   def encode(texts,cache=vectors):return [cache[t] for t in texts]
   config=cap['load_config'];revision=sha(canonical({'gguf':cap['gguf_sha256'],'config':config,'server':'LM Studio 0.4.22.0','prefixes':['search_document: ','search_query: ']}).encode())
   embed=LocalNomic(encode,revision=revision,model='nomic-ai/nomic-embed-text-v1.5' if name=='v15' else 'nomic-ai/nomic-embed-text-v2-moe');encoders[name]=embed
   t=time.perf_counter()
   for key in ids.values():store.index(key,embed,actor=ACTOR)
   index_times[name]={'initial_67_index_seconds':time.perf_counter()-t,'space_key':embed.space.key,'space':embed.space.__dict__}
  before={e['id']:store.inspect(ids[e['id']],actor=ACTOR) for e in f['episodes'] if e['lifecycle']!='retain'}
  before_retrieval={e:store.search(m['summary'],actor=ACTOR,limit=5)['hits'] for e,m in before.items()}
  before_vectors={e:store.db.execute('SELECT count(*) FROM vectors WHERE memory_id=?',(ids[e],)).fetchone()[0] for e in before}
  corrections=[];forgotten=[]
  for e in f['episodes']:
   if e['lifecycle']=='correct':
    store.correct(ids[e['id']],e['summary'],actor=ACTOR,reason='synthetic correction lifecycle probe')
    assert store.db.execute('SELECT count(*) FROM vectors WHERE memory_id=?',(ids[e['id']],)).fetchone()[0]==0
    assert store.db.execute('SELECT summary FROM memory_fts WHERE memory_id=?',(ids[e['id']],)).fetchone()[0]==e['summary']
    corrections.append(e['id'])
   elif e['lifecycle']=='forget':store.forget(ids[e['id']],actor=ACTOR);forgotten.append(e['id'])
  clock[0]=f['clock_after'];expired_count=store.expire(actor=ACTOR)
  expired=sorted(e['id'] for e in f['episodes'] if e['lifecycle']=='expire' and store.inspect(ids[e['id']],actor=ACTOR) is None)
  assert expired_count==3 and expired==['E061','E062','E066'], 'EXACT EXPIRY ABORT GATE'
  assert sorted(forgotten)==['E063','E064','E067'], 'EXACT FORGET ABORT GATE'
  for e in f['episodes']:
   m=store.inspect(ids[e['id']],actor=ACTOR)
   if e['lifecycle'] in ('forget','expire'):
    assert m is None
    for table in ['memory_fts','vectors','revisions','citations']:assert store.db.execute('SELECT count(*) FROM '+table+' WHERE memory_id=?',(ids[e['id']],)).fetchone()[0]==0
   else:assert m and m['summary']==e['summary'] and not m['expired']
  for name,embed in encoders.items():
   t=time.perf_counter()
   for e in corrections:store.index(ids[e],embed,actor=ACTOR)
   index_times[name]['corrected_3_reindex_seconds']=time.perf_counter()-t
  active={e['id']:store.inspect(ids[e['id']],actor=ACTOR) for e in f['episodes'] if store.inspect(ids[e['id']],actor=ACTOR)}
  assert len(active)==61
  for q in f['queries']:
   for eid in q['expected_ids']:
    assert eid in active and all(active[eid][k]==v for k,v in q['filters'].items()),'unreachable expected label'
  # All envelope hashes come from actual ingest(), not invented fixture hash fields.
  originals={ev['event_id']:project_event(ev)['envelope_sha256'] for e in f['episodes'] for ev in e['events']}
  for m in active.values():
   assert m['evidence'] and m['historical_only'] and m['current_world_state'].startswith('unknown')
   for ev in m['evidence']:assert ev['envelope_sha256']==originals[ev['event_id']]
  after_retrieval={e:store.search(m['summary'],actor=ACTOR,limit=5)['hits'] for e,m in before.items()}
  lifecycle={'before_retrieval':{e:[m['memory_id'] for m in hits] for e,hits in before_retrieval.items()},'after_retrieval_of_old_text':{e:[m['memory_id'] for m in hits] for e,hits in after_retrieval.items()},'retention_seconds':f['retention_seconds'],'clock_before':f['clock_before'],'clock_after':f['clock_after'],'expired':expired,'forgotten':forgotten,'corrected':corrections,'active_count':len(active),'before':before,'before_vector_counts':before_vectors,'after':{e:store.inspect(ids[e],actor=ACTOR) for e in before},'derived_claims_before_curation':derivations,'index_build':index_times,'foreign_key_check':list(store.db.execute('PRAGMA foreign_key_check')),'integrity':store.db.execute('PRAGMA integrity_check').fetchone()[0]}
  return store,ids,active,lifecycle,encoders
 except BaseException:
  store.close()
  raise

def lanes(store,ids,active,q,queryvector=None,space_key=None):
 rev={v:k for k,v in ids.items()};where='(m.expires IS NULL OR m.expires>?)';params=[store.clock()]
 for k,v in q['filters'].items():
  assert k in ('domain','session_id');where+=' AND m.'+k+'=?';params.append(v)
 eligible=sorted(e for e,m in active.items() if all(m[k]==v for k,v in q['filters'].items()))
 words=re.findall(r'[^\W_]+',q['query'],re.UNICODE)[:32];match=' OR '.join('"'+w+'"' for w in words)
 lexical=[]
 if match:
  lexical=[(rev[r[0]],-r[1]) for r in store.db.execute('SELECT m.memory_id,bm25(memory_fts) FROM memory_fts JOIN memories m USING(memory_id) WHERE memory_fts MATCH ? AND '+where+' ORDER BY bm25(memory_fts),m.memory_id LIMIT 100',[match,*params])]
 semantic=[]
 if queryvector is not None:
  for row in store.db.execute('SELECT v.memory_id,v.vector FROM vectors v JOIN memories m USING(memory_id) WHERE v.space_key=? AND '+where,[space_key,*params]):
   vector=unit_vector(json.loads(row[1]),768);score=sum(x*y for x,y in zip(queryvector,vector))
   if score>0:semantic.append((rev[row[0]],score))
  semantic.sort(key=lambda x:(-x[1],ids[x[0]]));semantic=semantic[:100]
 return eligible,lexical,semantic

def rank(store,ids,active,q,config,captures,encoders):
 name=config.rsplit('-',1)[-1] if config!='fts5' else None
 vec=None if name is None else unit_vector(next(r['vector'] for r in captures[name]['queries'] if r['id']==q['id']),768)
 eligible,lexical,semantic=lanes(store,ids,active,q,vec,None if name is None else encoders[name].space.key)
 if config=='fts5':ranking=lexical;gate=lexical[0][1] if lexical else 0.
 elif config.startswith('semantic'):ranking=semantic;gate=semantic[0][1] if semantic else 0.
 else:
  fused={}
  for lane in [lexical,semantic]:
   for n,(eid,_) in enumerate(lane,1):fused[eid]=fused.get(eid,0)+1/(60+n)
  ranking=sorted(fused.items(),key=lambda x:(-x[1],ids[x[0]]));gate=semantic[0][1] if semantic else 0.
 return {'ranked_ids':[e for e,_ in ranking[:5]],'ranking_scores':[s for _,s in ranking[:5]],'gate_score':gate,'eligible_ids':eligible}

def fit_threshold(rows):
 assert rows and all(r['split']=='dev' for r in rows)
 positive=[r for r in rows if r['expected_ids']];negative=[r for r in rows if not r['expected_ids']]
 assert positive and negative
 scores=[r['gate_score'] for r in rows];candidates=sorted({0.,*scores,math.nextafter(max(scores),math.inf)})
 scored=[]
 for t in candidates:
  tp=sum(r['gate_score']>=t and bool(r['ranked_ids']) for r in positive)/len(positive)
  tn=sum(not(r['gate_score']>=t and bool(r['ranked_ids'])) for r in negative)/len(negative)
  scored.append(((tp+tn)/2,t))
 score,threshold=max(scored)
 return {'threshold':threshold,'balanced_dev_answerability_accuracy':score,'dev_supported_count':len(positive),'dev_no_evidence_count':len(negative),'candidate_thresholds':candidates,'tie_rule':'highest threshold (conservative)'}

def aggregate(rows):
 supported=[r for r in rows if r['expected_ids'] and r.get('retrieval_scored',True)]
 negative=[r for r in rows if not r['expected_ids'] and r['class_name']!='historical_state_assertion']
 def recall(k):return sum(len(set(r['expected_ids'])&set(r['retrieved_ids'][:k]))/len(set(r['expected_ids'])) for r in supported)/len(supported) if supported else None
 reciprocal=[]
 for r in supported:reciprocal.append(next((1/i for i,e in enumerate(r['retrieved_ids'],1) if e in r['expected_ids']),0))
 return {'supported_count':len(supported),'no_evidence_count':len(negative),'recall@1':recall(1),'recall@3':recall(3),'recall@5':recall(5),'MRR':sum(reciprocal)/len(reciprocal) if reciprocal else None,'false_retrieval_count':sum(bool(r['retrieved_ids']) for r in negative),'false_retrieval_rate':sum(bool(r['retrieved_ids']) for r in negative)/len(negative) if negative else None,'false_abstention_count':sum(not r['retrieved_ids'] for r in supported),'false_abstention_rate':sum(not r['retrieved_ids'] for r in supported)/len(supported) if supported else None,'incorrect_match_count':sum(len(r['wrong_ids']) for r in rows if r.get('retrieval_scored',True)),'live_state_violations':sum(not r['historical_only'] or not r['current_world_state'].startswith('unknown') for r in rows),'retrieval_latency':percentile_summary([t for r in rows for t in r['retrieval_seconds']]),'embedding_latency':percentile_summary([t for r in rows for t in r['embedding_seconds']])}

def main():
 p=argparse.ArgumentParser();p.add_argument('--captures',type=Path,required=True);p.add_argument('--out',type=Path,required=True);args=p.parse_args();args.out.mkdir(parents=True,exist_ok=False)
 fpath=Path(__file__).with_name('fixtures.json');fdata=fpath.read_bytes();f=json.loads(fdata);freeze=json.loads(fpath.with_name('FREEZE.json').read_text())
 assert sha(fdata)=='c9a72a8c9befc331d71c50f7104731e259d7bed8473fb05cbe5d0e36885f3dbf'
 captures={name:json.loads(gzip.decompress((args.captures/('CAPTURE_'+name+'.json.gz')).read_bytes())) for name in ['v15','v2']}
 for name,cap in captures.items():
  assert cap['status']=='TESTED' and cap['fixture_sha256']==sha(fdata) and cap['own_instance_unloaded'] and not cap['initial_loaded'] and not cap['final_loaded']
  assert len(cap['documents'])==70 and len(cap['queries'])==99
  assert all(len(r['vector'])==768 and r['token_count']<=512 for r in [*cap['documents'],*cap['queries']])
  assert all(len(r['seconds'])==3 for r in cap['queries'])
 started=time.perf_counter();store,ids,active,lifecycle,encoders=prepare(f,args.out/'memory.sqlite',captures);construction=time.perf_counter()-started
 try:
  save(args.out/'LIFECYCLE.json',lifecycle);save(args.out/'MEMORY_CATALOG.json',active)
  devrows=[];calibrations={}
  for config in CONFIGS:
   rows=[]
   for q in f['queries']:
    if q['split']=='dev':rows.append(dict(q,config=config,**rank(store,ids,active,q,config,captures,encoders)))
   devrows.extend(rows)
   if config.startswith('hybrid'):calibrations[config]=calibrations['semantic-'+config.rsplit('-',1)[-1]]
   else:calibrations[config]=fit_threshold(rows)
  # Durable dev file exists before the held-out scoring loop runs.
  save(args.out/'DEV_CALIBRATION.json',{'utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'fixture_sha256':sha(fdata),'calibrations':calibrations,'rows':devrows})
  rows=[]
  for config in CONFIGS:
   for q in f['queries']:
    timings=[];ranks=[]
    for repeat in range(f['repeats']):
     start=time.perf_counter();r=rank(store,ids,active,q,config,captures,encoders);ranks.append(r)
     threshold=calibrations[config]['threshold'];accepted=r['ranked_ids'] if r['gate_score']>=threshold else []
     hits=[store.inspect(ids[e],actor=ACTOR) for e in accepted]
     timings.append(time.perf_counter()-start)
    assert all(r==ranks[0] for r in ranks)
    embedding=[] if config=='fts5' else next(r['seconds'] for r in captures[config.rsplit('-',1)[-1]]['queries'] if r['id']==q['id'])
    row=dict(q,config=config,**ranks[0],retrieved_ids=accepted,threshold=threshold,abstained=not accepted,retrieval_seconds=timings,embedding_seconds=embedding,historical_only=True,current_world_state='unknown; requires fresh adapter observations',wrong_ids=[e for e in accepted if e not in q['expected_ids']],missed_ids=[e for e in q['expected_ids'] if e not in accepted],hits=[{'episode_id':e,'memory_id':m['memory_id'],'summary':m['summary'],'revision':m['revision'],'claims':m['claims'],'uncertainty':m['uncertainty'],'event_ids':[x['event_id'] for x in m['evidence']],'historical_only':m['historical_only'],'current_world_state':m['current_world_state']} for e,m in zip(accepted,hits)])
    rows.append(row)
  for q in f['queries']:
   assert len({tuple(r['eligible_ids']) for r in rows if r['id']==q['id']})==1
  metrics={}
  for config in CONFIGS:
   selected=[r for r in rows if r['config']==config and r['split']=='test'];metrics[config]=aggregate(selected)
   metrics[config]['slices']={tag:aggregate([r for r in selected if tag in r['tags']]) for tag in sorted({t for r in selected for t in r['tags']})}
  result={'kind':'GREGORY_NOMIC_BENCHMARK_MEASURED','fixture_sha256':sha(fdata),'dev_queries':f['dev_queries'],'test_queries':f['test_queries'],'k':5,'corpus_count':61,'corpus_sha256':sha(canonical({e:m['summary'] for e,m in active.items()}).encode()),'scope':'retrieval over curated evidence-linked reported narratives, not consolidation quality','calibration_file_sha256':sha((args.out/'DEV_CALIBRATION.json').read_bytes()),'runtime':{'python':sys.version,'sqlite':sqlite3.sqlite_version,'sqlite_source_id':store.db.execute('SELECT sqlite_source_id()').fetchone()[0]},'construction_seconds_excluding_embedding':construction,'metrics':metrics,'per_query':rows,'source_models':{name:{k:v for k,v in cap.items() if k not in ['documents','queries']} for name,cap in captures.items()},'historical_assertion_scope':'typed historical MemoryStore envelopes only; no language generator or live adapter exercised'}
  save(args.out/'GREGORY_NOMIC_BENCHMARK_EVIDENCE.json',result)
  print(json.dumps({c:{k:v for k,v in m.items() if k!='slices'} for c,m in metrics.items()},indent=2))
 finally:store.close()
if __name__=='__main__':main()
