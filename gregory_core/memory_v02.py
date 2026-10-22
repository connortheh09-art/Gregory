"""Isolated v0.2: semantic candidates are not answers; historical evidence is not live state.

No migrations, network, model startup, generation, learned thresholds or keyword fusion.
Typed query contracts are supplied by callers; free-text candidates alone remain uncertain.
"""
from contextlib import closing
from pathlib import Path
import hashlib,json,math,re,sqlite3,time,uuid
from .memory import canonical,project_event,timestamp
from .embeddings import unit_vector
KIND='gregory.memory.v0.2'
GUARD={'historical_only':True,'live_state_asserted':False,'current_world_state':'unknown; requires fresh adapter observations'}
SCHEMA='''
CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE evidence(event_id TEXT PRIMARY KEY, envelope_sha256 TEXT NOT NULL, projection TEXT NOT NULL,
 source_instance_id TEXT NOT NULL,source_sequence INTEGER NOT NULL, claims TEXT NOT NULL,narrative TEXT,
 UNIQUE(source_instance_id,source_sequence));
CREATE TABLE episodes(memory_id TEXT PRIMARY KEY,run_id TEXT NOT NULL,correlation_id TEXT NOT NULL,
 session_id TEXT NOT NULL,domain TEXT NOT NULL,context TEXT NOT NULL,reality TEXT NOT NULL,
 occurred REAL NOT NULL,expires REAL NOT NULL,summary TEXT NOT NULL,revision INTEGER NOT NULL,
 UNIQUE(run_id,correlation_id));
CREATE TABLE citations(memory_id TEXT REFERENCES episodes ON DELETE CASCADE,
 event_id TEXT REFERENCES evidence ON DELETE RESTRICT,PRIMARY KEY(memory_id,event_id));
CREATE TABLE claims(claim_id TEXT PRIMARY KEY,memory_id TEXT REFERENCES episodes ON DELETE CASCADE,
 subject TEXT NOT NULL,predicate TEXT NOT NULL,value TEXT NOT NULL,kind TEXT NOT NULL,
 valid_from REAL,valid_to REAL,refs TEXT NOT NULL);
CREATE INDEX claim_identity ON claims(subject,predicate);
CREATE TABLE revisions(memory_id TEXT REFERENCES episodes ON DELETE CASCADE,revision INTEGER,
 summary TEXT NOT NULL,claims TEXT NOT NULL,reason TEXT NOT NULL,PRIMARY KEY(memory_id,revision));
CREATE TABLE vectors(memory_id TEXT REFERENCES episodes ON DELETE CASCADE,revision INTEGER,
 view INTEGER,space_key TEXT,space TEXT,view_text TEXT,vector TEXT,PRIMARY KEY(memory_id,view,space_key));
CREATE TABLE tombstones(fingerprint TEXT PRIMARY KEY);
'''
def fingerprint(value):return hashlib.sha256(canonical(value).encode()).hexdigest()
def bounded(value,limit=200):
 if not isinstance(value,str) or not value.strip() or len(value)>limit:raise ValueError('bounded nonempty text required')
 return value

def instant(value):
 if value is None:return None
 if isinstance(value,str):return timestamp(value)
 if type(value) not in (float,int) or not math.isfinite(value):raise ValueError('finite time required')
 return float(value)

def normalize_claim(c):
 allowed={'subject','predicate','value','evidence_kind','evidence_ids','valid_from','valid_to'}
 if set(c)!=allowed:raise ValueError('complete typed claim required')
 subject,predicate=bounded(c['subject']),bounded(c['predicate'])
 if type(c['value']) not in (str,int,float,bool,type(None)):raise ValueError('scalar claim required')
 if isinstance(c['value'],str):bounded(c['value'],500)
 if type(c['value']) is float and not math.isfinite(c['value']):raise ValueError('finite value required')
 kind=c['evidence_kind']
 if kind not in ('observed','reported','inferred','unknown'):raise ValueError('explicit evidence kind required')
 refs=c['evidence_ids']
 if not isinstance(refs,list) or not refs or len(refs)>32 or len(set(refs))!=len(refs):raise ValueError('unique evidence references required')
 for ref in refs:uuid.UUID(ref)
 start,end=instant(c['valid_from']),instant(c['valid_to'])
 if end is not None and (start is None or end<=start):raise ValueError('nonempty half-open valid interval required')
 return dict(subject=subject,predicate=predicate,value=c['value'],evidence_kind=kind,evidence_ids=sorted(refs),valid_from=start,valid_to=end)

def views(summary):
 """Exact source spans only: full text plus first three complete sentences."""
 bounded(summary,2000)
 sentences=[s.strip() for s in re.split(r'(?<=[.!?])\s+',summary) if s.strip()]
 return list(dict.fromkeys([summary,*sentences[:3]]))

def overlaps(a,b):
 if a['valid_from'] is None or b['valid_from'] is None:return False
 return max(a['valid_from'],b['valid_from'])<min(a['valid_to'] if a['valid_to'] is not None else math.inf,b['valid_to'] if b['valid_to'] is not None else math.inf)

class MemoryV02:
 def __init__(self,path,*,owner_id,retention_seconds,clock=time.time):
  self.path=Path(path).resolve();self.owner_id=bounded(owner_id);self.retention_seconds=retention_seconds;self.clock=clock
  if type(retention_seconds) not in (int,float) or not math.isfinite(retention_seconds) or retention_seconds<=0:raise ValueError('positive explicit retention required')
  fresh=not self.path.exists()
  if not fresh:
   with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True)) as db:
    try:meta=dict(db.execute('SELECT key,value FROM metadata'))
    except sqlite3.Error as exc:raise ValueError('not v0.2 database; no migration') from exc
    if meta!={'kind':KIND,'owner_id':owner_id,'retention_seconds':canonical(retention_seconds)}:raise ValueError('wrong version/owner/retention; no migration')
  self.path.parent.mkdir(parents=True,exist_ok=True);self.db=sqlite3.connect(self.path);self.db.row_factory=sqlite3.Row
  try:
   self.db.execute('PRAGMA foreign_keys=ON');self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL');self.db.execute('PRAGMA secure_delete=ON')
   if fresh:
    self.db.executescript(SCHEMA)
    with self.db:self.db.executemany('INSERT INTO metadata VALUES(?,?)',[('kind',KIND),('owner_id',owner_id),('retention_seconds',canonical(retention_seconds))])
  except BaseException:self.db.close();raise
 def close(self):self.db.close()
 def __enter__(self):return self
 def __exit__(self,*args):self.close()
 def _owner(self,actor):
  if actor!=self.owner_id:raise PermissionError('owner required')
 def ingest(self,events,*,actor):
  self._owner(actor);prepared=[]
  for event in events:
   p=project_event(event);claims=[normalize_claim(c) for c in event['payload'].get('memory_claims',[])]
   if len(claims)>16:raise ValueError('claim budget exceeded')
   for c in claims:
    if p['event_id'] not in c['evidence_ids']:raise ValueError('source claim must cite its own event')
    if c['evidence_kind']=='observed' and p['event_type']!='observation.accepted':raise ValueError('reported text cannot become observation')
   narrative=event['payload'].get('memory_narrative')
   if narrative is not None:bounded(narrative,2000)
   prepared.append((p,claims,narrative))
  with self.db:
   for p,claims,narrative in prepared:
    if self.db.execute('SELECT 1 FROM tombstones WHERE fingerprint=?',(fingerprint(p['event_id']),)).fetchone():continue
    old=self.db.execute('SELECT envelope_sha256 FROM evidence WHERE event_id=?',(p['event_id'],)).fetchone()
    if old and old[0]!=p['envelope_sha256']:raise ValueError('immutable event identity reused')
    if not old:self.db.execute('INSERT INTO evidence VALUES(?,?,?,?,?,?,?)',(p['event_id'],p['envelope_sha256'],canonical(p),p['source_instance_id'],p['source_sequence'],canonical(claims),narrative))
  return len(prepared)
 def _validate_text(self,text,refs):
  if not any(self.db.execute('SELECT 1 FROM evidence WHERE event_id=? AND narrative=?',(ref,text)).fetchone() for ref in refs):raise ValueError('narrative must match a cited source record')
 def _validate_claims(self,claims,refs):
  normalized=[normalize_claim(c) for c in claims]
  for c in normalized:
   if not set(c['evidence_ids'])<=set(refs):raise ValueError('claim references uncited evidence')
   supported=False
   for ref in c['evidence_ids']:
    row=self.db.execute('SELECT claims FROM evidence WHERE event_id=?',(ref,)).fetchone()
    if row and c in json.loads(row[0]):supported=True
   if not supported:raise ValueError('typed claim not present in original source evidence')
  return normalized
 def consolidate(self,run_id,correlation_id,*,actor,domain,summary,claims,context='default',reality='game',extra_evidence_ids=()):
  self._owner(actor);uuid.UUID(run_id);uuid.UUID(correlation_id);bounded(domain,80);bounded(context);bounded(summary,2000)
  if reality not in ('game','fictional','real','unknown'):raise ValueError('explicit reality scope required')
  mid=str(uuid.uuid5(uuid.NAMESPACE_URL,KIND+run_id+correlation_id))
  if self.db.execute('SELECT 1 FROM tombstones WHERE fingerprint=?',(fingerprint(mid),)).fetchone():return None
  old=self.inspect(mid,actor=actor)
  if old:
   if (old['domain'],old['context'],old['reality'])!=(domain,context,reality):raise ValueError('episode context immutable')
   return mid
  rows=self.db.execute('SELECT event_id,projection FROM evidence WHERE json_extract(projection,\'$.run_id\')=? AND json_extract(projection,\'$.correlation_id\')=?',(run_id,correlation_id)).fetchall()
  refs={r[0] for r in rows}|set(extra_evidence_ids)
  if not rows:raise ValueError('no source episode')
  projected=[json.loads(r[1]) for r in rows];sessions={p['session_id'] for p in projected}
  if len(sessions)!=1:raise ValueError('cross-session episode')
  for event in projected:
   for ref in event['observation_ids']:
    row=self.db.execute('SELECT projection FROM evidence WHERE event_id=?',(ref,)).fetchone()
    if not row:raise ValueError('missing source observation')
    obs=json.loads(row[0])
    if obs['event_type']!='observation.accepted' or obs['session_id'] not in sessions or (obs['run_id']!=run_id and ref not in extra_evidence_ids) or (obs['source_instance_id']==event['source_instance_id'] and obs['source_sequence']>event['source_sequence']):raise ValueError('incompatible or future source observation')
    refs.add(ref)
  for ref in extra_evidence_ids:
   row=self.db.execute('SELECT projection FROM evidence WHERE event_id=?',(ref,)).fetchone()
   if not row or json.loads(row[0])['session_id'] not in sessions:raise ValueError('missing or cross-session shared evidence')
  self._validate_text(summary,refs)
  normalized=self._validate_claims(claims,refs);occurred=max(p['occurred'] for p in projected)
  with self.db:
   self.db.execute('INSERT INTO episodes VALUES(?,?,?,?,?,?,?,?,?,?,1)',(mid,run_id,correlation_id,next(iter(sessions)),domain,context,reality,occurred,occurred+self.retention_seconds,summary))
   self.db.executemany('INSERT INTO citations VALUES(?,?)',[(mid,ref) for ref in sorted(refs)])
   self._write_claims(mid,normalized);self.db.execute('INSERT INTO revisions VALUES(?,1,?,?,?)',(mid,summary,canonical(normalized),'initial evidence-linked narrative'))
  return mid
 def _write_claims(self,mid,claims):
  self.db.execute('DELETE FROM claims WHERE memory_id=?',(mid,))
  for c in claims:
   self.db.execute('INSERT INTO claims VALUES(?,?,?,?,?,?,?,?,?)',(fingerprint([mid,c]),mid,c['subject'],c['predicate'],canonical(c['value']),c['evidence_kind'],c['valid_from'],c['valid_to'],canonical(c['evidence_ids'])))
 def _claims(self,mid):
  return [dict(subject=r['subject'],predicate=r['predicate'],value=json.loads(r['value']),evidence_kind=r['kind'],valid_from=r['valid_from'],valid_to=r['valid_to'],evidence_ids=json.loads(r['refs'])) for r in self.db.execute('SELECT * FROM claims WHERE memory_id=? ORDER BY claim_id',(mid,))]
 def _conflicts(self,mid):
  m=self.db.execute('SELECT domain,context,reality FROM episodes WHERE memory_id=?',(mid,)).fetchone();pairs=[]
  if not m:return pairs
  for a in self._claims(mid):
   for r in self.db.execute('SELECT c.memory_id FROM claims c JOIN episodes e USING(memory_id) WHERE e.domain=? AND e.context=? AND e.reality=? AND e.expires>? AND c.subject=? AND c.predicate=? AND c.memory_id!=?',(*m,self.clock(),a['subject'],a['predicate'],mid)):
    for b in self._claims(r[0]):
     if (a['subject'],a['predicate'])==(b['subject'],b['predicate']) and a['value']!=b['value'] and a['evidence_kind']!='unknown' and b['evidence_kind']!='unknown' and overlaps(a,b):pairs.append(r[0])
  return sorted(set(pairs))
 def inspect(self,mid,*,actor):
  self._owner(actor);r=self.db.execute('SELECT * FROM episodes WHERE memory_id=?',(mid,)).fetchone()
  if r is None:return None
  m=dict(r);m['claims']=self._claims(mid);m['evidence']=[dict(x) for x in self.db.execute('SELECT event_id,envelope_sha256,projection FROM evidence JOIN citations USING(event_id) WHERE memory_id=? ORDER BY event_id',(mid,))];m['contested_with']=self._conflicts(mid);m['contested']=bool(m['contested_with']);m['expired']=m['expires']<=self.clock();m['narrative_kind']='reported';m.update(GUARD);return m
 def correct(self,mid,text,claims,*,actor,reason,evidence_ids=()):
  self._owner(actor);bounded(text,2000);bounded(reason,200);old=self.inspect(mid,actor=actor)
  if old is None or old['expired']:raise KeyError(mid)
  refs=[r['event_id'] for r in old['evidence']]+list(evidence_ids)
  self._validate_text(text,refs)
  normalized=self._validate_claims(claims,refs)
  # Validate every new citation and session before starting mutation.
  for ref in evidence_ids:
   row=self.db.execute('SELECT projection FROM evidence WHERE event_id=?',(ref,)).fetchone()
   if not row or json.loads(row[0])['session_id']!=old['session_id']:raise ValueError('missing/cross-session correction source')
  revision=old['revision']+1
  with self.db:
   self.db.execute('UPDATE episodes SET summary=?,revision=? WHERE memory_id=?',(text,revision,mid));self.db.executemany('INSERT OR IGNORE INTO citations VALUES(?,?)',[(mid,ref) for ref in evidence_ids]);self._write_claims(mid,normalized)
   self.db.execute('DELETE FROM vectors WHERE memory_id=?',(mid,));self.db.execute('INSERT INTO revisions VALUES(?,?,?,?,?)',(mid,revision,text,canonical(normalized),reason))
 def index(self,mid,embedder,*,actor):
  self._owner(actor);m=self.inspect(mid,actor=actor)
  if not m or m['expired']:raise ValueError('missing/expired episode')
  encoded=[(i,text,unit_vector(embedder.document(text),embedder.space.dimensions)) for i,text in enumerate(views(m['summary']))]
  with self.db:
   current=self.db.execute('SELECT revision FROM episodes WHERE memory_id=?',(mid,)).fetchone()
   if not current or current[0]!=m['revision']:raise ValueError('stale embedding rejected')
   self.db.execute('DELETE FROM vectors WHERE memory_id=? AND space_key=?',(mid,embedder.space.key))
   self.db.executemany('INSERT INTO vectors VALUES(?,?,?,?,?,?,?)',[(mid,m['revision'],i,embedder.space.key,canonical(embedder.space.__dict__),text,canonical(v)) for i,text,v in encoded])
 def _forget(self,ids):
  for mid in ids:
   refs=[r[0] for r in self.db.execute('SELECT event_id FROM citations WHERE memory_id=?',(mid,))]
   self.db.execute('INSERT OR IGNORE INTO tombstones VALUES(?)',(fingerprint(mid),));self.db.execute('DELETE FROM episodes WHERE memory_id=?',(mid,))
   for ref in refs:
    if not self.db.execute('SELECT 1 FROM citations WHERE event_id=?',(ref,)).fetchone():
     self.db.execute('INSERT OR IGNORE INTO tombstones VALUES(?)',(fingerprint(ref),));self.db.execute('DELETE FROM evidence WHERE event_id=?',(ref,))
 def forget(self,mid,*,actor):
  self._owner(actor)
  with self.db:self._forget([mid])
 def forget_evidence(self,event_id,*,actor):
  self._owner(actor);ids=[r[0] for r in self.db.execute('SELECT memory_id FROM citations WHERE event_id=?',(event_id,))]
  with self.db:
   self._forget(ids);self.db.execute('INSERT OR IGNORE INTO tombstones VALUES(?)',(fingerprint(event_id),));self.db.execute('DELETE FROM evidence WHERE event_id=?',(event_id,))
  return ids
 def expire(self,*,actor):
  self._owner(actor);ids=[r[0] for r in self.db.execute('SELECT memory_id FROM episodes WHERE expires<=?',(self.clock(),))]
  with self.db:self._forget(ids)
  return ids
 def search(self,text,*,actor,embedder,domain=None,context=None,contract=None,limit=5):
  self._owner(actor);bounded(text,2000)
  if not 1<=limit<=100:raise ValueError('bounded result budget required')
  where='e.expires>?';params=[self.clock()]
  for col,value in [('domain',domain),('context',context)]:
   if value is not None:where+=' AND e.'+col+'=?';params.append(value)
  q=unit_vector(embedder.query(text),embedder.space.dimensions);ranked={};view_scores={}
  for r in self.db.execute('SELECT v.*,e.summary FROM vectors v JOIN episodes e USING(memory_id) WHERE v.space_key=? AND v.revision=e.revision AND '+where,[embedder.space.key,*params]):
   v=unit_vector(json.loads(r['vector']),embedder.space.dimensions);score=sum(a*b for a,b in zip(q,v));mid=r['memory_id']
   if mid not in ranked or score>ranked[mid]:ranked[mid]=score;view_scores[mid]={'view':r['view'],'text':r['view_text'],'score':score}
  candidates=[]
  for mid in sorted(ranked,key=lambda x:(-ranked[x],x))[:limit]:
   m=self.inspect(mid,actor=actor);m['relevance']=ranked[mid];m['matching_view']=view_scores[mid];candidates.append(m)
  result=dict(GUARD,candidates=candidates,hits=[],answer_status='unknown',answer_uncertainty='query_contract_missing',answer_claims=[],premise_confirmed=False,mode='semantic-only-exact-span-max-v1')
  if contract is None:return result
  allowed={'subject','predicate','as_of','reality','scope','value','requires','selection','evidence_kind','time_window'}
  if set(contract)-allowed:raise ValueError('unknown query-contract fields')
  if contract.get('scope')=='current':result['answer_uncertainty']='live_state_unknown';return result
  # A relation must be explicit. Similarity alone never supplies the claim/question.
  if not contract.get('subject') or not contract.get('predicate'):return result
  matched=[]
  for m in candidates:
   if contract.get('reality') and m['reality']!=contract['reality']:continue
   claims=[]
   for c in m['claims']:
    if (c['subject'],c['predicate'])!=(contract['subject'],contract['predicate']):continue
    at=instant(contract.get('as_of'))
    # An observation recorded later cannot prove an earlier moment by backdating metadata.
    if at is not None and c['evidence_kind']=='observed' and any(json.loads(self.db.execute('SELECT projection FROM evidence WHERE event_id=?',(ref,)).fetchone()[0])['occurred']>at for ref in c['evidence_ids']):continue
    if contract.get('time_window'):
     start,end=map(instant,contract['time_window'])
     if start is None or end is None or start>=end:raise ValueError('nonempty query time window required')
     if not overlaps(c,dict(valid_from=start,valid_to=end)):continue
     if c['evidence_kind']=='observed' and not any(start<=json.loads(self.db.execute('SELECT projection FROM evidence WHERE event_id=?',(ref,)).fetchone()[0])['occurred']<end for ref in c['evidence_ids']):continue
    if at is not None and (c['valid_from'] is None or c['valid_from']>at or c['valid_to'] is not None and at>=c['valid_to']):continue
    if contract.get('evidence_kind') and c['evidence_kind']!=contract['evidence_kind']:continue
    if 'value' in contract and c['value']!=contract['value']:continue
    claims.append(c)
   if claims:matched.append((m,claims))
  if not matched:result['answer_uncertainty']='no_supported_memory';return result
  # Presuppositions are facts to check, not an invitation to invent an intervening event.
  proof_before=instant(contract.get('as_of'))
  if proof_before is None and contract.get('time_window'):proof_before=instant(contract['time_window'][1])
  for need in contract.get('requires',[]):
   if not any(any(c['subject']==need['subject'] and c['predicate']==need['predicate'] and ('value' not in need or c['value']==need['value']) and c['evidence_kind']=='observed' and (proof_before is None or all(json.loads(self.db.execute('SELECT projection FROM evidence WHERE event_id=?',(ref,)).fetchone()[0])['occurred']<=proof_before for ref in c['evidence_ids'])) for c in m['claims']) for m in candidates if not m['contested'] and (not contract.get('reality') or m['reality']==contract['reality'])):result['answer_uncertainty']='premise_unverified';result['premise_status']='unverified';return result
  if contract.get('selection')=='latest_recorded':matched.sort(key=lambda x:(-x[0]['occurred'],x[0]['memory_id']));matched=matched[:1]
  elif contract.get('selection')=='earliest_recorded':matched.sort(key=lambda x:(x[0]['occurred'],x[0]['memory_id']));matched=matched[:1]
  # Determine conflict relevance at the question's time, not merely somewhere in history.
  relevant=[];seen={m['memory_id'] for m,c in matched}
  for m,cs in list(matched):
   for other_id in m['contested_with']:
    other=self.inspect(other_id,actor=actor)
    if other is None or other['expired']:continue
    compatible=[]
    for c in other['claims']:
     if (c['subject'],c['predicate'])!=(contract['subject'],contract['predicate']):continue
     at=instant(contract.get('as_of'))
     if at is not None and (c['valid_from'] is None or c['valid_from']>at or c['valid_to'] is not None and at>=c['valid_to']):continue
     if at is not None and c['evidence_kind']=='observed' and any(json.loads(self.db.execute('SELECT projection FROM evidence WHERE event_id=?',(ref,)).fetchone()[0])['occurred']>at for ref in c['evidence_ids']):continue
     if contract.get('time_window'):
      start,end=map(instant,contract['time_window'])
      if not overlaps(c,dict(valid_from=start,valid_to=end)):continue
      if c['evidence_kind']=='observed' and not any(start<=json.loads(self.db.execute('SELECT projection FROM evidence WHERE event_id=?',(ref,)).fetchone()[0])['occurred']<end for ref in c['evidence_ids']):continue
     if any(c['value']!=existing['value'] and overlaps(c,existing) for existing in cs):compatible.append(c)
    if compatible:
     relevant.append((m['memory_id'],other_id))
     if other_id not in seen:matched.append((other,compatible));seen.add(other_id)
  contested=bool(relevant)
  # Evidence-kind priority is explicit ordering, never deletion of dissenting testimony.
  preference={'observed':0,'reported':1,'inferred':2,'unknown':3}
  matched.sort(key=lambda pair:(min(preference[c['evidence_kind']] for c in pair[1]),-pair[0].get('relevance',-1),pair[0]['memory_id']))
  result['hits']=[m for m,c in matched];result['answer_claims']=[c for m,cs in matched for c in cs]
  result['contested']=contested;result['conflict_pairs']=relevant
  result['answer_status']='uncertain' if contested or any(c['evidence_kind'] in ('unknown','reported','inferred') or c['value'] in (None,'unknown') for c in result['answer_claims']) else 'supported'
  result['answer_uncertainty']='contested' if contested else 'reported_or_inferred_or_unknown' if result['answer_status']=='uncertain' else 'none'
  return result
