"""Freeze new developer inputs and literal semantic spans before model measurements."""
from pathlib import Path
import hashlib,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from gregory_core.memory_v02 import views
ROOT=Path(__file__).resolve().parent
DEV=[
 ('T01','I tried wheeling a cart through a narrow hatch. The wheels snagged. I unloaded the cart and carried the crates through separately.','How did you deliver the supplies when the vehicle would not fit?'),
 ('T02','A library shelf label had washed away. I matched the book spines to the catalog and rebuilt the label.','What helped you restore the order after the identifiers disappeared?'),
 ('T03','I tuned a receiver but heard only static. I changed its frequency and heard the beacon clearly.','Was there a time a small adjustment made the message intelligible?'),
 ('T04','I carried a watering can with a leaking seam. I put the seedlings in a tray and watered them there instead.','How did you save the plants when the container could not hold its contents?'),
 ('T05','I tried opening a painted handle. It was scenery, not a usable control. I stopped pulling it.','When did an apparently useful part turn out to be decorative?'),
 ('T06','I attempted a recipe but the oven lost power. The batter never baked.','Which meal stayed unfinished because the equipment stopped working?'),
 ('T07','I sent a request to reserve a seat. No confirmation arrived and I do not know whether it was reserved.','Did submitting the booking definitely secure a place?'),
 ('T08','A storyteller invented a robot who liked violet tea. No real person expressed that preference.','What does the real owner like to drink?'),
 ('T09','An amber indicator lit on the console. I recorded its color but never learned what it signified.','Does that signal prove the engine was overheating?'),
 ('T10','I found a spiral shell in a locked display. A curator called it a replica, but no inspection confirmed the material.','Was that object genuinely ancient?'),
 ('T11','I sorted parcels by destination. A smeared address forced me to put one parcel aside rather than guess.','When did you avoid sending something to an unsupported destination?'),
 ('T12','I took measurements of an empty storage bin. It was twenty centimeters deep.','How far down did that receptacle extend?')]
def main():
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--independent',type=Path,required=True);p.add_argument('--original',type=Path,required=True);p.add_argument('--old-benchmark',type=Path,required=True);args=p.parse_args()
 independent=json.loads(args.independent.read_text());original=json.loads(args.original.read_text());old=json.loads(args.old_benchmark.read_text());narratives={e['id']:e['claim'] for s in original['scenarios'] for e in s['episodes']}
 documents=set();queries=set()
 for _,text,q in DEV:documents.update(views(text));queries.add(q)
 for s in independent['scenarios']:
  for e in s['episodes']:
   text=e.get('correction_text',narratives[e['id']]);documents.update(views(text));documents.update(views(narratives[e['id']]))
 for q in independent['cases']:queries.add(q['query'])
 for e in old['episodes']:
  if e['lifecycle'] not in ['forget','expire']:documents.update(views(e['summary']))
 queries.add('Remember when you had trouble following me?')
 data={'schema':'gregory.memory.v02.embedding-inputs.v1','method':'full narrative plus first three exact sentence spans; per-episode maximum cosine; no keyword fusion, learned gate, query rewriting, aliases or additional models','independent_sha256':hashlib.sha256(args.independent.read_bytes()).hexdigest(),'synthetic_only':True,'documents':sorted(documents),'queries':sorted(queries),'dev':[{'id':i,'summary':d,'query':q} for i,d,q in DEV]}
 encoded=json.dumps(data,indent=2)+'\n';(ROOT/'INPUTS.json').write_text(encoded);print(len(documents),len(queries),hashlib.sha256(encoded.encode()).hexdigest())
if __name__=='__main__':main()
