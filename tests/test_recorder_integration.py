from concurrent.futures import Future
import contextlib
import importlib
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'deployments'/'oldpc'))
sys.modules.setdefault('requests',SimpleNamespace())  # Offline collector import, never a real HTTP call.
import gmod_bridge as bridge
import greg_playercore as core
from greg_events import run_traced,new_id,TraceContext
from greg_recorder import Recorder,open_reader,read_events
from greg_experience import ExperienceTracker


class ImmediateExecutor:
    def __init__(self,**kwargs): pass
    def submit(self,fn,*args,**kwargs):
        future=Future()
        try: future.set_result(fn(*args,**kwargs))
        except Exception as exc: future.set_exception(exc)
        return future
    def shutdown(self,**kwargs): pass


class CollectorIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def command(self,observer=None,action=None,seq=1):
        state=dict(steamid='private',bridgeSession='bridge',controlEpoch=1,pos=dict(x=0,y=0,z=0))
        bridge.write_cmd(self.root/'cmd.json',seq,action or {'action':'navigate','id':'route',
              'points':[{'x':500,'y':0,'z':0}],'lease':2.5},state,'session','idle',observer=observer)
        return json.loads((self.root/'cmd.json').read_text())

    def test_actual_payload_same_with_noop_or_raising_observer(self):
        fixed=1000
        with patch.object(bridge,'p0_trace'),patch.object(bridge.time,'time',return_value=fixed):
            baseline=self.command()
            recorded=[]
            hooked=self.command(lambda payload,**status:recorded.append((payload,status)))
            self.assertEqual(baseline,hooked);self.assertEqual(recorded[0][0],hooked)
            self.assertEqual(recorded[0][1]['write_result'],'written')
            self.assertEqual(baseline,self.command(Mock(side_effect=RuntimeError('fixture'))))

    def test_fallback_and_failed_writes_report_honestly(self):
        records=[]
        with patch.object(bridge,'p0_trace'),patch.object(bridge.os,'replace',side_effect=OSError('locked')):
            self.command(lambda payload,**status:records.append(status))
        self.assertEqual([r['write_result'] for r in records],['written'])
        records.clear()
        with patch.object(bridge,'p0_trace'),patch.object(Path,'write_text',side_effect=OSError('full')),patch.object(bridge.time,'sleep'):
            self.command = lambda *a,**k: None  # Do not try reading a file after intentionally failed writes.
            bridge.write_cmd(self.root/'missing.json',1,{'action':'wait'},
                dict(steamid='private',bridgeSession='b',controlEpoch=1),'s','idle',
                observer=lambda payload,**status:records.append(status))
        self.assertEqual(records[0]['write_result'],'failed');self.assertEqual(records[0]['retries'],6)

    def test_speech_suppression_is_not_dispatched(self):
        records=[]
        bridge.write_cmd(self.root/'never.json',1,{'action':'say','text':'<think>private</think>'},
            dict(steamid='p',bridgeSession='b',controlEpoch=1),'s','chat',
            observer=lambda payload,**status:records.append(status))
        self.assertFalse((self.root/'never.json').exists())
        self.assertEqual(records[0]['write_result'],'suppressed')

    def test_actual_model_return_and_original_exception_preserved(self):
        import greg_model
        r=Recorder(self.root/'history.sqlite3','s');self.addCleanup(r.close)
        trace=TraceContext(r.run_id,new_id(),decision_id=new_id())
        response=Mock();response.json.return_value={'model':'local','choices':[{'message':{'content':'safe'},'finish_reason':'stop'}]}
        body={'model':'local','max_tokens':32}
        post=Mock(return_value=response)
        with patch.dict(sys.modules,requests=SimpleNamespace(post=post)):
            self.assertIs(run_traced(trace,r,greg_model.post_chat,'unused',json=body),response)
        self.assertEqual(post.call_args.kwargs['json'],body)
        failure=OSError('provider unavailable')
        with patch.dict(sys.modules,requests=SimpleNamespace(post=Mock(side_effect=failure))):
            with self.assertRaises(OSError) as caught: run_traced(trace,r,greg_model.post_chat,'unused',json=body)
        self.assertIs(caught.exception,failure)

    def run_collector(self,enabled):
        directory=self.root/('on' if enabled else 'off');directory.mkdir()
        class Clock:
            now=0.
            def sleep(self,n): self.now+=n
        clock=Clock()
        class Tail:
            def __init__(self,path): self.path=path;self.n=0
            def read_new(self):
                if self.path.name!='state.json': return []
                self.n+=1
                return [json.dumps(dict(steamid='actor',bridgeSession='bridge',controlEpoch=1,map='city',
                    serverTime=2000+clock.now,t=clock.now+.01,seq=self.n,pos=dict(x=min(500,int(clock.now*300)),y=0,z=0),
                    enabled=True,dead=False,menu=False,capabilities={'playercore':True},
                    locomotion={'id':'abcdabcdabcd','status':'moving','event':self.n}))]
        graph=SimpleNamespace(map='city',areas={1:SimpleNamespace(center=(500,0,0))},
             route=lambda *a:{'areas':[1],'points':[(500,0,0)],'edges':[None]})
        def decide(self,state,landmarks,events):
            return {'_agenda':True,'choice':{'activity':'explore'},'context':('city','bridge',1),
                    'landmarks':[],'navigation_available':True}
        commands=[]
        original=bridge.write_cmd
        def writer(*args,**kwargs):
            original(*args,**kwargs)
            path=args[0]
            if path.exists(): commands.append(json.loads(path.read_text()))
        argv=['gmod_bridge.py','--data',str(directory),'--steamid','actor','--model','local','--playercore',
              '--no-social','--turns','4','--memory-dir',str(directory/'memory'),
              '--chat-memory',str(directory/'chat-memory.json')]
        if enabled: argv+=['--recorder','--recorder-db',str(directory/'recorder.sqlite3')]
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(sys,'argv',argv))
            stack.enter_context(patch.object(bridge,'Tail',Tail))
            stack.enter_context(patch.object(core.NavGraph,'load',return_value=graph))
            stack.enter_context(patch.object(core,'uuid',SimpleNamespace(uuid4=lambda:SimpleNamespace(hex='abcd'*8))))
            stack.enter_context(patch.object(bridge,'ThreadPoolExecutor',ImmediateExecutor))
            stack.enter_context(patch.object(bridge.Agenda,'decide',decide))
            stack.enter_context(patch.object(bridge,'write_cmd',writer))
            stack.enter_context(patch.object(bridge,'p0_trace'))
            stack.enter_context(patch.object(bridge,'watchdog',lambda:None))
            stack.enter_context(patch.object(bridge.time,'monotonic',lambda:clock.now))
            stack.enter_context(patch.object(bridge.time,'time',lambda:2000+clock.now))
            stack.enter_context(patch.object(bridge.time,'sleep',clock.sleep))
            stack.enter_context(patch.object(bridge.random,'uniform',lambda a,b:(a+b)/2))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            self.assertEqual(bridge.main(),0)
        for c in commands: c.pop('session',None)
        return commands,directory

    def test_full_collector_off_on_action_cadence_equivalence(self):
        baseline,off=self.run_collector(False)
        recording,on=self.run_collector(True)
        self.assertEqual(baseline,recording)
        self.assertFalse((off/'recorder.sqlite3').exists())
        with open_reader(on/'recorder.sqlite3') as db:
            kinds={e['event_type'] for e in read_events(db,limit=1000)['events']}
            self.assertIn('action.dispatch',kinds);self.assertIn('decision.applied',kinds)

    def test_cli_offline_query_export_no_overwrite_and_missing_db(self):
        r=Recorder(self.root/'history.sqlite3','s');r.wait_ready();r.record('run.heartbeat',{});r.close()
        command=[sys.executable,str(ROOT/'tools'/'greg_experience.py'),'--db',str(r.path)]
        result=subprocess.run(command+['events','--limit','100'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr);self.assertIn('database_id',json.loads(result.stdout))
        export=self.root/'export.jsonl'
        result=subprocess.run(command+['export','--run',r.run_id,'--output',str(export)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        original=export.read_bytes()
        result=subprocess.run(command+['export','--run',r.run_id,'--output',str(export)],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0);self.assertEqual(original,export.read_bytes())
        missing=self.root/'missing.sqlite3'
        result=subprocess.run([sys.executable,str(ROOT/'tools'/'greg_experience.py'),'--db',str(missing),'status'],capture_output=True)
        self.assertEqual(result.returncode,3);self.assertFalse(missing.exists())


if __name__=='__main__': unittest.main()
