"""Read local mounted spawn-menu catalog; never invent executable item IDs."""
import json
import time
from pathlib import Path

class Catalog:
    def __init__(self, path):
        self.path = Path(path)
        self.cursor = 0

    def observations(self, state, wall=None):
        """Observed events, not inferred success or a grant of permission to spawn."""
        wall = time.time() if wall is None else wall
        result = {'spawns': [], 'undos': []}
        try:
            started = float(str(state['bridgeSession']).split(':',1)[0])
        except (KeyError,ValueError,TypeError):
            return result
        for filename, group in [('spawn_events.json','spawns'),('undo_events.json','undos')]:
            try:
                with (self.path.parent/filename).open('rb') as stream:raw=stream.read(128001)
                if len(raw)>128000:continue
                rows=json.loads(raw)
                if not isinstance(rows,list):continue
                for row in rows[-128:]:
                    if not isinstance(row,dict):continue
                    if row.get('steamid')!=state.get('steamid') or row.get('map')!=state.get('map'):continue
                    stamp=float(row.get('time',0))
                    if stamp<started or not 0<=wall-stamp<=300:continue
                    result[group].append({k:row[k] for k in ('kind','entity','class','model','time','removedTime','name')if k in row})
                result[group]=result[group][-6:]
            except (OSError,ValueError,TypeError,KeyError):pass
        return result

    def entries(self, state, wall=None):
        wall = time.time() if wall is None else wall
        try:
            with self.path.open('rb') as stream:raw=stream.read(8_000_001)
            if len(raw)>8_000_000:return [],{}
            doc=json.loads(raw)
            if doc.get('version')!=1 or doc.get('map')!=state.get('map') or doc.get('bridgeSession')!=state.get('bridgeSession'):return [],{}
            if not 0<=wall-float(doc['generated'])<=90:return [],{}
            out=[]
            for entry in doc.get('entries',[])[:50000]:
                if not isinstance(entry,dict):continue
                kind,key=entry.get('kind'),entry.get('key')
                if kind not in {'prop','npc','entity','weapon','vehicle'} or not isinstance(key,str):continue
                if entry.get('id')!=kind+':'+key or len(key)>240 or any(c in key for c in '\r\n;'):continue
                out.append({k:str(entry.get(k,''))[:300] for k in ('id','kind','key','name','category')})
            return out,doc
        except (OSError,ValueError,TypeError,KeyError,AttributeError):return [],{}

    def choices(self, state, wall=None, query='', kind=''):
        entries,_=self.entries(state,wall)
        if query or kind:
            terms=query.casefold().split()
            return [e for e in entries if (not kind or e['kind']==kind) and all(t in (' '.join(e.values())).casefold() for t in terms)][:18]
        groups={}
        for e in entries:groups.setdefault(e['kind'],[]).append(e)
        selected=[]
        for group in groups.values():selected.extend(group[(self.cursor+i)%len(group)]for i in range(min(4,len(group))))
        self.cursor+=4
        return selected

    def describe(self,state):
        entries,doc=self.entries(state)
        groups={}
        for e in entries:
            key=(e['kind'],e['category']);groups[key]=groups.get(key,0)+1
        return {'count':len(entries),'total':doc.get('total',len(entries)),
            'truncated':bool(doc.get('truncated')),
            'categories':[{'kind':k,'category':c,'count':n}for(k,c),n in sorted(groups.items())][:80],
            'addons':[str(a.get('name',''))[:120]for a in doc.get('addons',[])[:80]if isinstance(a,dict)]}
