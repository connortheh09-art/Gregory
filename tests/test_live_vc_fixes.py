"""Regression checks for observed live failures, without Discord/game/model calls."""
import ast
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'deployments/oldpc')]
import test_recorder_integration
from greg_supervised import SessionWindow, drain_pending
from gregory_core.runtime import Core, LMStudioProvider
from test_supervised_bridge import exercise_chat
import gmod_bridge as bridge
from greg_sapi4 import synthesize, wav_to_discord


class ExpiryTests(unittest.TestCase):
    def test_twenty_second_request_at_t_minus_five_drains_without_new_chat(self):
        window = SessionWindow(0, 300)
        self.assertEqual(window.phase(295, 1), 'active')
        self.assertEqual(window.phase(300, 1), 'draining')
        _, _, lane, writes = exercise_chat(Path(bridge.__file__).read_text(),
            'Nice prop.', supervised=True, draining=True)
        self.assertEqual(lane.messages, []); self.assertEqual(writes, [])
        _, runtime, _, writes = exercise_chat(Path(bridge.__file__).read_text(),
            'Stop.', supervised=True, draining=True)
        self.assertEqual(writes, [{'action':'wait'}]); self.assertFalse(runtime.goal_active)
        self.assertEqual(window.phase(315, 0), 'drained')
        self.assertEqual(window.phase(335, 1), 'expired')

    def test_completed_unpolled_work_prevents_early_break(self):
        worker = SimpleNamespace(pending=0)
        lane = SimpleNamespace(queue=[], ready=None)
        self.assertEqual(drain_pending(worker,lane,object(),None),1)
        lane.ready = {'observation':'must preserve'}
        self.assertEqual(drain_pending(worker,lane,None,None),1)

    def test_failed_writer_and_forever_producer_cannot_hang_process(self):
        with tempfile.TemporaryDirectory() as folder:
            receipt = Path(folder)/'failure.json'
            program = '''import sys,threading,time
sys.path[:0]=sys.argv[1:3]
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1]).parents[1]))
import test_recorder_integration
from greg_supervised import recover_failed_core
from types import SimpleNamespace
t=threading.Thread(target=lambda:time.sleep(1000));t.start()
def blocked(*a,**k): raise TimeoutError('fixture writer unavailable')
recover_failed_core(SimpleNamespace(call=blocked,thread=t),{'fully_drained':False,'pending_producers':['worker']},sys.argv[3],seconds=.05)
'''
            result = subprocess.run([sys.executable,'-c',program,str(ROOT/'deployments/oldpc'),
                str(ROOT/'tests'),str(receipt)],capture_output=True,timeout=5)
            self.assertEqual(result.returncode,1,result.stderr)
            self.assertTrue(receipt.exists(),result.stderr.decode(errors='replace'))
            data=json.loads(receipt.read_text())
            self.assertFalse(data['fully_drained']);self.assertTrue(data['core_writer_orphaned'])
            self.assertEqual(data['original_failure']['pending_producers'],['worker'])

    def test_qualified_shutdown_function_unchanged(self):
        old=ROOT/'recovery/2026-11-12/fixtures/voice-ssh-gmod_bridge.py'
        if not old.exists(): self.skipTest('qualification baseline not shipped here')
        def function(path):
            tree=ast.parse(path.read_text());return ast.dump(next(n for n in tree.body
                if isinstance(n,ast.FunctionDef) and n.name=='shutdown_bridge'),include_attributes=False)
        self.assertEqual(function(old),function(Path(bridge.__file__)))


class CharacterTests(unittest.TestCase):
    def test_exact_vision_questions_not_unrelated_conversation(self):
        for text in ('What can you see?','Gregory, what do you see?','Can you see this?','Look!'):
            self.assertEqual(bridge.supervised_input(text)[0],'inspect')
        for text in ('I wonder what you can see','Do not look','That look is funny'):
            self.assertNotEqual(bridge.supervised_input(text)[0],'inspect')

    def test_only_supervised_vision_gets_bounded_slower_sensor_budget(self):
        response=SimpleNamespace(stdout=json.dumps({'caption':'A visible barrel.', 't':time.time()-20}))
        with patch.object(bridge.subprocess,'run',return_value=response) as run:
            with self.assertRaises(ValueError):bridge.inspect('helper',{},'look','python')
            self.assertEqual(run.call_args.kwargs['timeout'],12)
            result=bridge.inspect('helper',{},'look','python',True)
            self.assertEqual(run.call_args.kwargs['timeout'],35)
            self.assertTrue(json.loads(run.call_args.kwargs['input'])['supervised'])
            self.assertEqual(result['caption'],'A visible barrel.')
        response.stdout=json.dumps({'caption':'stale','t':time.time()-36})
        with patch.object(bridge.subprocess,'run',return_value=response):
            with self.assertRaises(ValueError):bridge.inspect('helper',{},'look','python',True)

    def test_explicit_speech_temperature_does_not_change_movement_budget(self):
        import greg_model
        before=(greg_model._min_tokens,greg_model._timeout,greg_model._reasoning)
        provider=LMStudioProvider('http://127.0.0.1:1234/v1/chat/completions','gemma',temperature=1)
        response=Mock();response.json.return_value={'choices':[{'message':{'content':'{"say":"Test","used_memory_ids":[]}'}}]}
        with patch('greg_model.post_chat',return_value=response) as post:
            provider.generate({'persona':'Gregory','goals':[]},'hello')
        self.assertEqual(post.call_args.kwargs['json']['temperature'],1)
        self.assertEqual((greg_model._min_tokens,greg_model._timeout,greg_model._reasoning),before)
        for value in (True,-1,3,float('nan'),float('inf')):
            with self.assertRaises(ValueError):LMStudioProvider('http://127.0.0.1/x','gemma',temperature=value)

    def test_core_persona_persists_without_replacing_identity_or_goals(self):
        with tempfile.TemporaryDirectory() as folder:
            core=Core(folder).start()
            try:
                original=core.call('status')['profile']
                updated=core.call('persona',{'persona':'Gregory character directions, not invented history.'})
                self.assertEqual(updated['character_id'],original['character_id'])
                self.assertEqual(updated['goals'],original['goals'])
                for value in ('', 'x'*8193, 42):
                    with self.assertRaises(ValueError):core.call('persona',{'persona':value})
            finally:core.call('stop');core.thread.join(5)
            restarted=Core(folder).start()
            try:self.assertEqual(restarted.call('status')['profile'],{k:v for k,v in updated.items() if k!='_result'})
            finally:restarted.call('stop');restarted.thread.join(5)


class BonziTests(unittest.TestCase):
    def wav(self,peak=1000):
        out=io.BytesIO()
        with wave.open(out,'wb') as wav:
            wav.setparams((1,2,24000,0,'NONE','not compressed'))
            wav.writeframes(struct.pack('<h',peak)*2400)
        return out.getvalue()

    def test_pcm_conversion_has_lead_stereo_and_quiet_only_normalization(self):
        import audioop
        for peak in (1000,30000):
            pcm=wav_to_discord(self.wav(peak));lead=48000
            self.assertEqual(pcm[:lead],bytes(lead))
            self.assertAlmostEqual((len(pcm)-lead)/192000,.1,places=3)
            expected=int(.85*32767) if peak==1000 else peak
            self.assertAlmostEqual(audioop.max(pcm[lead:],2),expected,delta=1)

    def test_local_http_only_and_non_200_never_falls_back(self):
        connection=Mock();connection.getresponse.return_value.status=503
        with patch('greg_sapi4.http.client.HTTPConnection',return_value=connection) as ctor:
            with self.assertRaises(RuntimeError):synthesize('hello')
        ctor.assert_called_once_with('127.0.0.1',23451,timeout=30)
        self.assertIn('pitch=140',connection.request.call_args.args[1])
        self.assertIn('speed=157',connection.request.call_args.args[1])
        connection.close.assert_called_once()


if __name__=='__main__':unittest.main()
