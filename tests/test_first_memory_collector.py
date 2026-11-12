"""Fresh-process collector path with fake provider; every HTTP call is replaced.

Tests routing/receipts, not model truthfulness or actual game speech delivery.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest

import test_first_memory as fixture
ROOT, state = fixture.ROOT, fixture.state
from gregory_core.memory import canonical, digest
from gregory_core.canary_preflight import clean_b, inventory


CHILD = r'''
import json,sys,time
from pathlib import Path
from types import SimpleNamespace
root,manifest,variant=sys.argv[1:]
sys.path.insert(0,str(Path(root)/'deployments'/'oldpc'))
sys.path.insert(0,root)
config=json.loads(Path(manifest).read_text())
prefix=Path(config['receipt_prefix'])
pre=json.loads(Path(config['preflight_receipt']).read_text())
transport=Path(pre['transport_root'])
monitor=prefix.with_suffix('.monitor.json')
def heartbeat():
    import os
    monitor.write_text(json.dumps(dict(kind='gregory.canary.monitor.v1',utc_seconds=time.time(),
        bridge_pid=os.getpid(),ok=True,baseline_ready=True)))
heartbeat()
state=json.loads((transport/'state.json').read_text().splitlines()[-1])
state['serverTime']=time.time()
(transport/'state.json').write_text(json.dumps(state)+'\n')
def fake_post(url,*,json,timeout):
    # A receipt must already be durably present before the provider is called.
    receipt=__import__('json').loads(Path(str(prefix)+'.request.json').read_text())
    assert receipt['verified_before_model'] is True
    from gregory_core.memory import digest
    assert digest(json)==receipt['request_sha256']
    Path(str(prefix)+'.fake-provider.json').write_text(__import__('json').dumps(json))
    text='I remember a crate there before; I have not checked it now.'
    if config['empty_control']:text='I do not have a stored encounter to recall.'
    if variant=='false_current':text="It's still sitting there."
    answer={'say':text}
    if variant=='movement':answer['action']={'action':'navigate','points':[{'x':999,'y':0,'z':0}]}
    if variant=='mutate_request':json['messages'][1]['content']='decoy'
    state['seq']+=1;state['t']+=1;state['serverTime']=time.time()
    heartbeat()
    with (transport/'state.json').open('a') as f:f.write(__import__('json').dumps(state)+'\n')
    return SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'choices':[{'message':{'content':__import__('json').dumps(answer)}}]})
sys.modules['requests']=SimpleNamespace(post=fake_post)
import gmod_bridge as b
sys.argv=['gmod_bridge.py','--first-memory-recall',manifest,'--data',str(transport.parent),
          '--model','OFFLINE-FAKE-PROVIDER','--model-min-tokens','512','--model-reasoning','off',
          '--first-memory-monitor',str(monitor)]
raise SystemExit(b.main())
'''


class RecallCollectorTests(unittest.TestCase):
    setUp = fixture.CanaryTests.setUp
    store = fixture.CanaryTests.store
    capture = fixture.CanaryTests.capture
    promoted = fixture.CanaryTests.promoted
    def rig(self, *, empty=False):
        store, reader, frozen, encounter = self.promoted()
        repo = self.root/'B-fresh-source'
        bridge = repo/'deployments'/'oldpc'
        shutil.copytree(ROOT/'deployments'/'oldpc', bridge, ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree(ROOT/'gregory_core', repo/'gregory_core', ignore=shutil.ignore_patterns('__pycache__'))
        transport = self.root/'B-game'/'data'/'greg'; transport.mkdir(parents=True)
        (transport/'playercore_agent.txt').write_text('installed-agent-20261015')
        (transport/'navdump.json').write_text('{"map":"gm_construct"}')
        pre = clean_b(source_root=bridge, core_root=repo/'gregory_core', transport_root=transport,
            source_sha256={k:v['sha256'] for k,v in inventory(bridge).items()},
            core_sha256={k:v['sha256'] for k,v in inventory(repo/'gregory_core').items()},
            bootstrap_sha256={k:v['sha256'] for k,v in inventory(transport).items()}, map_name='gm_construct',
            context_paths={k:str(bridge/name) for k,name in dict(chat_memory='greg_chat_memory.json',
                player_memory='greg_player_memory', audit='greg_model_audit.jsonl', trace='trace.jsonl',
                lessons='greg_lessons.jsonl', landmarks='greg_landmarks.json').items()})
        s = state(); s['bridgeSession']='synthetic-bridge-B'
        # Same entity index/class, different model/coordinates. None enter prompt.
        s['eye'].update(entIndex=71, model='models/DECOY.mdl', entityPos=dict(x=999,y=999,z=999))
        (transport/'state.json').write_text(json.dumps(s)+'\n')
        prepath=self.root/'clean-B.json';prepath.write_text(canonical(pre))
        sealpath=self.root/'seal.json';sealpath.write_text(canonical(frozen))
        memory = self.memory_path
        if empty:
            memory=self.root/'empty.sqlite3'; self.store(memory).close()
        config=dict(memory_db=str(memory), source_db=str(self.source_path), owner='owner',
            seal=str(sealpath), question='What did you encounter here last time, and where was it?',
            preflight_receipt=str(prepath), preflight_sha256=digest(pre), allowed_b_files=['state.json'],
            receipt_prefix=str(self.root/'B-recall'), empty_control=empty)
        manifest=self.root/'B-manifest.json';manifest.write_text(canonical(config))
        return repo, manifest, config, store, reader

    def child(self, repo, manifest, variant='valid'):
        env=dict(os.environ);env.pop('PYTHONPATH',None);env.pop('GREG_TRACE_PATH',None)
        return subprocess.run([sys.executable,'-c',CHILD,str(repo),str(manifest),variant],
            cwd=self.root, env=env, capture_output=True, text=True, timeout=15)

    def test_full_recall_branch_is_speech_only_and_decoy_not_in_prompt(self):
        repo, manifest, config, store, _=self.rig()
        from gregory_core.canary import logical_snapshot
        before=logical_snapshot(store)
        result=self.child(repo,manifest)
        self.assertEqual(result.returncode,0,result.stderr)
        request=json.loads((self.root/'B-recall.request.json').read_text())
        provider=json.loads((self.root/'B-recall.fake-provider.json').read_text())
        self.assertEqual(digest(provider),request['request_sha256'])
        self.assertIn('wood_crate001a.mdl',json.dumps(provider))
        self.assertNotIn('DECOY',json.dumps(provider))
        # Numeric decoy coordinates must not leak; a UUID may legally contain 999.
        self.assertNotRegex(json.dumps(provider),r'(?<![\w])999(?![\w])')
        self.assertEqual(provider['max_tokens'],512)
        self.assertEqual(provider['reasoning_effort'],'none')
        self.assertTrue(request['question_leak_check']['passed'])
        submission=json.loads((self.root/'B-recall.submission.json').read_text())
        self.assertEqual(submission['command']['payload']['action']['action'],'say')
        self.assertFalse(submission['delivered'])
        self.assertFalse(submission['current_state_claim'])
        self.assertEqual(before,logical_snapshot(store))
        self.assertFalse((repo/'deployments'/'oldpc'/'trace.jsonl').exists())

    def test_action_response_rejects_without_mailbox_submission(self):
        repo,manifest,config,_,_=self.rig()
        result=self.child(repo,manifest,'movement')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('speech-only',result.stderr)
        self.assertFalse((self.root/'B-recall.submission.json').exists())
        self.assertFalse((self.root/'B-game'/'data'/'greg'/'cmd.json').exists())

    def test_request_changed_by_provider_rejects_before_publication(self):
        repo,manifest,config,_,_=self.rig()
        result=self.child(repo,manifest,'mutate_request')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('request changed',result.stderr)
        self.assertFalse((self.root/'B-recall.submission.json').exists())

    def test_empty_store_uses_distinct_process_and_no_A_facts(self):
        repo,manifest,config,_,_=self.rig(empty=True)
        result=self.child(repo,manifest)
        self.assertEqual(result.returncode,0,result.stderr)
        request=json.loads((self.root/'B-recall.request.json').read_text())
        self.assertEqual(request['memory_ids'],[])
        self.assertNotIn('wood_crate',json.dumps(request['model_input']))

    def test_legacy_context_survivor_stops_before_fake_provider(self):
        repo,manifest,config,_,_=self.rig()
        (repo/'deployments'/'oldpc'/'greg_chat_memory.json').write_text('{"old":"A facts"}')
        result=self.child(repo,manifest)
        self.assertNotEqual(result.returncode,0)
        self.assertFalse((self.root/'B-recall.fake-provider.json').exists())

    def test_question_fact_leak_writes_rejection_before_fake_provider(self):
        repo,manifest,config,_,_=self.rig()
        config['question']='Did you encounter that PROP_PHYSICS last time?'
        manifest.write_text(canonical(config))
        result=self.child(repo,manifest)
        self.assertNotEqual(result.returncode,0)
        self.assertFalse((self.root/'B-recall.fake-provider.json').exists())
        rejected=json.loads((self.root/'B-recall.request-rejected.json').read_text())
        self.assertFalse(rejected['model_called'])
        self.assertEqual(rejected['question_leak_check']['matched_fields'],['class'])
        self.assertFalse((self.root/'B-game'/'data'/'greg'/'cmd.json').exists())

    def test_false_current_presence_is_explicitly_flagged_in_receipts(self):
        repo,manifest,config,_,_=self.rig()
        result=self.child(repo,manifest,'false_current')
        self.assertEqual(result.returncode,0,result.stderr)
        submission=json.loads((self.root/'B-recall.submission.json').read_text())
        assessment=json.loads((self.root/'B-recall.speech-assessment.json').read_text())
        self.assertTrue(submission['current_state_claim'])
        self.assertEqual(assessment,submission['current_state_check'])
        self.assertFalse(submission['delivered'])
        self.assertFalse(assessment['complete_semantic_check'])
