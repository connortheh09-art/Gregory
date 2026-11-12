"""Cancellation must suppress speech/actions without erasing heard owner context."""
import asyncio
import json
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'deployments/oldpc'), str(ROOT/'tests')]
import test_voice_turn_taking as voice
import test_core_harness as harness

DOOR = 'Walk forward to the south tower approach and interact with the doors.'
COOKIE = "The doors teleport you to the top. If you make it there, I'll give you five cookies. How does that sound?"


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.host = voice.CoreListenTests().rig()
        self.addCleanup(self.host.doCleanups)
        self.lane = self.host.lane
        self.scope = ['connection', 1]
        self.lane.delivery.stamp = lambda: tuple(self.scope)
        self.n = 0
        self.prompts = []
        def generate(profile, prompt):
            self.prompts.append(prompt)
            # Context-dependent fixture, not a claim about live Gemma behavior.
            return dict(say='I heard you.', intent=None, used_memory_ids=[])
        self.host.provider.generate = generate

    def admit(self, text):
        self.n += 1
        meta = dict(self.host.meta, connection=self.scope[0], generation=self.scope[1],
                    request_id='input-'+str(self.n), captured_at=time.time())
        self.assertTrue(self.lane.hear_voice(text, meta))
        return self.lane.queue.popleft()

    def answer(self, request):
        self.lane.update(dict(self.host.state, serverTime=time.time()))
        return dict(self.lane._work(request), request=request)

    def cancel(self, text):
        row = self.answer(self.admit(text))
        self.scope[1] += 1  # meaningful barge-in cancels this output, not its input
        self.lane.published(row, False)
        return row

    def test_door_cookie_cancellation_retains_heard_context_for_presence_check(self):
        self.cancel(DOOR)
        self.cancel(COOKIE)
        row = self.answer(self.admit('You there Gregory?'))
        prompt = self.prompts[-1]
        recent = json.loads(prompt.split('\nRECENT_DIALOGUE:')[1])
        self.assertEqual([x['user'] for x in recent], [DOOR, COOKIE])
        self.assertTrue(all(x['reply'] == '' for x in recent))
        self.assertTrue(all('no reply published' in x['qualification'] for x in recent))
        self.assertIn('presence check', prompt)
        self.assertFalse(self.host.tasks.engaged)
        self.assertEqual(self.lane.recent_dialogue(), [])
        self.assertEqual(self.host.core.call('lookup', dict(query='five cookies'))['hits'], [])
        self.lane.published(row, True)
        self.assertEqual(len(self.lane.unanswered_voice), 0)

    def test_reconnect_never_reuses_unanswered_input(self):
        self.cancel(COOKIE)
        self.scope[:] = ['new-connection', 1]
        self.answer(self.admit('Hello again'))
        self.assertNotIn(COOKIE, self.prompts[-1])

    def test_stop_world_invalidation_clears_unanswered_input(self):
        self.cancel(COOKIE)
        self.lane.invalidate()
        self.assertEqual(len(self.lane.unanswered_voice), 0)
        self.answer(self.admit('Hello again'))
        self.assertNotIn(COOKIE, self.prompts[-1])

    def test_context_expires_and_is_bounded(self):
        for i in range(7):
            self.cancel('Unanswered statement '+str(i))
        self.assertEqual(len(self.lane.unanswered_voice), 4)
        for item in self.lane.unanswered_voice:
            item['heard_at'] -= 121
        self.answer(self.admit('You there?'))
        self.assertNotIn('Unanswered statement', self.prompts[-1])

    def test_private_inbox_request_is_not_added_to_public_pending_context(self):
        self.lane.delivery.authorize_inbox = lambda *args: 'private-claim'
        request = self.admit('Discuss my private messages')
        self.assertEqual(request['inbox_voice_claim'], 'private-claim')
        self.assertEqual(len(self.lane.unanswered_voice), 0)

    def test_old_publication_does_not_discard_a_newer_heard_turn(self):
        first = self.answer(self.admit(DOOR))
        self.admit(COOKIE)
        self.lane.published(first, True)
        self.assertEqual([x['text'] for x in self.lane.unanswered_voice], [COOKIE])

    def test_silent_listen_stays_silent_and_does_not_forge_a_reply(self):
        def generate(profile, prompt):
            return dict(say='[listen]', intent=dict(action='voice_turn', kind='listen'), used_memory_ids=[])
        self.host.provider.generate = generate
        row = self.answer(self.admit('Wait, I am still explaining the rules'))
        self.assertTrue(row['voice_wait'])
        self.assertEqual(row['say'], '')
        self.assertIsNone(row['game_intent'])
        self.lane.published(row, False, listened=True)
        self.assertEqual(len(self.lane.unanswered_voice), 0)


class PublicationDiagnosticTests(unittest.TestCase):
    def rig(self):
        host = harness.HarnessTests()
        host.setUp()
        self.addCleanup(host.doCleanups)
        return host

    def test_actual_bridge_stale_voice_gate_logs_id_without_applying_action(self):
        host = self.rig()
        host.stamp = ('voice', 2)
        host.publish()
        logs = [x for x in host.logs if x.startswith('SUPERVISED_PUBLICATION_REFUSED ')]
        self.assertEqual(len(logs), 1)
        event = json.loads(logs[0].split(' ', 1)[1])
        self.assertEqual(event, dict(request_id='owner-turn', reason='harness_admission_refused'))
        self.assertEqual(host.spoken, [])
        self.assertFalse(host.link.engaged)

    def test_actual_bridge_generation_gate_logs_distinct_reason(self):
        host = self.rig()
        host.lane.generation += 1
        host.publish()
        self.assertIn('generation_changed', ' '.join(host.logs))
        self.assertEqual(host.spoken, [])


class InterruptGateTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = voice.AdapterTurnTests.asyncSetUp
    asyncTearDown = voice.AdapterTurnTests.asyncTearDown
    wait = voice.AdapterTurnTests.wait
    offer = voice.AdapterTurnTests.offer

    async def test_two_owner_turns_without_playback_keep_both_reply_stamps_valid(self):
        original = self.host.stamp()
        await self.adapter.audio(DOOR.encode(), self.user, 1, time.time())
        await self.wait(lambda: len(self.host.turns) == 1)
        await self.adapter.audio(COOKIE.encode(), self.user, 1, time.time())
        await self.wait(lambda: len(self.host.turns) == 2)
        self.assertEqual(self.host.stamp(), original)
        self.assertEqual([x['text'] for x in self.host.turns], [DOOR, COOKIE])
        # Actual host publication acceptance, not just an unchanged local variable.
        self.assertTrue(self.host.offer(dict(request=dict(delivery_stamp=original), say='First reply.')))
        self.assertTrue(self.host.offer(dict(request=dict(delivery_stamp=original), say='Second reply.')))

    async def test_genuine_playback_still_interrupts_and_refuses_old_reply(self):
        self.offer('A reply currently being spoken.')
        await self.wait(lambda: bool(self.plays))
        original = self.host.stamp()
        await self.adapter.audio(b'Wait, there is more to explain.', self.user, 1, time.time())
        await self.wait(lambda: self.host.stamp() != original)
        self.assertEqual(self.host.stamp()[1], original[1]+1)
        self.assertFalse(self.host.offer(dict(request=dict(delivery_stamp=original), say='Stale reply.')))
        self.assertTrue(any('VOICE_REPLY_REFUSED' in x and 'delivery_stamp_changed' in x for x in self.logs))

    async def test_short_recognized_fragment_without_playback_cannot_cancel_pending_reply(self):
        original = self.host.stamp()
        await self.adapter.audio(b'You', self.user, 1, time.time())
        await self.wait(lambda: bool(self.host.turns))
        self.assertEqual(self.host.stamp(), original)

    async def test_queued_reply_without_active_audio_still_allows_barge_in(self):
        # Pause only the fixture's playback worker, leaving real poll/STT/assembly.
        worker = self.adapter.tasks[2]
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        original = self.host.stamp()
        self.adapter.reply_queue.put_nowait((dict(self.adapter.scope),
            dict(reply_id='fixture-queued', text='Not yet spoken.')))
        self.assertIsNone(self.adapter.current)
        await self.adapter.audio(b'Wait, let me clarify.', self.user, 1, time.time())
        await self.wait(lambda: self.host.stamp() != original)
        self.assertEqual(self.host.stamp()[1], original[1]+1)


if __name__ == '__main__':
    unittest.main()
