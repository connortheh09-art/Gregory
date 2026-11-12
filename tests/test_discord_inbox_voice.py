"""Actual Core + VoiceSession one-turn disclosure and post-publication isolation."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
import uuid
from contextlib import closing

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'deployments/oldpc')]
from gregory_core.runtime import Core, FixtureProvider
from greg_voice_session import VoiceSession
from greg_voice_protocol import inbox_text
from greg_supervised import SupervisedLane
from greg_recorder import Recorder
from greg_experience import ExperienceTracker

CFG = dict(bot_id='1563299893014036550', users=['1200889100379639899'], after_id='100')
VOICE = dict(owner_id=CFG['users'][0], guild_id='2001', channel_id='3001', game_name='Connor')
DM = dict(bot_id=CFG['bot_id'], channel_id='4001', peer_id=VOICE['owner_id'])
SECRET = 'private-voice-zebra'

class Provider(FixtureProvider):
    def __init__(self): self.prompts = []
    def generate(self, profile, prompt):
        self.prompts.append(prompt)
        return dict(say=SECRET if 'PRIVATE_INBOX_DATA_JSON:' in prompt else 'ordinary reply',
                    used_memory_ids=[], intent={'action': 'must_not_dispatch'})

class VoiceInboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.host = VoiceSession(VOICE, 'STEAM_0:1:1000')
        self.connect()
        self.provider = Provider()
        self.core = Core(self.root/'core', provider=self.provider, inbox_config=CFG,
                         inbox_voice_authorizer=self.host.consume_inbox).start()
        self.addCleanup(self.cleanup)
        self.core.call('inbox', dict(DM, operation='bind'))
        self.core.call('inbox', dict(DM, operation='batch', messages=[dict(
            message_id='101', author_id=VOICE['owner_id'], content=SECRET)]))
        self.lane = None

    def connect(self):
        self.host.call('connect', {k: VOICE[k] for k in ('guild_id', 'channel_id')})

    def metadata(self, text='check my DMs in this call'):
        connection, generation = self.host.stamp()
        self.host.call('turn', dict(connection=connection, generation=generation,
            request_id=str(uuid.uuid4()), author_id=VOICE['owner_id'], is_bot=False,
            text=text, captured_at=self.host.clock()))
        row = self.host.drain()[0]
        return self.host.claim(row)

    def grant(self):
        return self.host.authorize_inbox(self.metadata(), 'check my DMs in this call')

    def think(self, claim):
        return self.core.call('think', dict(prompt='check my DMs in this call', inbox_voice_claim=claim))

    def cleanup(self):
        if self.lane:
            self.lane.invalidate(); self.lane.jobs.request_stop()
            self.lane.jobs.join_until(time.monotonic()+3)
            self.tracker.shutdown(); self.recorder.close()
        if self.core.accepting: self.core.call('stop')
        self.core.thread.join(5)

    def test_explicit_directive_only_not_quoted_or_negated(self):
        for text in ('Gregory, check my DMs in this call!', 'Read my messages in this call.'):
            self.assertTrue(inbox_text(text))
        for text in ('check my DMs', 'do not check my DMs in this call',
                     'he said check my DMs in this call', 'read his DMs in this call', None):
            self.assertFalse(inbox_text(text))

    def test_ordinary_text_and_wrong_identity_cannot_issue_grants(self):
        meta = self.metadata()
        self.assertIsNone(self.host.authorize_inbox(meta, 'hello'))
        for key, value in [('author_id', '999'), ('channel_id', '999'), ('guild_id', '999'),
                           ('connection', 'wrong'), ('generation', 999), ('captured_at', 0)]:
            self.assertIsNone(self.host.authorize_inbox(dict(meta, **{key: value}), 'check my DMs in this call'))

    def test_actual_core_releases_matching_sender_once_and_strips_intent(self):
        claim = self.grant(); answer = self.think(claim)
        self.assertEqual(answer['say'], SECRET); self.assertNotIn('intent', answer)
        self.assertIn('AUTHORIZED ONE-TURN VC DISCLOSURE', self.provider.prompts[-1])
        with self.assertRaises(PermissionError): self.think(claim)

    def test_reconnect_invalidates_unconsumed_grant(self):
        claim = self.grant(); self.connect()
        with self.assertRaises(PermissionError): self.think(claim)
        self.assertEqual(self.provider.prompts, [])

    def test_stop_invalidates_unconsumed_grant(self):
        claim = self.grant(); self.metadata('Stop.')
        with self.assertRaises(PermissionError): self.think(claim)

    def test_expired_capture_and_lease_rejected(self):
        claim = self.grant(); real_clock = self.host.clock
        self.host.clock = lambda: real_clock()+21
        with self.assertRaises(PermissionError): self.think(claim)

    def test_public_context_and_events_do_not_retain_private_reply(self):
        self.think(self.grant())
        self.core.call('think', dict(prompt='hello in public', metadata_only=True))
        self.assertNotIn(SECRET, self.provider.prompts[-1])
        with closing(sqlite3.connect(self.core.root/'core.sqlite3')) as db:
            journal = ' '.join(r[0] for r in db.execute('SELECT payload FROM events'))
        self.assertNotIn(SECRET, journal)
        self.assertIn('"surface": "vc"', journal)

    def test_no_authorizer_unknown_claim_or_ambiguous_surface_refused(self):
        with self.assertRaises(PermissionError): self.think('x'*43)
        claim = self.grant()
        with self.assertRaises(PermissionError): self.core.call('think', dict(prompt='q',
            inbox_voice_claim=claim, inbox_scope=dict(bot_id=CFG['bot_id'],channel_id='4001',author_id=VOICE['owner_id'],surface='dm')))
        authorizer = self.core.inbox_voice_authorizer; self.core.inbox_voice_authorizer = None
        try:
            with self.assertRaises(PermissionError): self.think(claim)
        finally: self.core.inbox_voice_authorizer = authorizer

    def test_model_scope_cannot_select_someone_elses_channel(self):
        self.core.call('inbox', dict(DM, operation='bind', channel_id='4002'))
        with self.assertRaises(PermissionError): self.think(self.grant())
        self.assertEqual(self.provider.prompts, [])

    def test_real_lane_publication_never_copies_dm_answer_into_dialogue(self):
        self.recorder = Recorder(self.root/'recorder.sqlite3', 'fixture-private-vc', max_mib=64)
        self.assertTrue(self.recorder.wait_ready())
        self.tracker = ExperienceTracker(self.recorder, landmark_capture=False)
        state = dict(steamid='fixture-agent',bridgeSession='fixture-bridge',controlEpoch=1,
                     map='gm_construct',seq=1,t=1,serverTime=time.time(),enabled=True,dead=False,
                     menu=False,stopped=False,pos=dict(x=0,y=0,z=0))
        self.tracker.accepted_state(state)
        self.lane = SupervisedLane(self.core,self.recorder,self.tracker,delivery=self.host)
        self.lane.update(state)
        self.assertTrue(self.lane.hear_voice('check my DMs in this call',self.metadata()))
        deadline = time.monotonic()+3
        while self.lane.ready is None and time.monotonic()<deadline:
            self.lane.poll(); time.sleep(.01)
        row = self.lane.take(); self.assertIsNotNone(row)
        self.assertTrue(self.host.offer(row)); self.lane.published(row,True)
        self.assertEqual(list(self.lane.dialogue), [])
        self.assertEqual(row['say'], SECRET)
        self.assertTrue(self.lane.hear_voice('hello again',self.metadata('hello again')))
        request = self.lane.queue[-1]
        self.assertNotIn('inbox_voice_claim', request)

if __name__ == '__main__': unittest.main()
