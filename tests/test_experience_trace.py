import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deployments'/'oldpc'))
from greg_events import run_traced
from greg_experience import ExperienceTracker,SafeTracker
from greg_recorder import Recorder,open_reader,get_experience,read_events
from greg_model import post_chat
from greg_playercore import Runtime,EventMemory


def state(seq=1,t=1,x=0,route='route',event=1,epoch=1):
    return dict(steamid='private-steam-id',map='city',bridgeSession='bridge',controlEpoch=epoch,
                serverTime=100,t=t,seq=seq,pos=dict(x=x,y=0,z=0),menu=False,dead=False,enabled=True,
                capabilities={'playercore':True},locomotion={'id':route,'event':event,'status':'moving'})


class Trace(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'history.sqlite3'
        self.sink=Recorder(self.path,'s');self.addCleanup(self.sink.close);self.sink.wait_ready()
        self.now=1_000_000_000
        self.tracker=ExperienceTracker(self.sink,clock=lambda:100_000_000_000,mono=lambda:self.now)

    def sample(self,seq,t,x,**kwargs):
        self.now=int(t*1e9)
        return self.tracker.accepted_state(state(seq,t,x,**kwargs),mono_ns=self.now)

    def start(self):
        self.sample(1,1,0)
        trace=self.tracker.begin_decision(lane='agenda',template_version='agenda.v1')
        response=Mock();response.json.return_value={'model':'local','choices':[{'message':{'content':'{"activity":"explore"}'},'finish_reason':'stop'}],
                                                   'usage':{'total_tokens':42}}
        with patch.dict(sys.modules,requests=Mock(post=Mock(return_value=response))):
            run_traced(trace,self.sink,post_chat,'not-a-network-call',json={'model':'local','max_tokens':32})
        self.tracker.decision_result(trace,accepted=True,reason='accepted',parsed_summary={'activity':'explore'})
        command={'seq':1,'session':'s','expires':102,'action':{'action':'navigate','id':'route',
                  'points':[{'x':500,'y':0,'z':0,'radius':24}],'lease':2.5}}
        self.tracker.dispatch(command,trace=trace)
        return trace,command

    def result(self,trace):
        self.sink.close()
        with open_reader(self.path) as db: return get_experience(db,trace.correlation_id)

    def test_model_navigation_chain_survives_reopen(self):
        trace,command=self.start()
        self.sample(2,2,500,event=2)
        self.sample(3,2.5,500,event=3)
        self.sample(4,3,500,event=4)
        result=self.result(trace)
        self.assertEqual(result['world_outcome'],'succeeded');self.assertTrue(result['trace_complete'])
        dispatch=next(e for e in result['events'] if e['event_type']=='action.dispatch')
        self.assertEqual(dispatch['payload']['action'],command['action'])
        self.assertEqual(result['unresolved_refs'],[])
        self.assertNotIn('private-steam-id',json.dumps(result))

    def test_five_minute_old_success_survives_recorder_restart(self):
        import time
        old=time.time_ns()-300_000_000_000
        self.sink.factory.clock=lambda:old
        trace,_=self.start();self.sample(2,2,500);self.sample(3,2.5,500);self.sample(4,3,500)
        self.sink.close()
        second=Recorder(self.path,'restart');second.wait_ready();second.close()
        with open_reader(self.path) as db:
            result=get_experience(db,trace.correlation_id)
            self.assertTrue(result['trace_complete']);self.assertEqual(result['world_outcome'],'succeeded')
            self.assertTrue(any(e['received_at_utc']<second.health()['started_at_utc'] for e in result['events']))

    def test_write_success_never_implies_world_success(self):
        trace,_=self.start();result=self.result(trace)
        self.assertEqual(result['world_outcome'],'unknown');self.assertFalse(result['trace_complete'])

    def test_recording_timeout_does_not_touch_live_goal(self):
        trace,_=self.start();self.now=32_000_000_000;self.tracker.tick()
        result=self.result(trace)
        self.assertEqual(result['closure_reason'],'telemetry_timeout')
        self.assertEqual(result['world_outcome'],'unknown')

    def test_gap_prevents_dwell_success(self):
        trace,_=self.start();self.sample(2,2,500);self.sample(3,2.5,500);self.sample(4,5,500)
        result=self.result(trace);self.assertNotEqual(result['world_outcome'],'succeeded')

    def test_unrelated_epoch_or_route_cannot_complete_action(self):
        traces=[]
        for mode in ('route','epoch'):
            with self.subTest(mode=mode):
                trace,_=self.start()
                kw={'route':'other'} if mode=='route' else {'epoch':2}
                for seq,t in ((2,2),(3,2.5),(4,3)): self.sample(seq,t,500,**kw)
                traces.append(trace)
        self.sink.close()
        with open_reader(self.path) as db:
            for trace in traces: self.assertNotEqual(get_experience(db,trace.correlation_id)['world_outcome'],'succeeded')

    def test_stale_decision_discarded_not_applied(self):
        self.sample(1,1,0);trace=self.tracker.begin_decision(lane='agenda')
        self.tracker.decision_result(trace,accepted=False,reason='stale_or_context')
        result=self.result(trace)
        self.assertEqual(result['closure_reason'],'stale_or_context')
        self.assertNotIn('decision.applied',{e['event_type'] for e in result['events']})

    def test_renewals_keep_action_id_and_idle_does_not_start_episodes(self):
        trace,command=self.start();command['seq']=2;self.tracker.dispatch(command)
        before=len(self.tracker.episodes)
        self.tracker.close(trace.correlation_id,'fixture')
        for seq in range(20): self.tracker.dispatch({'seq':seq,'session':'s','action':{'action':'wait'}})
        self.assertEqual(len(self.tracker.episodes),before)
        result=self.result(trace)
        actions=[e for e in result['events'] if e['event_type']=='action.dispatch']
        self.assertEqual(len({e['action_id'] for e in actions}),1)
        self.assertEqual(len({e['payload']['dispatch_id'] for e in actions}),2)

    def test_safe_observer_failure_does_not_escape(self):
        safe=SafeTracker(self.tracker)
        with patch.object(self.tracker,'tick',side_effect=RuntimeError('private details')):
            self.assertIsNone(safe.tick())

    def test_assisted_travel_is_not_unassisted_navigation_success(self):
        trace,_=self.start()
        for seq,t in ((2,2),(3,2.5),(4,3)):
            self.now=int(t*1e9)
            sample=state(seq,t,500);sample['rescue']={'owned':True}
            self.tracker.accepted_state(sample,mono_ns=self.now)
        self.assertNotEqual(self.result(trace)['world_outcome'],'succeeded')

    def test_missing_pre_observation_blocks_trace_completeness(self):
        trace,_=self.start()
        self.sample(2,2,500);self.sample(3,2.5,500);self.sample(4,3,500)
        result=self.result(trace)
        import sqlite3
        with sqlite3.connect(self.path) as db:
            db.execute('DELETE FROM events WHERE event_id=?',(trace.observation_ids[0],))
        with open_reader(self.path) as db:
            partial=get_experience(db,trace.correlation_id)
            self.assertFalse(partial['trace_complete']);self.assertTrue(partial['unresolved_refs'])

    def test_blocked_route_and_native_goal_failure_record_failed_outcome(self):
        trace,_=self.start()
        self.tracker.runtime_event({'kind':'goal','id':'g','status':'started','map':'city'})
        sample=state(2,2,0);sample['locomotion']['status']='blocked'
        self.now=2_000_000_000;self.tracker.accepted_state(sample,mono_ns=self.now)
        self.tracker.runtime_event({'kind':'goal','id':'g','status':'failed','reason':'route_failed','map':'city'})
        result=self.result(trace)
        self.assertEqual(result['world_outcome'],'failed');self.assertEqual(result['verdict'],'fail')

    def test_source_clock_utc_shift_does_not_advance_deadline(self):
        trace,_=self.start()
        self.tracker.clock=lambda:10**18
        self.now+=1_000_000_000;self.tracker.tick(wall_ns=10**18)
        self.assertFalse(self.tracker.episodes[trace.correlation_id]['closed'])

    def test_conversation_does_not_steal_locomotion_ownership(self):
        trace,_=self.start();active=self.tracker.active_trace
        self.tracker.dispatch({'session':'s','seq':2,'action':{'action':'say','text':'status reply'}})
        self.assertEqual(self.tracker.active_trace,active)
        self.sample(2,2,500);self.sample(3,2.5,500);self.sample(4,3,500)
        self.assertEqual(self.result(trace)['world_outcome'],'succeeded')

    def test_rest_closes_not_applicable_without_repeated_idle_episodes(self):
        self.sample(1,1,0);trace=self.tracker.begin_decision(lane='agenda')
        self.tracker.decision_result(trace,accepted=True,reason='rest')
        for i in range(10): self.tracker.dispatch({'session':'s','seq':i,'action':{'action':'wait'}})
        self.assertEqual(len(self.tracker.episodes),1)
        self.assertEqual(self.result(trace)['world_outcome'],'not_applicable')

    def test_explicit_stop_and_shutdown_are_recorded_without_idle_goals(self):
        self.sample(1,1,0)
        for i in range(10): self.tracker.dispatch({'session':'s','seq':i,'mode':'idle','action':{'action':'wait'}})
        self.assertEqual(len(self.tracker.episodes),0)
        for i in range(10): self.tracker.dispatch({'session':'s','seq':i,'mode':'chat','action':{'action':'wait'}})
        self.assertEqual(len(self.tracker.episodes),1)
        self.tracker.dispatch({'session':'s','seq':20,'mode':'stop','action':{'action':'wait'}})
        self.assertEqual(len(self.tracker.episodes),2)
        self.sink.close()
        with open_reader(self.path) as db:
            for row in db.execute('SELECT world_outcome FROM experiences'): self.assertEqual(row[0],'unknown')

    def test_native_state_gate_rejects_stale_duplicate_and_wrong_actor(self):
        memory=EventMemory(Path(self.tmp.name)/'memory')
        runtime=Runtime(Mock(),memory,observer=self.tracker.runtime_event)
        with patch('builtins.print'):
            self.assertTrue(runtime.observe(state(), 'private-steam-id',100,1))
            latest=self.tracker.latest
            self.assertFalse(runtime.observe(state(), 'private-steam-id',100,1))
            self.assertFalse(runtime.observe(state(seq=2,t=2), 'another-player',100,2))
            self.assertFalse(runtime.observe(state(seq=2,t=2), 'private-steam-id',110,2))
            self.assertEqual(self.tracker.latest,latest)


if __name__=='__main__': unittest.main()
