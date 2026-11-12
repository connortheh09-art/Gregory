"""Real loopback transport with independent PC clock domains; no Discord/model."""
import asyncio
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import time
import unittest
import uuid
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'deployments/oldpc')]
import test_recorder_integration
from greg_voice_session import VoiceSession,VoiceServer,VoiceRefused
from greg_voice_client import CoreVoiceAdapter,VoiceHTTP

CONFIG=dict(owner_id='1001',guild_id='2001',channel_id='3001',game_name='Connor')
STEAM='STEAM_0:1:1000'


class ClockTests(unittest.IsolatedAsyncioTestCase):
    async def wait(self,predicate):
        end=time.monotonic()+3
        while time.monotonic()<end:
            if predicate():return
            await asyncio.sleep(.01)
        self.fail('bounded clock-domain fixture wait expired')

    async def make(self,offset):
        real_time=time.time
        logs=[]
        host=VoiceSession(CONFIG,STEAM,clock=lambda:real_time()+offset,log=logs.append)
        server=VoiceServer(host).start()
        adapter=CoreVoiceAdapter(VoiceHTTP(server.receipt()),owner_id=CONFIG['owner_id'],
            channel=lambda:{k:CONFIG[k] for k in ('guild_id','channel_id')},
            transcribe=lambda pcm:pcm.decode(),synthesize=lambda text:b'pcm',
            play=lambda pcm,after:after(None),stop=lambda:None,log=logs.append)
        await adapter.start()
        await self.wait(lambda:adapter.scope is not None and adapter.clock_anchor is not None)
        return host,server,adapter,logs

    async def test_baseline_cold_stt_passes_but_fast_stt_fails_with_host_behind(self):
        host=VoiceSession(CONFIG,STEAM,clock=lambda:time.time()-1.4)
        scope=host.call('connect',{k:CONFIG[k] for k in ('guild_id','channel_id')})
        scope={k:scope[k] for k in ('connection','generation')}
        def turn(age):
            return host.call('turn',dict(scope,request_id=str(uuid.uuid4()),author_id='1001',
                is_bot=False,text='hello',captured_at=time.time()-age))
        turn(2)
        with self.assertRaisesRegex(VoiceRefused,'capture age'):turn(.1)

    async def test_fast_repeated_utterances_and_stop_work_with_both_clock_skews(self):
        user=SimpleNamespace(id=1001,bot=False)
        for offset in (-1.4,2.5):
            with self.subTest(host_offset=offset):
                host,server,adapter,logs=await self.make(offset)
                try:
                    for text in (b'hello',b'walk forward',b'Stop.'):
                        ended=time.time()-.25
                        self.assertTrue(await adapter.audio(text,user,1,ended))
                        await self.wait(lambda:len(host.turns)>0)
                        row=host.turns[-1]
                        self.assertAlmostEqual(row['captured_at'],ended+offset,delta=.1)
                        self.assertLessEqual(row['captured_at'],host.clock())
                        self.assertEqual(host.drain()[0]['msg'],'stop' if text==b'Stop.' else text.decode())
                    self.assertFalse(any('VOICE_TURN_REFUSED' in x for x in logs))
                finally:
                    await adapter.close();server.close()

    async def test_client_wall_clock_step_after_capture_does_not_retimestamp_speech(self):
        host,server,adapter,logs=await self.make(-1.4)
        user=SimpleNamespace(id=1001,bot=False)
        ended=time.time()-.5
        try:
            self.assertTrue(await adapter.audio(b'hello',user,1,ended))
            # After capture is queued, an NTP/manual clock step must not alter
            # its age or make later handler/STT time the capture endpoint.
            with patch('greg_voice_client.time.time',return_value=time.time()+3600):
                await self.wait(lambda:len(host.turns)>0)
            self.assertAlmostEqual(host.turns[0]['captured_at'],ended-1.4,delta=.1)
        finally:
            await adapter.close();server.close()

    async def test_clock_alignment_does_not_waive_twenty_second_stale_limit(self):
        host,server,adapter,logs=await self.make(-1.4)
        def slow(pcm):time.sleep(.25);return pcm.decode()
        adapter.transcribe=slow
        try:
            self.assertTrue(await adapter.audio(b'Stop.',SimpleNamespace(id=1001,bot=False),1,time.time()-19.9))
            await self.wait(lambda:any('VOICE_TURN_REFUSED' in x for x in logs))
            self.assertEqual(list(host.turns),[])
            self.assertTrue(any('voice text/capture age refused' in x for x in logs))
        finally:
            await adapter.close();server.close()

    async def test_coarse_host_wall_ticks_do_not_reject_fast_followup_or_stop(self):
        host,server,adapter,logs=await self.make(-1.4)
        real_time=time.time
        host.clock=lambda:math.floor((real_time()-1.4)*50)/50
        try:
            # Refresh calibration after switching this fixture to 20-ms ticks.
            await asyncio.sleep(.15)
            for text in (b'one',b'two',b'Stop.'):
                self.assertTrue(await adapter.audio(text,SimpleNamespace(id=1001,bot=False),1,time.time()))
                await self.wait(lambda:len(host.turns)>0)
                self.assertLessEqual(host.turns[-1]['captured_at'],host.clock())
                host.drain()
            self.assertFalse(any('VOICE_TURN_REFUSED' in x for x in logs))
        finally:
            await adapter.close();server.close()


if __name__=='__main__':unittest.main()
