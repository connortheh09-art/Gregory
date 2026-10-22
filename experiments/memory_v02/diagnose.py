"""Read-only cached-vector diagnostics; never recalibrate a gate or call a model."""
from pathlib import Path
import argparse,gzip,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from gregory_core.embeddings import unit_vector
from gregory_core.memory_v02 import views
def read(p):return json.loads(gzip.decompress(p.read_bytes())) if p.suffix=='.gz' else json.loads(p.read_text())
def bank(capture):return {x['input']:unit_vector(x['vector'],768) for x in capture['documents']+capture['queries']}
def rank(episodes,query,vectors,spans=False):
 q=vectors['search_query: '+query]
 return sorted([(max(sum(a*b for a,b in zip(q,vectors['search_document: '+text])) for text in (views(e['summary']) if spans else [e['summary']])),e['id']) for e in episodes],key=lambda x:(-x[0],x[1]))
def main():
 p=argparse.ArgumentParser();p.add_argument('--original-fixture',type=Path,required=True);p.add_argument('--original-capture',type=Path,required=True);p.add_argument('--capture',type=Path,required=True);p.add_argument('--inputs',type=Path,default=Path(__file__).with_name('INPUTS.json'));p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 old,original,new,inputs=map(read,[a.original_fixture,a.original_capture,a.capture,a.inputs]);before,after=bank(original),bank(new);assert original['gguf_sha256']==new['gguf_sha256'] and original['load_config']==new['load_config'];after={**before,**after}
 query=next(q for q in old['queries'] if q['id']=='Q068');episodes=[e for e in old['episodes'] if e['lifecycle'] not in ('forget','expire') and e['domain']==query['filters']['domain']];base=rank(episodes,query['query'],before);candidate=rank(episodes,query['query'],after,True)
 result={'q068':{'baseline_rank':[x[1] for x in base].index('E001')+1,'candidate_rank':[x[1] for x in candidate].index('E001')+1,'baseline_top5':base[:5],'candidate_top5':candidate[:5]},'dev':[]}
 for dev in inputs['dev']:
  b=rank(inputs['dev'],dev['query'],after);c=rank(inputs['dev'],dev['query'],after,True);result['dev'].append({'id':dev['id'],'baseline_rank':[x[1] for x in b].index(dev['id'])+1,'candidate_rank':[x[1] for x in c].index(dev['id'])+1})
 a.out.write_text(json.dumps(result,indent=2)+'\n');print('Q068',result['q068']['baseline_rank'],'->',result['q068']['candidate_rank'],'; new developer top1',sum(x['baseline_rank']==1 for x in result['dev']),'->',sum(x['candidate_rank']==1 for x in result['dev']))
if __name__=='__main__':main()
