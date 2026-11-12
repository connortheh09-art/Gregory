import concurrent.futures
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deployments'/'oldpc'))
from greg_events import EventFactory, TraceContext, ControlContext, new_id, current_trace, observed, run_traced


class Events(unittest.TestCase):
    def setUp(self): self.factory=EventFactory(new_id(),'session')

    def test_unknown_schema_or_event_rejected(self):
        with self.assertRaises(ValueError): self.factory.make('fake.event',{})

    def test_metadata_never_retains_untrusted_fields_or_text(self):
        e=self.factory.make('decision.response',{'headers':{'Authorization':'secret'},'text':'private conversation',
             'content':'<think>secret reasoning</think>','model':'local','pos':{'x':1,'y':2,'z':3}}).encoded
        self.assertNotIn('private conversation',e);self.assertNotIn('secret',e)
        self.assertIn('local',e);self.assertIn('content_omitted',e)

    def test_visible_policy_drops_credentials_and_inline_reasoning(self):
        f=EventFactory(new_id(),'s',text='visible')
        for text in ['<think>private','Authorization: Bearer abc','api_key=xyz','https://user:pass@host']:
            event=f.make('decision.response',{'content':text}).encoded
            self.assertNotIn(text,event)
        self.assertIn('visible reply',f.make('decision.response',{'content':'visible reply'}).encoded)

    def test_frozen_event_does_not_follow_payload_mutation(self):
        payload={'pos':{'x':1}};e=self.factory.make('observation.accepted',payload)
        payload['pos']['x']=200
        self.assertEqual(e.as_dict()['payload']['pos']['x'],1)

    def test_bounds_finite_values_and_unique_sequences_concurrent(self):
        e=self.factory.make('action.dispatch',{'action':{'points':[{'x':1}]*1000},'speed':float('nan')})
        self.assertEqual(len(e.as_dict()['payload']['action']['points']),256)
        self.assertNotIn('speed',e.as_dict()['payload'])
        with concurrent.futures.ThreadPoolExecutor(4) as pool:
            events=list(pool.map(lambda _:self.factory.make('run.heartbeat',{}).as_dict(),range(100)))
        self.assertEqual(len({e['event_id'] for e in events}),100)
        self.assertEqual(len({e['source_sequence'] for e in events}),100)

    def test_worker_scope_does_not_leak_and_preserves_result_exception(self):
        class Sink:
            def record(self,*a,**k): return current_trace().decision_id
        trace=TraceContext(self.factory.run_id,new_id(),decision_id=new_id())
        self.assertEqual(run_traced(trace,Sink(),observed,'decision.parsed',{}),trace.decision_id)
        self.assertIsNone(current_trace())
        failure=RuntimeError('original')
        def fail(): raise failure
        with self.assertRaises(RuntimeError) as caught: run_traced(trace,Sink(),fail)
        self.assertIs(caught.exception,failure);self.assertIsNone(current_trace())

    def test_control_identity_is_pseudonymous(self):
        state={'steamid':'STEAM_PRIVATE','map':'city','bridgeSession':'bridge','controlEpoch':1}
        c=ControlContext.from_state(state,self.factory.run_id)
        self.assertNotIn('STEAM_PRIVATE',json.dumps(c.as_dict()))


if __name__=='__main__': unittest.main()
