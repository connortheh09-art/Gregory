"""CPU-only synthetic capture in the existing owner-approved qualification environment."""
from pathlib import Path
import gzip,hashlib,json,math,struct,sys,time,traceback
ROOT=Path(__file__).resolve().parent
SDKROOT=ROOT.parent/'nomic-benchmark-20261021'
sys.path.insert(0,str(SDKROOT/'sdk314'));sys.path.insert(0,str(SDKROOT))
import lmstudio
from capture_embeddings import http,loaded,resources,MODELS

def gguf_metadata(path):
 result={}
 with open(path,'rb') as stream:
  def read(fmt):return struct.unpack('<'+fmt,stream.read(struct.calcsize('<'+fmt)))[0]
  def string():return stream.read(read('Q')).decode('utf-8')
  def value(t,keep=True):
   formats={0:'B',1:'b',2:'H',3:'h',4:'I',5:'i',6:'f',7:'?',10:'Q',11:'q',12:'d'}
   if t in formats:return read(formats[t])
   if t==8:return string()
   if t==9:
    subtype,n=read('I'),read('Q')
    if subtype in formats:stream.seek(n*struct.calcsize('<'+formats[subtype]),1)
    else:
     for _ in range(n):value(subtype,False)
    return {'array_items':n,'type':subtype}
   raise ValueError('unknown GGUF metadata type')
  if stream.read(4)!=b'GGUF':raise ValueError('not GGUF')
  version=read('I');tensors,n=read('Q'),read('Q');result.update(version=version,tensors=tensors)
  for _ in range(n):
   key=string();v=value(read('I'))
   if any(x in key for x in ['pooling','embedding_length','architecture','general.name']):result[key]=v
 return result

def main():
 raw=(ROOT/'INPUTS.json').read_bytes();f=json.loads(raw);result={'kind':'GREGORY_MEMORY_V02_REAL_V15_CAPTURE','input_sha256':hashlib.sha256(raw).hexdigest(),'utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'python':sys.version,'initial_loaded':loaded(),'resources_before':resources(),'documents':[],'queries':[],'conditions':'serial CPU-only; exact local GGUF; 512context; full768; one document pass and 3querypasses; explicit single prefixes; no configuration changes'}
 if result['initial_loaded']:raise RuntimeError('ABORT existing model instance: no load attempted')
 if result['resources_before']['ram_available_bytes']<6*1024**3:raise RuntimeError('RAM gate')
 path,sha=MODELS['v15'];file=Path(r'C:\Users\Conman\.lmstudio\.internal\bundled-models')/path
 if hashlib.sha256(file.read_bytes()).hexdigest()!=sha:raise RuntimeError('GGUF changed')
 result['gguf_sha256']=sha;result['gguf_metadata']=gguf_metadata(file);model=None
 try:
  with lmstudio.Client(api_host='127.0.0.1:41343') as c:
   ident='gregory-memory-v02-v15-cpu';model=c.embedding.load_new_instance(path,instance_identifier=ident,config={'gpu':{'ratio':0},'contextLength':512},ttl=600)
   result['info']=model.get_info().to_dict();result['load_config']=model.get_load_config().to_dict()
   if result['info']['path'].replace('\\','/')!=path or result['load_config']['gpu']['ratio']!=0:raise RuntimeError('exact local CPU gate')
   result['resources_loaded']=resources()
   def encode(text):
    if text.startswith('search_document: search_document: ') or text.startswith('search_query: search_query: '):raise RuntimeError('double prefix')
    tokens=model.count_tokens(text)
    if tokens>512:raise RuntimeError('token gate')
    start=time.perf_counter();response=http('/v1/embeddings',{'model':ident,'input':text,'encoding_format':'float'});seconds=time.perf_counter()-start;v=response['data'][0]['embedding']
    if len(v)!=768 or not all(math.isfinite(x) for x in v) or not math.hypot(*v):raise RuntimeError('vector gate')
    return {'input':text,'token_count':tokens,'vector':v,'seconds':seconds,'usage':response.get('usage')}
   start=time.perf_counter()
   for i,text in enumerate(f['documents']):
    if i%25==0 and any(inst.get('id',inst.get('identifier'))!=ident for m in loaded() for inst in m['instances']):raise RuntimeError('foreign model detected; stop')
    result['documents'].append(encode('search_document: '+text))
   result['document_wall_seconds']=time.perf_counter()-start
   result['queries']=[dict(input='search_query: '+text,seconds=[],repeat_deltas=[]) for text in f['queries']]
   for repeat in range(3):
    for row in result['queries']:
     r=encode(row['input']);row['seconds'].append(r['seconds']);row['token_count']=r['token_count']
     if repeat==0:row['vector']=r['vector']
     else:row['repeat_deltas'].append(max(abs(a-b) for a,b in zip(row['vector'],r['vector'])))
   result['resources_encoded']=resources();result['status']='TESTED';model.unload();model=None;result['own_instance_unloaded']=True
 except Exception:result['error']=traceback.format_exc()
 finally:
  if model is not None:model.unload();result['own_instance_unloaded']=True
  result['final_loaded']=loaded();result['resources_after']=resources();out=ROOT/'V02_CAPTURE.json.gz';out.write_bytes(gzip.compress(json.dumps(result,separators=(',',':')).encode(),mtime=0))
  print(json.dumps({k:v for k,v in result.items() if k not in ['documents','queries']}));print(json.dumps({'file':out.name,'bytes':out.stat().st_size,'sha256':hashlib.sha256(out.read_bytes()).hexdigest()}))
 if 'error' in result:raise SystemExit(1)
if __name__=='__main__':main()
