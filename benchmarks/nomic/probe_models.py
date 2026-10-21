"""Bounded local-only CPU probe. Never unloads a pre-existing model."""
from pathlib import Path
import hashlib,json,sys,time,urllib.request,subprocess,math,traceback
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'sdk314'))
import lmstudio
MODELS=[('v15','nomic-ai/nomic-embed-text-v1.5-GGUF/nomic-embed-text-v1.5.Q4_K_M.gguf'),('v2','ggml-org/Nomic-Embed-Text-V2-GGUF/nomic-embed-text-v2-moe-q8_0.gguf')]
def http(path,data=None):
 req=urllib.request.Request('http://127.0.0.1:1234'+path,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=90) as r:return json.load(r)
def loaded():return [dict(key=m['key'],instances=m['loaded_instances']) for m in http('/api/v1/models')['models'] if m.get('loaded_instances')]
def resources():
 return {'gpu':subprocess.check_output(['nvidia-smi','--query-gpu=memory.total,memory.used,memory.free,utilization.gpu','--format=csv,noheader,nounits'],text=True).strip()}
def cosine(a,b):return sum(x*y for x,y in zip(a,b))/math.hypot(*a)/math.hypot(*b)
result={'kind':'LOCAL_CPU_PREFIX_PROBE','started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'initial_loaded':loaded(),'resources_before':resources(),'models':[]}
if result['initial_loaded']:raise SystemExit('ABORT: existing model instance; no load attempted')
try:
 with lmstudio.Client(api_host='127.0.0.1:41343') as c:
  for name,path in MODELS:
   if loaded():raise RuntimeError('foreign model loaded; stopping')
   ident='gregory-nomic-benchmark-'+name+'-cpu'
   row={'name':name,'requested_path':path,'identifier':ident};result['models'].append(row)
   model=None
   try:
    started=time.perf_counter()
    model=c.embedding.load_new_instance(path,instance_identifier=ident,config={'gpu':{'ratio':0},'contextLength':512},ttl=600)
    row['load_seconds']=time.perf_counter()-started
    row['info']=model.get_info().to_dict();row['load_config']=model.get_load_config().to_dict()
    if row['info']['path'].replace('\\','/')!=path:raise RuntimeError('loaded path is not exact local path')
    if row['load_config'].get('gpu',{}).get('ratio')!=0:raise RuntimeError('CPU offload configuration not confirmed')
    row['resources_loaded']=resources();row['context_length']=model.get_context_length()
    base='A synthetic robot recovered after stumbling at a low ledge.'
    texts=[base,'search_query: '+base,'search_document: '+base,'search_query: search_query: '+base,'search_document: search_document: '+base]
    row['probes']=[]
    for text in texts:
     tok=list(model.tokenize(text));native=list(model.embed(text));response=http('/v1/embeddings',{'model':ident,'input':text,'encoding_format':'float'})
     vec=response['data'][0]['embedding']
     if len(vec)!=768:raise RuntimeError('not full 768 dimensions')
     row['probes'].append({'input':text,'token_ids':tok,'token_count':len(tok),'native_vector':native,'http_vector':vec,'http_usage':response.get('usage'),'sdk_http_cosine':cosine(native,vec),'max_abs_difference':max(abs(a-b) for a,b in zip(native,vec))})
    row['raw_vs_query_cosine']=cosine(row['probes'][0]['http_vector'],row['probes'][1]['http_vector'])
    row['query_vs_double_cosine']=cosine(row['probes'][1]['http_vector'],row['probes'][3]['http_vector'])
    row['status']='TESTED'
   finally:
    if model is not None:model.unload();row['own_instance_unloaded']=True
except Exception:
 result['error']=traceback.format_exc()
finally:
 result['final_loaded']=loaded();result['resources_after']=resources()
 (ROOT/'PREFIX_PROBE.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({k:v for k,v in result.items() if k!='models'}))
 for r in result['models']:print(json.dumps({k:v for k,v in r.items() if k!='probes'}))
if 'error' in result:raise SystemExit(1)
