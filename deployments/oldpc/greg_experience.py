"""Passive collector-thread experience tracking. Never changes Runtime or commands."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import replace
import math
import time

from greg_events import ControlContext, TraceContext, new_id, sanitize


class SafeTracker:
    """A failing observer can lose evidence, never change the observed operation."""
    def __init__(self, tracker): object.__setattr__(self, '_tracker', tracker)
    def __getattr__(self, name):
        value = getattr(self._tracker, name)
        if not callable(value): return value
        def call(*args, **kwargs):
            try: return value(*args, **kwargs)
            except Exception:
                self._tracker.sink.record('recorder.degraded', {'reason':'observer_error'}, priority='critical')
                return None
        return call
    def __setattr__(self, name, value): setattr(self._tracker, name, value)


def point(value):
    try:
        result = tuple(float(value[k]) for k in ('x','y','z'))
        return result if all(math.isfinite(v) for v in result) else None
    except (KeyError, TypeError, ValueError): return None


class ExperienceTracker:
    def __init__(self, sink, *, clock=time.time_ns, mono=time.monotonic_ns):
        self.sink, self.clock, self.mono = sink, clock, mono
        self.run_id = sink.run_id
        self.samples, self.episodes = OrderedDict(), OrderedDict()
        self.routes, self.goals = OrderedDict(), OrderedDict()
        self.latest = None
        self.last_receive = None
        self.last_sample_key = None
        self.last_periodic = -10**20
        self.gap = False
        self.active_trace = None
        self.scope_trace = None
        self.current_control = ControlContext()
        self.last_heartbeat = -10**20

    def _emit(self, kind, payload, *, trace=None, refs=(), priority='critical', **kwargs):
        return self.sink.record(kind, payload, trace=trace, observation_ids=refs,
                                priority=priority, **kwargs)

    def _bounded(self, table, key, value, limit=256):
        table[key] = value; table.move_to_end(key)
        while len(table) > limit: table.popitem(last=False)

    def _new_episode(self, trace, now):
        if trace.correlation_id not in self.episodes:
            self.episodes[trace.correlation_id] = dict(trace=trace, started=now, closed=False,
                                                    action=None, previous=None, near_at=None,
                                                    last_feedback=None, pre=None, target=None, assisted=False,
                                                    near_oid=None, failure_observed=False)
            if len(self.episodes) > 128:
                key, _ = next(iter(self.episodes.items()))
                self.close(key, 'resource_limit'); self.episodes.pop(key, None)
        return self.episodes[trace.correlation_id]

    def _pin(self, oid):
        sample = self.samples.get(oid)
        if sample is None: return
        if sample.get('event') is None:
            sample['event'] = self.sink.factory.make('observation.accepted', sample['payload'],
                                      trace=sample['trace'], event_id=oid,
                                      wall_ns=sample['wall'], mono_ns=sample['mono'])
        self.sink.emit(sample['event'], priority='critical')

    def accepted_state(self, state, *, wall_ns=None, mono_ns=None):
        wall = self.clock() if wall_ns is None else wall_ns
        now = self.mono() if mono_ns is None else mono_ns
        control = ControlContext.from_state(state, self.run_id, self.current_control.intent_version)
        sample_key = (control, state.get('seq'), state.get('t'))
        if sample_key == self.last_sample_key: return self.latest
        old = self.samples.get(self.latest)
        if old and control != self.current_control:
            for cid, episode in list(self.episodes.items()):
                if not episode['closed'] and episode['trace'].control != control:
                    self.close(cid, 'context_changed')
            self.active_trace = None
        if old and control == self.current_control:
            oldseq = old['payload'].get('seq'); seq = state.get('seq')
            if isinstance(seq,int) and isinstance(oldseq,int) and seq > oldseq+1:
                self._emit('telemetry.sequence_gap', {'skipped': seq-oldseq-1, 'first_sequence': oldseq+1,
                           'last_sequence': seq-1}, trace=self.active_trace)
        self.current_control = control
        oid = new_id()
        payload = {k:state[k] for k in ('seq','t','serverTime','pos','velocity','ang','menu','enabled','dead',
                    'grounded','locomotion','rescue','capabilities','clearance') if k in state}
        payload = sanitize(payload)
        self.samples[oid] = dict(payload=payload, wall=wall, mono=now, event=None,
                                trace=TraceContext(self.run_id,None,control=control))
        self.latest = oid; self.last_sample_key = sample_key; self.last_receive = now
        while len(self.samples) > 32: self.samples.popitem(last=False)
        if self.gap:
            self._emit('telemetry.resumed', {'reason':'fresh_sample'}, trace=self.active_trace)
            self.gap = False
        if now-self.last_periodic >= 1_000_000_000:
            self._pin(oid); self.last_periodic = now
        for cid, episode in list(self.episodes.items()):
            if not episode['closed'] and episode['trace'].control == control and episode['action']:
                self._feedback(episode, state, oid, now)
        return oid

    def begin_decision(self, *, lane='action', template_version=None, control=None):
        if self.latest: self._pin(self.latest)
        trace = TraceContext(self.run_id,new_id(),decision_id=new_id(),
                             control=control or self.current_control,
                             observation_ids=(self.latest,) if self.latest else (),
                             lane=lane,template_version=template_version)
        episode = self._new_episode(trace,self.mono())
        event = self._emit('decision.requested', {'lane':lane,'template_version':template_version,
                           'origin':'deterministic' if lane=='deterministic' else 'model'}, trace=trace)
        if event:
            trace = replace(trace,causation_id=event.as_dict()['event_id'])
            episode['trace'] = trace
        return trace

    def decision_result(self, trace, *, accepted, reason, parsed_summary=None):
        self._emit('decision.applied' if accepted else 'decision.discarded',
                   {'accepted':accepted,'reason':reason,'parsed':parsed_summary or {}},trace=trace)
        if not accepted: self.close(trace.correlation_id,reason)
        elif trace.lane != 'social': self.active_trace = trace

    def directive(self, version):
        if self.active_trace:
            self.close(self.active_trace.correlation_id,'superseded_by_chat')
        self.current_control = replace(self.current_control,intent_version=version)
        self.active_trace = None

    def runtime_event(self, event):
        kind = event.get('kind')
        if kind == 'state':
            self.accepted_state(event['state']); return
        trace = self.scope_trace or self.active_trace
        native = event.get('id')
        goal_key = (event.get('map'),tuple(event.get('context',())),native)
        if kind == 'goal' and goal_key in self.goals:
            trace = self.goals[goal_key]
        if trace is None:
            # Preexisting goals: honest origin, never synthesize a missing model decision.
            trace = self.begin_decision(lane='deterministic',template_version='preexisting.v1')
        if kind == 'goal':
            trace = replace(trace,goal_id=self.goals[goal_key].goal_id if goal_key in self.goals else new_id())
            self._bounded(self.goals,goal_key,trace)
            if trace.correlation_id in self.episodes: self.episodes[trace.correlation_id]['trace'] = trace
            self._emit('goal.observed', {**event,'native_goal_id':native,'native_status':event.get('status')},trace=trace)
            if event.get('status') in {'failed','abandoned','rejected'}:
                # A source failure is recorded separately from independent world evidence.
                episode=self.episodes.get(trace.correlation_id,{})
                failed=event.get('status')=='failed' and episode.get('failure_observed')
                self.close(trace.correlation_id,event.get('reason','source_terminal'),
                           'failed' if failed else 'unknown','fail' if failed else 'inconclusive')
        elif kind == 'route':
            self._emit('route.observed',event,trace=trace)

    def dispatch(self, payload, *, trace=None, write_result='written', reason='', retries=0, speech_trace=None):
        trace = trace or self.active_trace
        action = payload.get('action',{})
        act = action.get('action')
        if trace is None:
            # Idle renewal/wait is telemetry, not a new fictitious goal each tick.
            if act == 'wait': return
            trace = self.begin_decision(lane='deterministic',template_version='literal.v1')
            self.decision_result(trace,accepted=True,reason='deterministic',parsed_summary=action)
        if trace.correlation_id not in self.episodes: return
        episode = self.episodes[trace.correlation_id]
        if episode['closed'] and act == 'wait': return
        if episode['closed']:
            prior = trace.correlation_id
            trace = replace(trace,correlation_id=new_id(),decision_id=None,action_id=None,causation_id=None)
            episode = self._new_episode(trace,self.mono())
            self._emit('decision.requested',{'origin':'preexisting','continuation_of':prior},trace=trace)
        route = action.get('id') if act=='navigate' else None
        route_key = (trace.control,route) if route else None
        if route_key and route_key in self.routes:
            action_id = self.routes[route_key]
        else:
            action_id = new_id()
            if route_key: self._bounded(self.routes,route_key,action_id)
        trace = replace(trace,action_id=action_id)
        params = dict(action)
        # Never persist the native routing identity; keep a per-run alias only.
        params.pop('gazeSteamID',None)
        parameters_complete = sanitize(params,visible=self.sink.factory.visible) == params
        if 'gazeSteamID' in action: parameters_complete = False
        record = dict(command_session=payload.get('session'),command_sequence=payload.get('seq'),
                      expires=payload.get('expires'),action=params,native_route_id=route,
                      dispatch_id=new_id(),write_status=write_result,reason=reason,retries=retries,
                      parameters_complete=parameters_complete)
        if speech_trace is not None:
            record['links']=[{'relation':'compound_speech','to_id':speech_trace.correlation_id,'to_kind':'correlation'}]
        if self.latest: self._pin(self.latest)
        refs = (self.latest,) if self.latest else ()
        self._emit('action.requested', record,trace=trace,refs=refs)
        kind = {'written':'action.dispatch','failed':'action.write_failed','suppressed':'action.suppressed'}[write_result]
        self._emit(kind,record,trace=trace,refs=refs)
        if speech_trace is not None: self.close(speech_trace.correlation_id,'speech_submitted')
        if write_result != 'written':
            self.close(trace.correlation_id,'write_'+write_result); return
        if act=='navigate':
            points = action.get('points',[])
            episode.update(trace=trace,action=route,pre=episode['pre'] or self.latest,
                           target=point(points[-1]) if points else None)
            if trace.lane != 'social': self.active_trace = trace
        elif act not in {'say','wait','gaze'}:
            self.close(trace.correlation_id,'unsupported_primitive')
        elif trace.lane=='social':
            self.close(trace.correlation_id,'speech_submitted')

    def _feedback(self, episode, state, oid, now):
        f = state.get('locomotion') or {}
        if f.get('id') != episode['action']: return
        token = (f.get('id'),f.get('event'))
        trace = episode['trace']
        if token != episode['last_feedback']:
            self._pin(oid)
            self._emit('controller.feedback', {**f,'native_route_id':f.get('id'),'native_status':f.get('status')},
                       trace=trace,refs=(oid,))
            episode['last_feedback'] = token
            if f.get('status') in {'blocked','stuck','no_ground','route_diverged','expired'}:
                episode['failure_observed']=True
                self._emit('outcome.evaluated',{'evaluator':'gmod.controller-failure.v1','world_outcome':'failed',
                           'verdict':'fail','reason':f.get('status')},trace=trace,refs=(oid,))
        pos,target = point(state.get('pos')),episode['target']
        if (state.get('rescue') or {}).get('owned'): episode['assisted'] = True
        if not pos or not target or episode['assisted'] or state.get('menu') or state.get('dead') or not state.get('enabled',True):
            episode['near_at'] = None; return
        old = episode['previous']; episode['previous'] = (state.get('t'),pos,now,oid)
        speed = math.inf
        if old and isinstance(state.get('t'),(float,int)) and isinstance(old[0],(float,int)) and state['t']>old[0]:
            speed = math.dist(pos[:2],old[1][:2])/(state['t']-old[0])
        near = math.dist(pos[:2],target[:2])<=100 and abs(pos[2]-target[2])<48 and speed<=10
        if old and now-old[2]>1_500_000_000: near=False
        if near:
            self._pin(oid)
            if old: self._pin(old[3])
            if episode['near_at'] is None:
                episode['near_at']=now; episode['near_oid']=oid
            elif now-episode['near_at']>=500_000_000:
                refs=tuple(dict.fromkeys(x for x in (episode['pre'],episode['near_oid'],old[3] if old else None,oid) if x))
                self._emit('outcome.evaluated', {'evaluator':'gmod.navigate.proximity.v1','world_outcome':'succeeded',
                           'verdict':'pass','distance':math.dist(pos[:2],target[:2]),'speed':speed,
                           'dwell_seconds':(now-episode['near_at'])/1e9},trace=trace,refs=refs)
                self.close(trace.correlation_id,'verified_arrival','succeeded','pass',refs)
        else: episode['near_at']=episode['near_oid']=None
        # World failure is not inferred just from one blocked route: replanning may recover.

    def close(self, cid, reason, world='unknown', verdict='inconclusive', refs=()):
        episode = self.episodes.get(cid)
        if episode is None or episode['closed']: return
        episode['closed']=True
        if world != 'succeeded':
            self._emit('outcome.evaluated', {'evaluator':'gmod.observation-window.v1',
                       'closure_reason':reason,'world_outcome':world,'verdict':verdict},
                       trace=episode['trace'],refs=refs)
        self._emit('experience.closed',{'closure_reason':reason,'world_outcome':world,'verdict':verdict},
                   trace=episode['trace'],refs=refs)

    def tick(self, *, wall_ns=None, mono_ns=None):
        now=self.mono() if mono_ns is None else mono_ns
        if self.last_receive is not None:
            elapsed=(now-self.last_receive)/1e9
            if elapsed>3 and not self.gap:
                self._emit('telemetry.gap',{'gap_seconds':elapsed},trace=self.active_trace); self.gap=True
            if elapsed>30:
                for cid,e in list(self.episodes.items()):
                    if not e['closed']: self.close(cid,'telemetry_timeout')
        for cid,e in list(self.episodes.items()):
            if not e['closed'] and now-e['started']>600_000_000_000: self.close(cid,'recording_window_elapsed')
        if now-self.last_heartbeat>5_000_000_000:
            self._emit('run.heartbeat', {'last_state_age_seconds':(now-self.last_receive)/1e9 if self.last_receive else None},
                       priority='normal'); self.last_heartbeat=now

    def shutdown(self):
        for cid in list(self.episodes): self.close(cid,'orderly_shutdown')
