"""Core-selected conversational tasks; only the bridge thread may apply/execute.

No model calls, mailbox writes, new memory writer, arbitrary coordinates or guest grants.
"""
from copy import deepcopy
import hashlib
import json
import math
import re
import threading
from types import SimpleNamespace
import time
import uuid


def binding(state):
    return tuple(state.get(k) for k in ('map','bridgeSession','controlEpoch'))


def position(value):
    if isinstance(value,dict):value=[value.get(k) for k in ('x','y','z')]
    if not isinstance(value,(tuple,list)) or len(value)!=3:return None
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in value):return None
    return tuple(value)


def heading(state):
    value=(state.get('ang') or {}).get('y') if isinstance(state.get('ang'),dict) else None
    return value if type(value) in (int,float) and math.isfinite(value) else None


def unpause(task,now):
    """Clear a pause, shifting the task's clocks by the time it was held."""
    held=max(0.,now-task.pop('paused_at'))
    for key in ('deadline','expires_at','review_until'):
        if type(task.get(key)) in (int,float) and math.isfinite(task[key]):task[key]+=held


class GameTasks:
    def __init__(self,owner_steamid=''):
        self.owner_steamid=owner_steamid
        self.lock=threading.Lock();self.view=None;self.active=None;self.last_outcome=None;self.revision=0
        self.last_candidates=-math.inf;self.candidates=[]
        self.last_refusal=None;self.refusals=0

    def invalidate(self):
        with self.lock:
            self.active=None;self.last_outcome=None;self.last_refusal=None;self.refusals=0;self.view=None;self.candidates=[];self.revision+=1
            self.last_candidates=-math.inf

    def people(self,state):
        """Per-world aliases, not display-name identity or model-invented coordinates."""
        rows=[p for p in state.get('players',[]) if isinstance(p,dict)]
        counts={p.get('steamid'):sum(q.get('steamid')==p.get('steamid') for q in rows)
                for p in rows if isinstance(p.get('steamid'),str)}
        result=[]
        for p in rows:
            sid=p.get('steamid')
            if (not isinstance(sid,str) or not re.fullmatch(r'STEAM_[0-5]:[01]:[0-9]+',sid)
                    or sid==state.get('steamid') or counts.get(sid)!=1 or p.get('fresh') is not True
                    or position(p.get('pos')) is None):continue
            alias=hashlib.sha256((str(binding(state))+sid).encode()).hexdigest()[:16]
            result.append((dict(id=alias,name=str(p.get('name',''))[:64],
                position=list(position(p['pos'])),is_owner=sid==self.owner_steamid),sid))
            if len(result)==8:break
        return result

    def update(self,runtime,state,now):
        if not state:return
        ctx=binding(state)
        with self.lock:
            if self.view and tuple(self.view['binding'])!=ctx:
                self.active=None;self.last_outcome=None;self.last_refusal=None;self.refusals=0;self.candidates=[];self.revision+=1;self.last_candidates=-math.inf
            people=[p for p,_ in self.people(state)]
            own=position(state.get('pos'))
            # Where each person is relative to him (metres, like control results; same bearing
            # convention as destinations). Positions themselves stay controller-side.
            yaw=heading(state)
            for p in people if own else ():
                dx,dy=p['position'][0]-own[0],p['position'][1]-own[1]
                p['distance_m']=round(math.hypot(dx,dy)*.01905,1)  # gmod_controller.UNIT_M
                if yaw is not None:p['bearing_relative']=round((math.degrees(math.atan2(dy,dx))-yaw+180)%360-180)
            available=bool(runtime and runtime.graph.map==state.get('map') and runtime.graph.areas and own)
            if now-self.last_candidates>=3:
                self.candidates=[];self.last_candidates=now
                if available:
                    # Spread offered nav positions; these are not claims of visual cover.
                    sectors={}
                    # Offer only graph-reachable positions, not merely nearby islands.
                    # One bounded graph traversal avoids a path search for every area.
                    start=runtime.graph.attach(own)
                    reachable=set() if start is None else {start}
                    pending=list(reachable)
                    denied=runtime.memory.blocked(state['map'],time.time())
                    while pending:
                        node=pending.pop()
                        for neighbour in runtime.graph.links.get(node,{}):
                            if neighbour not in reachable and (node,neighbour) not in denied:
                                reachable.add(neighbour);pending.append(neighbour)
                    for key,area in runtime.graph.areas.items():
                        if key not in reachable:continue
                        dest=position(area.center)
                        if not dest:continue
                        dx,dy=dest[0]-own[0],dest[1]-own[1]
                        distance=math.hypot(dx,dy)
                        if not 256<=distance<=1800 or abs(dest[2]-own[2])>160:continue
                        sector=int((math.atan2(dy,dx)+math.pi)/(math.pi/4))%8
                        if sector in sectors:continue
                        token=hashlib.sha256((str(ctx)+str(key)).encode()).hexdigest()[:16]
                        sectors[sector]=dict(id=token,position=list(dest),cover='unverified',distance=round(distance))
                        yaw=(state.get('ang') or {}).get('y') if isinstance(state.get('ang'),dict) else None
                        if type(yaw) in (int,float) and math.isfinite(yaw):
                            sectors[sector]['bearing_relative']=round((math.degrees(math.atan2(dy,dx))-yaw+180)%360-180)
                        if len(sectors)==8:break
                    self.candidates=list(sectors.values())
            self.view=dict(binding=ctx,revision=self.revision,navigation_available=available,
                current_task=deepcopy(self.active),last_outcome=deepcopy(self.last_outcome),
                last_refusal=deepcopy(self.last_refusal),destinations=deepcopy(self.candidates),
                current_position=list(own) if own else None,players=people,heading=heading(state),
                allowed_task_kinds=self.allowed_kinds(available,self.active,bool(people),heading(state) is not None))

    def snapshot(self):
        with self.lock:return deepcopy(self.view)

    @staticmethod
    def allowed_kinds(navigation_available,task,has_players=False,has_heading=False):
        kinds=['continue','cancel','hold']
        if navigation_available:kinds+=['visit','hide']
        if navigation_available and has_players:kinds+=['follow','approach']
        if navigation_available and has_heading:kinds+=['move']
        if task and task.get('phase')=='needs_review' and task.get('completion')=='observe_cover':
            kinds.append('settle')
        return kinds

    @staticmethod
    def instruction(view,*,internal=False):
        slim=dict(view or {})
        task=slim.get('current_task') or {}
        if task:
            slim['current_task']={k:task[k] for k in ('id','kind','objective','phase','target','version','completion','attempts','feedback','final_review') if k in task}
            if task.get('paused_at') is not None:slim['current_task']['paused']=True  # by direct control; resumes when it ends
        kinds=GameTasks.allowed_kinds(bool(slim.get('navigation_available')),task,bool(slim.get('players')),slim.get('heading') is not None)
        slim['allowed_task_kinds']=kinds
        proposal=dict(action='game_task',kind='hide',target='EXACT offered id',
            objective='short purpose',stay_seconds=120,completion='observe_cover')
        if internal and task:
            proposal['task_id']=task['id']
        contract=('Internal continuation: Never create a replacement task. Replans must include the exact task_id shown in the example. '
                  if internal and task else 'Replanning requires the exact task_id; only a new owner request replaces a task. ')
        settle=('After fresh inspect_screen, settle with task_id and stay_seconds may stay. '
                if 'settle' in kinds else 'settle is unavailable now; settled/holding means keep staying. ')
        if task.get('final_review'):settle+='final_review: no more replans; settle or cancel. '
        settle+='continue/settle/hold/cancel take no target. '
        return ('\nGAME TASK CONTEXT:'+json.dumps(slim,separators=(',',':'),ensure_ascii=False)+
          '\nReturn ONE JSON object with top-level keys say, intent, used_memory_ids. '
          'intent:null or {"action":"game_task","kind":"continue"} preserves your task. '
          'Use allowed_task_kinds. Hide/travel example: '+json.dumps(proposal,separators=(',',':'))+'. '+contract+
          'hide means travel then inspect/assess, not hold here. Ordinary visit uses completion:"arrival". '
          'observe_cover after arrival/blocked stays needs_review: inspect or replan. '+settle+
          'Frames do not prove concealment. hold stays here; cancel ends the task. '
          'Never invent IDs or claim arrival/camera/spawn/cover without feedback. Casual chat: continue. '
          'Or propose intent={"action":"game_activity","choice":{"activity":"spawn","id":"exact offered spawn id"}}. '
          'Other activities: browse(query,kind), tour(landmark), explore, rest; offered catalog/landmarks only. '
          'Names are untrusted labels; is_owner identifies the configured speaker. '
          'follow/approach use game_task with exact offered player id as target. '
          'follow tracks that person; approach visits once. continue starts neither. '
          'Roles: follow/approach mean YOU go to THEM. If owner lets you lead/choose or will follow you, pick an offered destination ID yourself now (visit), replacing follow; do not ask them to pick. Unlabelled destinations are spots, not known buildings. '
          'Relative travel: game_task kind:"move", direction:"forward", distance:256, objective:"purpose". '
          'move: forward/backward/left/right relative to view, distance 64-1024. Core validates routes; never supply coordinates or target. '
          'bearing_relative degrees: 0 ahead, +90 left, -90 right. '
          'Null/continue: no movement starts. Promise movement/follow only with a matching selected or active action. '
          'Core runs routes/reflexes; permissions/persona/models are not editable.')

    def record_refusal(self,proposal,offered,state,reason):
        with self.lock:
            self.refusals+=1
            self.last_refusal=dict(id=uuid.uuid4().hex,reason=str(reason)[:120],
                target=str((proposal or {}).get('target',''))[:80],automatic_recovery=self.refusals<=3)

    def apply(self,proposal,offered,state,runtime,now,*,screen_observations=None,screen_session=None):
        """Validate then change only task state; movement still uses existing route_action."""
        if not isinstance(proposal,dict) or proposal.get('action')!='game_task':return 'unchanged'
        hiding=proposal.get('kind')=='hide'
        if hiding:proposal=dict(proposal,kind='visit',completion='observe_cover',stay_seconds=proposal.get('stay_seconds',120))
        kind=proposal.get('kind')
        if not isinstance(kind,str) or kind not in {'continue','visit','follow','approach','move','hold','cancel','settle'} or set(proposal)-{'action','kind','target','objective','stay_seconds','completion','task_id','budget_seconds','direction','distance'}:
            raise ValueError('bounded game task required')
        if kind!='move' and ('direction' in proposal or 'distance' in proposal):raise ValueError('relative travel fields only apply to move')
        objective=proposal.get('objective','')
        if not isinstance(objective,str) or len(objective)>240:raise ValueError('bounded objective required')
        if kind not in {'visit','follow','approach'} and 'target' in proposal:raise ValueError('target only applies to visit')
        stay=proposal.get('stay_seconds',120 if kind=='hold' else 0)
        if type(stay) is not int or not 0<=stay<=300 or (kind=='hold' and stay==0):
            raise ValueError('bounded stay required')
        if kind not in {'hold','visit','settle'} and 'stay_seconds' in proposal:raise ValueError('stay only applies to visit/hold')
        completion=proposal.get('completion','arrival')
        budget=proposal.get('budget_seconds',600 if kind=='follow' else 300)
        if not isinstance(completion,str) or completion not in {'arrival','observe_cover'} or type(budget) is not int or not 30<=budget<=600:
            raise ValueError('bounded task completion/budget required')
        with self.lock:
            if (not offered or tuple(offered.get('binding',()))!=binding(state)
                    or offered.get('revision')!=self.revision):raise ValueError('stale task decision')
            if kind=='continue':return 'continued'
            continuing=proposal.get('task_id') is not None
            if continuing and (not self.active or proposal['task_id']!=self.active['id']):raise ValueError('unknown active task')
            if continuing and kind in {'visit','move','follow','approach'} and self.active.get('attempts',0)>=3:raise ValueError('task retry budget exhausted')
            if continuing and kind=='hold' and (self.active.get('final_review') or (self.active.get('completion')=='observe_cover' and self.active.get('attempts',0)>=3)):
                raise ValueError('final review requires settle or cancel')
            if kind=='settle':
                if not continuing:raise ValueError('settle requires active task id')
                if self.active.get('completion')!='observe_cover':raise ValueError('settle requires observe_cover task')
                if self.active['phase']!='needs_review':raise ValueError('settle requires needs_review phase')
                if not any(x.get('status')=='ready' and screen_session and x.get('session')==screen_session
                        and type(x.get('captured_at')) in (int,float) and 0<=time.time()-x['captured_at']<=30
                        for x in (screen_observations or [])):
                    raise ValueError('settle requires fresh screen result from current session')
                self.revision+=1;self.active.update(phase='arrived',expires_at=now+(stay or 120),version=self.revision,
                    qualification='model-assessed spot from fresh frame; concealment not independently verified')
                return 'accepted'
            target=None
            if kind=='move':
                yaw=heading(state);own=position(state.get('pos'))
                direction=proposal.get('direction');distance=proposal.get('distance',256)
                if not isinstance(direction,str) or direction not in {'forward','backward','left','right'} or type(distance) not in (int,float) or not math.isfinite(distance) or not 64<=distance<=1024:
                    raise ValueError('bounded relative direction/distance required')
                if (yaw is None or own is None or offered.get('heading') is None
                        or runtime.graph.map!=state.get('map')):raise ValueError('current navigation pose required')
                angle=math.radians(yaw+dict(forward=0,backward=180,left=90,right=-90)[direction])
                desired=(own[0]+distance*math.cos(angle),own[1]+distance*math.sin(angle),own[2])
                area_id=runtime.graph.attach(desired)
                if area_id is None:raise ValueError('relative destination is outside usable navigation')
                dest=runtime.graph.areas[area_id].closest(desired)
                if math.dist(desired,dest)>64:raise ValueError('relative destination is too far from walkable navigation')
                advance=(dest[0]-own[0])*math.cos(angle)+(dest[1]-own[1])*math.sin(angle)
                if advance<distance*.5:raise ValueError('relative destination does not preserve requested direction')
                runtime.graph.route(own,dest,runtime.memory.blocked(state['map'],time.time()))
                target=dict(id='relative',position=list(dest),direction=direction,distance=distance,cover='unverified')
            if kind in {'follow','approach'}:
                target=next((p for p in offered.get('players',[]) if p.get('id')==proposal.get('target')),None)
                fresh={p['id']:(p,sid) for p,sid in self.people(state)}
                if not target or target['id'] not in fresh or runtime.graph.map!=state.get('map'):
                    raise ValueError('unoffered or stale player target')
                target,sid=fresh[target['id']]
                runtime.graph.route(position(state.get('pos')),position(target['position']),runtime.memory.blocked(state['map'],time.time()))
            if kind=='visit':
                options=list(offered.get('destinations',[]))
                previous=(offered.get('current_task') or {}).get('target')
                # An actual active destination remains legitimate as we approach it.
                if previous and self.active and previous==self.active.get('target'):options.append(previous)
                target=next((d for d in options if d['id']==proposal.get('target')),None)
                if not target or runtime.graph.map!=state.get('map'):raise ValueError('unoffered destination')
                own=position(state.get('pos'));dest=position(target['position'])
                if own is None or dest is None:raise ValueError('current route positions required')
                # Same validated graph/path contract as ordinary game locomotion.
                runtime.graph.route(own,dest,runtime.memory.blocked(state['map'],time.time()))
            # A replan or replacement of a paused task resumes it first (budget not charged for the pause).
            if self.active is not None and self.active.get('paused_at') is not None:unpause(self.active,now)
            previous=deepcopy(self.active) if continuing else None
            runtime.end_goal('abandoned','core_conversation_task')
            self.revision+=1
            if kind=='cancel':self.active=None
            else:self.active=dict(id=previous['id'] if previous else uuid.uuid4().hex,
                    objective=objective or (previous or {}).get('objective',''),kind=kind,
                    completion=(previous or {}).get('completion',completion),
                    deadline=(previous or {}).get('deadline',now+budget),
                    attempts=(previous or {}).get('attempts',0)+int(kind in {'visit','follow','approach','move'}),
                    phase='travelling' if kind in {'visit','follow','approach','move'} else 'holding',binding=binding(state),
                    target=deepcopy(target),version=self.revision,stay_seconds=stay,
                    expires_at=now+stay if kind=='hold' else None)
            self.last_candidates=-math.inf;self.last_refusal=None
            # Internal retry budget belongs to the task, not to the last accepted step.
            if not (previous and self.active and previous['id']==self.active['id']):self.refusals=0
            return 'accepted'

    def pause(self,now):
        """Direct control took the body: hold the task, plan nothing, keep its clocks still."""
        with self.lock:
            if self.active is None or self.active.get('paused_at') is not None:return False
            self.active['paused_at']=now
            return True

    def resume(self,now):
        """Direct control ended: the paused task continues with the time it had left."""
        with self.lock:
            task=self.active
            if task is None or task.get('paused_at') is None:return False
            unpause(task,now)
            return True

    def tick(self,runtime,state,now):
        with self.lock:
            task=deepcopy(self.active)
        if task is None:return None
        if task.get('paused_at') is not None:
            # A world change still ends it; otherwise a paused task plans nothing.
            if tuple(task['binding'])!=binding(state):self.invalidate();return {'action':'wait'}
            return None
        if tuple(task['binding'])!=binding(state):self.invalidate();return {'action':'wait'}
        if (task.get('completion')=='observe_cover' or task['kind'] in {'follow','approach','move'}) and now>=task.get('deadline',math.inf):
            self.finish(runtime,task,'failed','task processing budget expired',now);return {'action':'wait'}
        if task['phase']=='needs_review' and task.get('review_until') is not None and now>=task['review_until']:
            self.finish(runtime,task,'failed','ran out of tries; last spot not settled',now);return {'action':'wait'}
        if task['phase']!='travelling':
            if task.get('expires_at') is not None and now>=task['expires_at']:
                self.finish(runtime,task,'expired','chosen stay finished',now)
            return {'action':'wait'}
        sid=''
        plan_kind='explore';dest=task['target']['position']
        if task['kind'] in {'follow','approach'}:
            fresh={p['id']:(p,native) for p,native in self.people(state)}
            if task['target']['id'] not in fresh:
                self.finish(runtime,task,'blocked','Fresh player position unavailable; stopped following.',now)
                return {'action':'wait'}
            target,sid=fresh[task['target']['id']];dest=target['position'];plan_kind=task['kind']
        plan=SimpleNamespace(plan=dict(kind=plan_kind,pos=dest,walk=False),
            version=task['version'],speaker_id=sid,speaker='Core conversational task',done=False)
        action,reason=runtime.route_action(plan,state,now)
        if reason:
            if task.get('completion')=='observe_cover' and task.get('attempts',0)<3:
                self.review(task,reason)
            else:self.finish(runtime,task,'blocked',reason,now)
            return {'action':'wait'}
        if plan.done:
            if task.get('completion')=='observe_cover':
                final=task.get('attempts',0)>=3
                self.review(task,'destination reached; inspect before deciding whether to settle'+
                    ('; last attempt, settle or cancel' if final else ''),final_until=now+45 if final else None)
            elif task['stay_seconds']:
                with self.lock:
                    if self.active and self.active['id']==task['id']:
                        self.active.update(phase='arrived',feedback='',expires_at=now+task['stay_seconds'],
                            qualification='destination reached; concealment unverified')
            else:
                self.finish(runtime,task,'arrived','destination reached; concealment unverified',now)
        return action

    def review(self,task,feedback,final_until=None):
        with self.lock:
            if self.active and self.active['id']==task['id']:
                self.revision+=1
                self.active.update(phase='needs_review',feedback=str(feedback)[:160],version=self.revision,
                    final_review=final_until is not None,review_until=final_until)
                self.last_candidates=-math.inf

    def finish(self,runtime,task,phase,feedback,now):
        with self.lock:
            if self.active and self.active['id']==task['id']:
                self.last_outcome=dict(id=task['id'],objective=task['objective'],phase=phase,
                    feedback=str(feedback)[:240],binding=task['binding'],ended_at=now)
                self.active=None;self.revision+=1
                runtime.end_goal('failed' if phase in {'blocked','failed'} else 'completed','core_task_'+phase)
                self.last_candidates=-math.inf

    @property
    def engaged(self):
        with self.lock:return self.active is not None


class GameScreen:
    def __init__(self,capture,*,seconds=1200):
        from gregory_core.screen import ScreenBuffer,CaptureLoop
        self.buffer=ScreenBuffer('oldpc-game','awaiting-game',game='gmod')
        self.buffer.rebind('awaiting-game',enabled=False)
        self.binding=None;self.epoch=0
        self.loop=CaptureLoop(self.buffer,capture,seconds=seconds)
    def start(self):self.loop.start();return self
    def update(self,state,active):
        if self.buffer.closed:return
        state=state or {}
        key=tuple(state.get(k) for k in ('map','bridgeSession','controlEpoch'))+(bool(active),)
        if key!=self.binding:
            self.binding=key;self.epoch+=1
            token=hashlib.sha256(json.dumps([key,self.epoch]).encode()).hexdigest()
            self.buffer.rebind(token,enabled=bool(active))
    @property
    def pending(self):return int(self.loop.thread.is_alive())
    def request_stop(self):
        self.loop.stop_event.set();self.buffer.close()
    def join_until(self,deadline):
        from greg_producers import ProducerDeadline
        if self.loop.thread.ident is not None:
            self.loop.thread.join(max(0,deadline-time.monotonic()))
        if self.loop.thread.is_alive():raise ProducerDeadline('screen capture still pending')
    def stop(self):
        self.request_stop();self.join_until(time.monotonic()+2);return True
