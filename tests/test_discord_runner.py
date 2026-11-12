"""Runner startup/termination without SDK/network/real token."""
import asyncio
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gregory_core.runtime import Core

spec=importlib.util.spec_from_file_location('discord_runner',Path(__file__).resolve().parents[1]/'tools/gregory_discord_text.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)/'existing'
        core=Core(self.root).start();self.profile=core.call('status')['profile']
        core.call('stop');core.thread.join(2)
        self.config=dict(core_root=str(self.root),lm_endpoint='http://127.0.0.1:1234/v1/chat/completions',
            lm_model='fixture-unused',guild_id='1',channel_id='2',bot_id='3',users=['4'],bots=['5'],
            embed_endpoint='http://127.0.0.1:1234/v1',embed_model='fixture-embed',
            embed_revision='sha256:'+'0'*64)
    async def asyncTearDown(self):self.tmp.cleanup()

    async def test_validate_does_not_create_a_second_character_or_need_sdk(self):
        self.assertEqual(runner.validate(self.config),self.root)
        wrong=dict(self.config,core_root=str(self.root/'new'))
        with self.assertRaisesRegex(ValueError,'existing initialized'):runner.validate(wrong)
        self.assertFalse((self.root/'new').exists())

    async def test_foreground_window_times_out_and_releases_authoritative_writer(self):
        instances=[]
        class Client:
            def __init__(self,**kw):
                self.closed=False;self.user=SimpleNamespace(id=3);instances.append(self)
            def event(self,fn):setattr(self,fn.__name__,fn);return fn
            async def start(self,token,**kw):
                assert token=='fixture-not-a-real-token'
                await self.on_ready()
                await asyncio.Event().wait()
            async def close(self):self.closed=True
        fake=SimpleNamespace(Client=Client,Intents=SimpleNamespace(none=lambda:SimpleNamespace()),
            AllowedMentions=SimpleNamespace(none=lambda:None))
        output=io.StringIO()
        with patch.dict(sys.modules,discord=fake),patch.dict(runner.os.environ,DISCORD_BOT_TOKEN='fixture-not-a-real-token'),redirect_stdout(output):
            await asyncio.wait_for(runner.run(self.config,.001),2)
        self.assertTrue(instances[0].closed)
        self.assertIn('discord_supervised_stop',output.getvalue())
        self.assertNotIn('fixture-not-a-real-token',output.getvalue())
        restarted=Core(self.root).start()
        try:self.assertEqual(restarted.call('status')['profile'],self.profile)
        finally:restarted.call('stop');restarted.thread.join(2)

    async def test_sdk_setup_failure_still_releases_core(self):
        class Broken:
            def __init__(self,**kw):raise RuntimeError('fixture SDK startup failure')
        fake=SimpleNamespace(Client=Broken,Intents=SimpleNamespace(none=lambda:SimpleNamespace()),
            AllowedMentions=SimpleNamespace(none=lambda:None))
        with patch.dict(sys.modules,discord=fake),patch.dict(runner.os.environ,DISCORD_BOT_TOKEN='fixture-not-a-real-token'),redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError,'fixture SDK startup failure'):
                await runner.run(self.config,.001)
        restarted=Core(self.root).start()
        restarted.call('stop');restarted.thread.join(2)

if __name__=='__main__':unittest.main()
