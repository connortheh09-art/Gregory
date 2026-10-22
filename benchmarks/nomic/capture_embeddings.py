"""Capture synthetic HTTP embeddings; no server changes or foreign unloads."""
from pathlib import Path
import argparse,ctypes,gzip,hashlib,json,math,subprocess,sys,time,traceback
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'sdk314'))
import lmstudio
from urllib.request import Request,urlopen
MODELS={'v15':('nomic-ai/nomic-embed-text-v1.5-GGUF/nomic-embed-text-v1.5.Q4_K_M.gguf','d4e388894e09cf3816e8b0896d81d265b55e7a9fff9ab03fe8bf4ef5e11295ac'), 'v2':('ggml-org/Nomic-Embed-Text-V2-GGUF/nomic-embed-text-v2-moe-q8_0.gguf','36c5817bc25f379e62021f49efde05b10ed3b0c93ab8059c43173a7a5de73565')}
def http(path,data=None):
 req=Request('http://127.0.0.1:1234'+path,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json'})
 with urlopen(req,timeout=90) as r:return json.load(r)
def loaded():return [dict(key=m['key'],instances=m['loaded_instances']) for m in http('/api/v1/models')['models'] if m.get('loaded_instances')]
def resources():
 class Status(ctypes.Structure):
  _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(n,ctypes.c_ulonglong) for n in ['total_phys','avail_phys','total_page','avail_page','total_virtual','avail_virtual','avail_extended']]
 s=Status();s.length=ctypes.sizeof(s);ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
 return {'gpu_total_used_free_util_mib':subprocess.check_output(['nvidia-smi','--query-gpu=memory.total,memory.used,memory.free,utilization.gpu','--format=csv,noheader,nounits'],text=True).strip(),'ram_available_bytes':s.avail_phys,'ram_total_bytes':s.total_phys}
def main():
 p=argparse.ArgumentParser();p.add_argument('model',choices=MODELS);args=p.parse_args();name=args.model
 fixture_data=(ROOT/'fixtures.json').read_bytes();f=json.loads(fixture_data)
 if hashlib.sha256(fixture_data).hexdigest()!='c9a72a8c9befc331d71c50f7104731e259d7bed8473fb05cbe5d0e36885f3dbf':raise RuntimeError('fixture freeze mismatch')
 docs=sorted({e[k] for e in f['episodes'] for k in ['summary','before_summary']})
 result={'kind':'LOCAL_HTTP_EMBEDDING_CAPTURE','name':name,'utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'fixture_sha256':hashlib.sha256(fixture_data).hexdigest(),'python':sys.version,'sdk_version':'1.5.0','http_base':'127.0.0.1:1234','initial_loaded':loaded(),'resources_before':resources(),'documents':[],'queries':[],'samples':[],'conditions':'CPU-only; serial requests; single-prefix; one document pass; 3 full query passes; warmed after prefix probe; no cold-start claims'}
 if result['initial_loaded']:raise RuntimeError('existing model loaded; abort before load')
 if result['resources_before']['ram_available_bytes']<6*1024**3:raise RuntimeError('RAM gate <6GiB')
 path,sha=MODELS[name];ident='gregory-nomic-measure-'+name+'-cpu';model=None
 try:
  with lmstudio.Client(api_host='127.0.0.1:41343') as c:
   t=time.perf_counter();model=c.embedding.load_new_instance(path,instance_identifier=ident,config={'gpu':{'ratio':0},'contextLength':512},ttl=600);result['load_seconds']=time.perf_counter()-t
   result['info']=model.get_info().to_dict();result['load_config']=model.get_load_config().to_dict();result['gguf_sha256']=sha
   if result['info']['path'].replace('\\','/')!=path or result['load_config']['gpu']['ratio']!=0:raise RuntimeError('exact local CPU load gate')
   result['resources_loaded']=resources()
   def encode(text):
    if len(text.encode('ascii'))>400:raise RuntimeError('primary input byte cap')
    tokens=list(model.tokenize(text))
    if len(tokens)>512:raise RuntimeError('actual token cap')
    start=time.perf_counter();r=http('/v1/embeddings',{'model':ident,'input':text,'encoding_format':'float'});elapsed=time.perf_counter()-start
    v=r['data'][0]['embedding']
    if len(v)!=768 or not all(math.isfinite(x) for x in v) or not math.hypot(*v):raise RuntimeError('invalid full vector')
    return {'input':text,'token_count':len(tokens),'vector':v,'seconds':elapsed,'usage':r.get('usage'),'response_model':r.get('model')}
   start=time.perf_counter()
   for i,doc in enumerate(docs):
    if i%20==0:
     if any(x['instances'][0]['id']!=ident for x in loaded()):raise RuntimeError('foreign model detected')
     result['samples'].append(resources())
    result['documents'].append(encode('search_document: '+doc))
   result['document_encoding_wall_seconds']=time.perf_counter()-start
   byq={q['id']:{'id':q['id'],'input':'search_query: '+q['query'],'seconds':[],'usages':[],'repeat_vector_max_abs_delta':[]} for q in f['queries']}
   for repeat in range(f['repeats']):
    for q in f['queries']:
     row=byq[q['id']];v=encode(row['input']);row['seconds'].append(v['seconds']);row['usages'].append(v['usage']);row['token_count']=v['token_count']
     if repeat==0:row['vector']=v['vector']
     else:row['repeat_vector_max_abs_delta'].append(max(abs(a-b) for a,b in zip(row['vector'],v['vector'])))
    result['samples'].append(resources())
   result['queries']=list(byq.values());result['resources_encoded']=resources();result['status']='TESTED'
   model.unload();model=None;result['own_instance_unloaded']=True
 except Exception:result['error']=traceback.format_exc()
 finally:
  # Only this unique benchmark handle can be unloaded.
  if model is not None:
   try:model.unload();result['own_instance_unloaded']=True
   except Exception:result['unload_error']=traceback.format_exc()
  result['final_loaded']=loaded();result['resources_after']=resources()
  data=json.dumps(result,separators=(',',':')).encode();(ROOT/('CAPTURE_'+name+'.json.gz')).write_bytes(gzip.compress(data,mtime=0))
  print(json.dumps({k:v for k,v in result.items() if k not in ['documents','queries','samples']}))
 if 'error' in result:raise SystemExit(1)
if __name__=='__main__':main()
