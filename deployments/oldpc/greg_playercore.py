"""Staged player core: directed routing, bounded memory and event-driven tasks.
No game process control, network listener, or command-mailbox writer lives here.
"""
from __future__ import annotations
import hashlib
import heapq
import random
import json
import math
import os
import time
import uuid
from collections import deque
from pathlib import Path
from greg_goal_lifecycle import Goals


def point(value):
    try:
        p=tuple(float(value[k]) for k in ('x','y','z')) if isinstance(value,dict) else tuple(map(float,value))
        return p if len(p)==3 and all(math.isfinite(x) for x in p) else None
    except (TypeError,ValueError,KeyError):
        return None


def xyz(p): return dict(zip(('x','y','z'),p))
def distance(a,b): return math.dist(a,b)
def planar(a,b): return math.hypot(a[0]-b[0],a[1]-b[1])


class StateGate:
    """Require increasing telemetry seq AND sample clock within a control context."""
    def __init__(self):
        self.identity=None;self.last_t=-math.inf;self.last_seq=-1;self.retired=deque(maxlen=32)
    def accept(self,state,actor,wall):
        try:
            stamp=float(state['t']);age=wall-float(state['serverTime']);seq=state['seq']
            if isinstance(seq,bool) or not isinstance(seq,int) or seq<0:return False
            identity=(state['steamid'],state['bridgeSession'],state['controlEpoch'])
            if not isinstance(identity[2],int) or isinstance(identity[2],bool):return False
            if self.identity and identity[:2]==self.identity[:2] and identity[2]<self.identity[2]:return False
            if state['steamid']!=actor or not 0<=age<=3 or not math.isfinite(stamp):return False
            if identity!=self.identity:
                if identity in self.retired:return False
                if self.identity:self.retired.append(self.identity)
                self.identity=identity;self.last_t=-math.inf;self.last_seq=-1
            if stamp<=self.last_t or seq<=self.last_seq:return False
            self.last_t=stamp;self.last_seq=seq;return True
        except (KeyError,TypeError,ValueError):return False


class EventMemory:
    """Append events; bounded, map-scoped digest. Never resumes a saved task."""
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.events=self.root/'events.jsonl';self.world_path=self.root/'world.json'
        self.tail=deque(maxlen=128);self.world={};self.dirty=False;self.last_flush=-math.inf
        if self.events.exists():
            # Bounded tail read, even after an interrupted old run.
            with self.events.open('rb') as f:
                f.seek(0,2);size=f.tell();f.seek(max(0,size-262144));raw=f.read()
            lines=raw.decode('utf8','replace').splitlines()
            for line in lines:
                try:
                    e=json.loads(line)
                    if isinstance(e,dict):self.tail.append(e)
                except ValueError:pass
        try:
            w=json.loads(self.world_path.read_text());self.world=w if isinstance(w,dict) else {}
        except (OSError,ValueError):pass
    def add(self,kind,map_name,**fields):
        event={'time':time.time(),'kind':kind,'map':str(map_name),**fields}
        self.tail.append(event)
        if (kind == 'goal_lifecycle' and fields.get('source') == 'self'
                and fields.get('status') in {'completed', 'failed'}):
            scope = self.world.setdefault(str(map_name), {})
            recent = scope.setdefault('recent_goals', [])
            text = ' '.join(str(fields.get('text', '')).casefold().split())[:400]
            if text:
                recent = [item for item in recent if item != text]
                recent.append(text)
                scope['recent_goals'] = recent[-12:]
        try:
            with self.events.open('a',encoding='utf8') as f:f.write(json.dumps(event)+'\n')
            if self.events.stat().st_size>2_000_000:
                self._atomic(self.events,''.join(json.dumps(e)+'\n' for e in self.tail))
        except OSError:pass # Memory disk failure must not kill movement/interlocks.
        self.dirty=True
    def _atomic(self,path,text):
        tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(text,encoding='utf8');os.replace(tmp,path)
    def edge_failure(self,map_name,edge,now):
        key=f'{edge[0]}>{edge[1]}'
        self.world.setdefault(map_name,{}).setdefault('blocked_edges',{})[key]=now+300
        self.add('route_edge_blocked',map_name,edge=list(edge),expires=now+300)
    def blocked(self,map_name,wall):
        records=self.world.get(map_name,{}).get('blocked_edges',{})
        return {tuple(map(int,k.split('>'))) for k,v in records.items() if isinstance(v,(float,int)) and v>wall}
    def landmarks(self,map_name):
        return self.world.get(map_name,{}).get('landmarks',[])
    def import_landmarks(self,path,map_name):
        # Old landmark files have no map; caller MUST supply verified provenance.
        if not map_name:return 0
        try:data=json.loads(Path(path).read_text())
        except (OSError,ValueError):return 0
        valid=[dict(x) for x in data if isinstance(x,dict) and point(x) and isinstance(x.get('name'),str)] if isinstance(data,list) else []
        self.world.setdefault(map_name,{})['landmarks']=valid;self.dirty=True;return len(valid)
    def recent_events(self, map_name, limit=12):
        # Filter BEFORE slicing: activity on another map must not hide this map.
        return [e for e in self.tail if e.get('map') == map_name][-limit:] if limit > 0 else []

    def recent_goals(self, map_name):
        scope = self.world.get(map_name, {})
        stored = scope.get('recent_goals', []) if isinstance(scope, dict) else []
        if not isinstance(stored, list):
            stored = []
        # Also recover a just-appended outcome if the last world flush was interrupted.
        recovered = [e.get('text') for e in self.recent_events(map_name, 128)
                     if e.get('kind') == 'goal_lifecycle' and e.get('source') == 'self'
                     and e.get('status') in {'completed', 'failed'}]
        result = []
        for text in stored + recovered:
            if not isinstance(text, str) or not text.strip():
                continue
            text = ' '.join(text.casefold().split())[:400]
            if text in result:
                result.remove(text)
            result.append(text)
        return result[-12:]

    def summary(self,map_name,person='',task=None,goal=None):
        kinds = {'directive', 'arrived', 'route_failed', 'target_lost',
                 'interaction', 'goal_lifecycle', 'rescue'}
        recent = []
        for event in self.recent_events(map_name, 128):
            if event.get('kind') not in kinds:
                continue
            # Drop runtime internals; retain observed outcomes and why they happened.
            compact = {k: event[k] for k in ('time', 'kind', 'text', 'person',
                       'source', 'status', 'reason', 'interaction') if k in event}
            compact = {k: v[:400] if isinstance(v, str) else v
                       for k, v in compact.items()}
            recent.append(compact)
        recent = recent[-8:]
        landmarks = [{'name': x['name'], 'pos': xyz(point(x)),
                      'note': str(x.get('note', ''))[:160]}
                     for x in self.landmarks(map_name)
                     if isinstance(x, dict) and isinstance(x.get('name'), str) and point(x)][:24]
        active = {k: goal[k] for k in ('id', 'text', 'source', 'target', 'ticks')
                  if k in goal} if isinstance(goal, dict) else None
        payload = {'map': map_name, 'speaker': person, 'active_task': task,
                   'active_goal': active, 'landmarks': landmarks, 'recent_events': recent}
        while len(json.dumps(payload)) > 6000 and landmarks:
            landmarks.pop()
        while len(json.dumps(payload)) > 6000 and recent:
            recent.pop(0)
        return json.dumps(payload, ensure_ascii=True)
    def flush(self,now):
        if not self.dirty or now-self.last_flush<5:return
        try:
            self._atomic(self.world_path,json.dumps(self.world,indent=2))
            self._atomic(self.root/'digest.json',json.dumps(list(self.tail)[-24:],indent=2))
            self.last_flush=now;self.dirty=False
        except OSError:pass


class Area:
    def __init__(self,row):
        self.id=int(row['i']);self.center=point(row['c']);self.adj=list(map(int,row.get('a',[])))
        self.corners=[point(k) for k in row.get('k',[])]
        if not self.center or len(self.corners)!=4 or any(k is None for k in self.corners):raise ValueError('invalid nav geometry')
        self.x0=min(k[0] for k in self.corners);self.x1=max(k[0] for k in self.corners)
        self.y0=min(k[1] for k in self.corners);self.y1=max(k[1] for k in self.corners)
        self.walkable=not row.get('b') and not (int(row.get('t',0)) & 3) # crouch/jump traversal not implemented
    def height(self,x,y):
        # Bilinear rectangular nav surface; reject malformed degenerate areas.
        if self.x1<=self.x0 or self.y1<=self.y0:raise ValueError('degenerate nav area')
        fx=max(0,min(1,(x-self.x0)/(self.x1-self.x0)));fy=max(0,min(1,(y-self.y0)/(self.y1-self.y0)))
        def z(cx,cy):return min(self.corners,key=lambda p:abs(p[0]-cx)+abs(p[1]-cy))[2]
        return (1-fx)*(1-fy)*z(self.x0,self.y0)+fx*(1-fy)*z(self.x1,self.y0)+fx*fy*z(self.x1,self.y1)+(1-fx)*fy*z(self.x0,self.y1)
    def closest(self,p):
        x=max(self.x0,min(self.x1,p[0]));y=max(self.y0,min(self.y1,p[1]));return (x,y,self.height(x,y))


class NavGraph:
    """Directed A*, no invented adjacency. Conservative walk portals, no ladders."""
    def __init__(self,data):
        self.map=str(data.get('map',''));self.areas={}
        for row in data.get('areas',[]):
            try:
                a=Area(row)
                if a.walkable:self.areas[a.id]=a
            except (ValueError,KeyError,TypeError):continue
        self.links={i:{} for i in self.areas}
        for i,a in self.areas.items():
            for j in a.adj:
                b=self.areas.get(j)
                if b is None:continue
                # Shared boundary/overlap only: no leaps across map gaps.
                x0,x1=max(a.x0,b.x0),min(a.x1,b.x1);y0,y1=max(a.y0,b.y0),min(a.y1,b.y1)
                if x0>x1+1 or y0>y1+1:continue
                # A 32-wide hull needs a usable portal, not a point corner.
                if max(x1-x0,y1-y0)<36:continue
                x,y=(x0+x1)/2,(y0+y1)/2
                za,zb=a.height(x,y),b.height(x,y);rise=zb-za
                if rise>18 or rise < -48:continue
                self.links[i][j]=[(x,y,max(za,zb))]
    @classmethod
    def load(cls,path,waypoints=""):
        graph=cls(json.loads(Path(path).read_text()))
        if waypoints:graph.add_verified_links(json.loads(Path(waypoints).read_text()))
        return graph
    def add_verified_links(self,data):
        if data.get('map')!=self.map:raise ValueError('waypoint overlay map mismatch')
        for link in data.get('links',[]):
            if link.get('verified') is not True or link.get('type')!='walk':continue
            u,v=link.get('from'),link.get('to');via=[point(p) for p in link.get('via',[])]
            if u not in self.areas or v not in self.areas or not via or len(via)>64 or any(p is None for p in via):raise ValueError('invalid verified walk link')
            if distance(via[0],self.areas[u].closest(via[0]))>64 or distance(via[-1],self.areas[v].closest(via[-1]))>64:raise ValueError('walk link endpoints not on nav areas')
            self.links[u][v]=via
    def attach(self,p):
        options=[(distance(p,a.closest(p)),i) for i,a in self.areas.items() if abs(p[2]-a.closest(p)[2])<=64]
        if not options:return None
        d,i=min(options);return i if d<=128 else None
    def route(self,start,end,blocked=()):
        s,g=self.attach(start),self.attach(end)
        if s is None or g is None:raise ValueError('position is not near a usable nav area')
        denied=set(blocked);front=[(0,0,s)];cost={s:0};previous={};closed=set()
        while front:
            _,actual,u=heapq.heappop(front)
            if u in closed:continue
            closed.add(u)
            if u==g:break
            for v in self.links[u]:
                if (u,v) in denied:continue
                anchors=[self.areas[u].center]+self.links[u][v]+[self.areas[v].center]
                step=sum(distance(a,b) for a,b in zip(anchors,anchors[1:]))
                new=actual+step
                if new<cost.get(v,math.inf):
                    cost[v]=new;previous[v]=u
                    heapq.heappush(front,(new+distance(self.areas[v].center,self.areas[g].center),new,v))
        if g not in closed:raise ValueError('no connected walk route')
        ids=[g]
        while ids[-1]!=s:ids.append(previous[ids[-1]])
        ids.reverse()
        # Portal + next-area interior: each segment stays inside a convex nav area.
        points=[];edges=[]
        for u,v in zip(ids,ids[1:]):
            via=self.links[u][v]+[self.areas[v].center]
            points.extend(via);edges.extend([(u,v)]*len(via))
        points.append(end);edges.append(None)
        if len(points)>256:raise ValueError('route too long; requires hierarchical planning')
        return {'areas':ids,'points':points,'edges':edges}


class Runtime:
    def __init__(self,graph,memory,*,observer=None):
        self.observer=observer
        self.speech=deque();self.committed_id=None;self.target_failures={};self.failure_context=None
        self.goals=Goals(self.goal_event)
        self.graph=graph;self.memory=memory;self.gate=StateGate();self.route=None;self.route_id=''
        self.context=None;self.task_key=None;self.destination=None;self.failures=0;self.failed=False
        self.last_plan=-math.inf;self.replan_after=0;self.last_feedback=None;self.autotask=None
        self.rescue_eligible=False;self.needs_brain=True;self.wake_at=math.inf;self.events=deque(maxlen=8);self.last_interaction=None;self.last_rescue=None
    def _notify(self,event):
        if self.observer is not None:
            try:self.observer(event)
            except Exception:pass
    def goal_event(self, event):
        self._notify(dict(event,kind='goal'))
        self.memory.add('goal_lifecycle', event.get('map',''), **{k:v for k,v in event.items() if k!='map'})
        event=dict(event,wall=time.time(),mono=time.monotonic())
        if event.get('status') in {'failed','abandoned'}:
            self.speech=deque(x for x in self.speech if x.get('id')!=event.get('id'))
        if event.get('status')=='failed' and event.get('source')=='self':
            k=event.get('text','').casefold();self.target_failures[k]=self.target_failures.get(k,0)+max(1,self.failures)
        if event.get('status')=='completed' and event.get('reason')=='arrived':
            label=event['text'].split(':',1)[-1] if event['text'].startswith('landmark:') else 'my destination'
            self.speech.append({'id':event.get('id'),'text':'Made it to '+label+'.','kind':'arrival'})
        print('GOAL ' + json.dumps(event), flush=True)
    def end_goal(self, status, reason):
        self.goals.finish(status, reason)
        self.autotask=None;self.route=None;self.route_id='';self.task_key=None
        self.failed=False;self.rescue_eligible=False;self.needs_brain=True
    def observe(self,state,actor,wall,now):
        if not self.gate.accept(state,actor,wall):return False
        self._notify({'kind':'state','state':state})
        context=(state.get('map'),state.get('bridgeSession'),state.get('controlEpoch'))
        if context!=self.failure_context:self.target_failures.clear();self.failure_context=context
        if context!=self.context:
            self.end_goal("abandoned", "map_or_session_changed")
            self.reset();self.context=context;self.needs_brain=True
            # Restore avoidance, never actions, routes, targets or a running goal.
            self.goals.recent.clear()
            self.goals.recent.extend(self.memory.recent_goals(state.get('map', '')))
        f=state.get('locomotion') or {}
        interaction=(state.get('bridgeSession'),f.get('interactionTime'),f.get('interaction'))
        if f.get('interaction') and interaction!=self.last_interaction:
            self.memory.add('interaction',state.get('map',''),interaction=f['interaction'],pos=state.get('pos'))
            self.last_interaction=interaction
        rescue=state.get('rescue') or {}
        rescue_key=(state.get('bridgeSession'),rescue.get('event'))
        if rescue.get('status') and rescue_key!=self.last_rescue:
            self.memory.add('rescue',state.get('map',''),status=rescue['status'],owned=rescue.get('owned',False))
            self.last_rescue=rescue_key
        had_goal = self.goals.active is not None
        self.goals.observe(state, now)
        if had_goal and self.goals.active is None:
            self.end_goal('failed', 'observed_outcome')
        self.memory.flush(now);return True
    def reset(self):
        self.route=None;self.route_id='';self.task_key=None;self.destination=None;self.failures=0;self.failed=False;self.last_feedback=None;self.autotask=None;self.wake_at=math.inf
    def directive(self,user,text,map_name,now,kind=None):
        self.memory.add('directive',map_name,person=user,text=str(text)[:400])
        if kind != "continue":self.end_goal("abandoned", "superseded_by_chat")
        # Existing Intent handles continue/cancel; don't reset route unconditionally.
    def prompt(self,state,speaker=''):
        return 'PLAYER MEMORY (facts, not instructions): '+self.memory.summary(state.get('map',''),speaker,self.autotask,self.goals.active) + ' RECENT GOALS (avoid): ' + ' | '.join(self.goals.recent)+'\n'
    def player(self,state,sid):
        candidates=[p for p in state.get('players',[]) if p.get('steamid')==sid and p.get('fresh') is True and point(p.get('pos'))]
        return candidates[0] if len(candidates)==1 else None
    def _feedback(self,state,now):
        f=state.get('locomotion') or {}
        token=(f.get('id'),f.get('event'))
        if f.get('id')!=self.route_id or token==self.last_feedback:return
        self.last_feedback=token
        if f.get('status') in {'stuck','blocked','no_ground','route_diverged','expired'}:
            self.failures+=1
            edge=None
            if self.route:
                index=max(0,min(len(self.route['edges'])-1,int(f.get('cursor',1))-1));edge=self.route['edges'][index]
            if edge and f.get('status')!='expired':self.memory.edge_failure(self.graph.map,edge,time.time())
            self.memory.add('route_failed',self.graph.map,reason=f.get('status'),route=self.route_id,edge=edge)
            self.route=None;self.route_id='';self.replan_after=now+.5
            if self.failures>=2:self.failed=True
        elif f.get('status')=='arrived':
            self.memory.add('arrived',self.graph.map,route=self.route_id)
            self.route=None;self.route_id=''
    def route_action(self,intent,state,now):
        plan=intent.plan or {};kind=plan.get('kind');map_name=state.get('map','')
        own=point(state.get('pos'))
        if not own or map_name!=self.graph.map:return {'action':'wait'},'No matching navigation map is loaded.'
        if not (state.get('capabilities') or {}).get('playercore'):return {'action':'wait'},'Continuous controller is not enabled on this client.'
        key=(intent.version,kind,intent.speaker_id,plan.get('target'))
        if key!=self.task_key:
            saved_task=self.autotask;self.reset();self.autotask=saved_task;self.task_key=key;self.last_plan=-math.inf
        self._feedback(state,now)
        if self.failed:return {'action':'wait','rescueEligible':True},'Two route attempts failed. I need a new direction.'
        gaze_sid=None
        if kind in {'follow','approach'}:
            player=self.player(state,intent.speaker_id)
            if player is None:
                if self.route:self.memory.add('target_lost',map_name,person=intent.speaker)
                self.route=None;self.route_id=''
                return {'action':'wait'},'Lost a fresh position for you. Waiting here.'
            dest=point(player['pos']);gaze_sid=intent.speaker_id
        elif kind=='landmark':
            target = str(plan.get('target', '')).strip().casefold()
            landmarks = self.memory.landmarks(map_name)
            hits = [l for l in landmarks if target and target == l.get('name', '').casefold()]
            if not hits:
                hits = [l for l in landmarks if target and target in l.get('name', '').casefold()]
            if len(hits)!=1:return {'action':'wait'},'That landmark is missing or ambiguous on this map.'
            dest=point(hits[0])
            area=self.graph.attach(dest) if dest else None
            if area is not None:dest=self.graph.areas[area].closest(dest)
        elif kind=='explore':
            dest=point(plan.get('pos'))
        else:
            matches=[p for p in state.get('nearby',[]) if str(plan.get('target','')).casefold() in (' '.join(str(p.get(k,'')) for k in ('name','class','model'))).casefold() and point(p.get('pos'))]
            if len(matches)!=1:return {'action':'wait'},'I cannot locate that target unambiguously.'
            dest=point(matches[0]['pos'])
        if not dest:return {'action':'wait'},'The target position is unavailable.'
        if planar(own,dest)<=100 and abs(own[2]-dest[2])<48:
            if self.route:self.memory.add('arrived',map_name,route=self.route_id,person=intent.speaker)
            if kind!='follow' and not (self.autotask and self.goals.active):intent.done=True
            self.rescue_eligible=False
            self.route=None;self.route_id=''
            return {'action':'gaze','target':xyz((dest[0],dest[1],dest[2]+60)),'duration':1,'stop':True},''
        if now<self.replan_after:return {'action':'wait','rescueEligible':self.rescue_eligible},''
        moved=self.destination is None or distance(dest,self.destination)>96
        self.rescue_eligible=True
        if self.route is None or (moved and now-self.last_plan>=1):
            try:self.route=self.graph.route(own,dest,self.memory.blocked(map_name,time.time()))
            except ValueError as exc:
                self.failed=True;self.memory.add('route_failed',map_name,reason=str(exc))
                return {'action':'wait','rescueEligible':True},'No connected walking route to that position.'
            self.route_id=uuid.uuid4().hex[:12];self.destination=dest;self.last_plan=now
            self.memory.add('route_planned',map_name,id=self.route_id,areas=self.route['areas'],target=xyz(dest))
            self._notify({'kind':'route','id':self.route_id,'target':xyz(dest),'status':'planned'})
            if self.goals.active:
                g=self.goals.active;g['target']=dest
                length=sum(distance(a,b) for a,b in zip([own]+self.route['points'],self.route['points']))
                g['ttl']=max(g.get('ttl',0) if g.get('eta_set') else 0,60,length/180*2+30)
                g['eta_set']=True
        self.rescue_eligible=True
        return {'action':'navigate','id':self.route_id,'points':[{**xyz(p),'radius':8 if n<len(self.route['points'])-1 else 24} for n,p in enumerate(self.route['points'])],
                'lease':2.5,'walk':bool(plan.get('walk')),'gazeSteamID':gaze_sid},''
    def autonomous(self,proposal,state,now,intent):
        # A completed primitive is an event; a stable task never needs per-step inference.
        if now>=self.wake_at:self.needs_brain=True;self.wake_at=math.inf
        if self.goals.active and self.autotask:proposal=None
        if proposal:
            # A model's micro-move in free-roam starts a routed episode instead.
            if proposal.get('action')=='move':proposal={'action':'goal','kind':'explore'}
            act=proposal.get('action')
            if act=='goal':
                kind=proposal.get('kind');target=str(proposal.get('target',''))[:100]
                text = kind + ':' + target if kind == 'landmark' else 'explore'
                # Explore destinations are selected below; compare concrete coordinates.
                if kind == 'landmark' and (text.casefold() in self.goals.recent or self.target_failures.get(text.casefold(),0)>=2):
                    kind='explore';target='';text='explore'
                if kind=='landmark':self.autotask={'kind':'landmark','target':target}
                elif kind=='explore':
                    own=point(state.get('pos'))
                    # Consume candidates, including rejected/blocked ones. Never park
                    # on one recent destination; bound route work per decision.
                    options=list(self.graph.areas)
                    random.SystemRandom().shuffle(options)
                    offset=getattr(self,'explore_cursor',0)%max(1,len(options))
                    found=None
                    for n in range(min(64,len(options))):
                        index=(offset+n)%len(options)
                        self.explore_cursor=(index+1)%len(options)
                        dest=self.graph.areas[options[index]].center
                        candidate='explore:' + ','.join(str(round(v)) for v in dest)
                        if candidate.casefold() in self.goals.recent or self.target_failures.get(candidate.casefold(),0)>=2:continue
                        if own and 256<distance(own,dest)<3000:
                            try:
                                self.graph.route(own,dest,self.memory.blocked(self.graph.map,time.time()))
                            except ValueError:continue
                            if self.goals.start(candidate,'self',state,now,dest):
                                found=dest;break
                    self.autotask={'kind':'explore','pos':xyz(found)} if found else None
                else:self.autotask=None
                if self.autotask:
                    dest=point(self.autotask.get('pos'))
                    if dest: text='explore:' + ','.join(str(round(v)) for v in dest)
                    if kind!='explore' and not self.goals.start(text, 'self', state, now, dest):
                        self.end_goal('abandoned', 'repeat_rejected')
                        return self.autonomous({'action':'goal','kind':'explore'},state,now,intent)
                self.task_key=None;self.needs_brain=False
                if not self.autotask:
                    self.end_goal('failed','no_reachable_exploration_goal')
                    self.needs_brain=False;self.wake_at=now+2
                    return {'action':'wait','reason':'no_reachable_exploration_goal','retryAfter':2}
            elif act not in {'navigate','gaze'}:
                self.end_goal('abandoned', 'new_primitive')
                self.needs_brain=False;self.wake_at=now+max(.5,float(proposal.get('duration',1)))
                return proposal
        if self.autotask:
            class Task:pass
            task=Task();task.plan=self.autotask;task.version=intent.version;task.speaker_id='';task.speaker='';task.done=False
            action,reply=self.route_action(task,state,now)
            if self.goals.active and self.destination:
                self.goals.active['target'] = self.destination
                if not self.failed and action.get('action')=='navigate' and self.committed_id!=self.goals.active['id']:
                    self.committed_id=self.goals.active['id']
                    label=self.autotask.get('target') if self.autotask.get('kind')=='landmark' else None
                    self.speech.append({'id':self.committed_id,'text':"I'm going to check out "+label+'.' if label else "I'm going for a wander.",'kind':'commit'})
            if task.done or self.failed:
                self.end_goal('completed' if task.done else 'failed', 'arrived' if task.done else 'route_failed')
            elif reply:
                self.end_goal('failed', 'unavailable_target: ' + reply)
            return action
        # No active task must never permanently disable inference.
        self.needs_brain=self.wake_at==math.inf or now>=self.wake_at
        return {'action':'wait','reason':'awaiting_new_goal'}
