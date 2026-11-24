"""Real Core/adapter flow; synthetic replies are NOT live naturalness proof."""
from dataclasses import replace
import json
import sqlite3
import unittest
from unittest.mock import patch
import test_discord_text as fixture
from core_fixture_experience import capture_fixture
from gregory_core.runtime import Core,LMStudioProvider
from gregory_core.discord_text import sha
from test_provider_reply_contract import Response


class WorkingContextTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixture.TextTests.asyncSetUp
    asyncTearDown=fixture.TextTests.asyncTearDown
    new_adapter=fixture.TextTests.new_adapter
    message=fixture.TextTests.message
    turn=fixture.TextTests.turn

    def context(self):
        prompt=self.provider.calls[-1][1]
        return json.loads(prompt.split('\nRECENT_DIALOGUE: ',1)[1].split('\nHISTORICAL_RETRIEVAL: ',1)[0])

    async def test_follow_up_receives_actual_prior_input_and_delivered_reply(self):
        await self.turn(self.message(content='gregory: I am not sure; we should figure that out'))
        previous=self.transport.posts[-1][1]
        await self.turn(self.message(id='11',content='gregory: Can you stop saying that?'))
        self.assertEqual(self.context(),[
            dict(role='user',content='gregory: I am not sure; we should figure that out'),
            dict(role='assistant',content=previous)])
        self.assertIn('Treat feedback about your replies as feedback',self.provider.calls[-1][1])
        self.assertNotIn('[Retrieval:',self.transport.posts[-1][1])
        self.assertFalse(hasattr(self.adapter,'dialogue'))

    async def test_future_planning_has_live_context_and_real_fixture_evidence(self):
        mid=self.core.call('import',capture_fixture(self.root/'experience'))['memory_id']
        self.provider.used_memory_ids=[mid]
        await self.turn(self.message(content='gregory: wood_crate001a is where we paused'))
        await self.turn(self.message(id='11',content='gregory: What should we do next with wood_crate001a?'))
        prompt=self.provider.calls[-1][1]
        self.assertIn('where we paused',json.dumps(self.context()))
        self.assertIn(mid,prompt)
        self.assertIn('Historical memory '+mid,self.transport.posts[-1][1])
        self.assertEqual(self.core.call('status')['memory_count'],1)
        # No fabricated BigCity fixture or canned exploration answer is injected.
        self.assertNotIn('BigCity',prompt)

    async def test_scope_isolation_between_allowed_authors_and_channels(self):
        self.adapter.users.add('7')
        await self.turn(self.message(content='gregory: UNIQUE_PRIVATE_USER_DETAIL'))
        await self.turn(replace(self.message(id='11'),author_id='7'))
        self.assertEqual(self.context(),[])
        await self.adapter.close()
        self.adapter=self.new_adapter()
        self.adapter.channel_id='8'
        await self.turn(replace(self.message(id='12'),channel_id='8'))
        self.assertEqual(self.context(),[])

    async def test_unknown_turn_does_not_claim_a_spoken_exchange(self):
        self.transport.fail=True
        failed=await self.turn(self.message(content='gregory: UNKNOWN_SEND_DETAIL'))
        self.assertEqual(failed['state'],'unknown')
        self.transport.fail=False
        await self.turn(self.message(id='11'))
        self.assertEqual(self.context(),[])
        self.assertNotIn('UNKNOWN_SEND_DETAIL',self.provider.calls[-1][1])

    async def test_cancelled_turn_does_not_enter_working_context(self):
        original=self.provider.generate
        def disconnected_reply(profile,prompt):
            self.adapter.disconnect()
            return dict(say='CANCELLED_REPLY_NOT_DELIVERED')
        self.provider.generate=disconnected_reply
        failed=await self.turn(self.message(content='gregory: CANCELLED_INPUT'))
        self.assertEqual(failed['state'],'cancelled')
        self.assertEqual(self.transport.posts,[])
        self.assertEqual(self.core.dialogue.scopes,{})
        self.provider.generate=original
        self.adapter.reconnect()
        await self.turn(self.message(id='11'))
        self.assertEqual(self.context(),[])

    async def test_context_fields_are_rejected_outside_complete_accepted_exchange(self):
        import time
        ids=dict(guild_id='1',channel_id='2',message_id='71')
        payload=dict(ids,operation='reserve',author_id='4',content_sha256=sha('input'),
            source_at=time.time(),received_at=time.time(),trigger='prefix')
        with self.assertRaisesRegex(ValueError,'complete accepted exchange'):
            self.core.call('conversation',dict(payload,context_user='input',context_reply='reply'))
        self.core.call('conversation',payload)
        with self.assertRaisesRegex(ValueError,'complete accepted exchange'):
            self.core.call('conversation',dict(ids,operation='transition',state='intent',
                context_user='input',context_reply='reply'))
        self.assertEqual(self.core.call('conversation',dict(ids,operation='get'))['state'],'received')
        self.assertEqual(self.core.dialogue.scopes,{})

    async def test_duplicate_delivery_does_not_append_twice(self):
        m=self.message(content='gregory: Once only')
        await self.turn(m);await self.turn(m)
        await self.turn(self.message(id='11'))
        self.assertEqual(len(self.context()),2)
        self.assertEqual(len(self.transport.posts),2)

    async def test_history_read_failure_is_empty_logged_and_nonfatal(self):
        await self.turn(self.message(content='gregory: earlier context'))
        with patch.object(self.core.dialogue,'snapshot',side_effect=RuntimeError('PRIVATE FAILURE TEXT')):
            outcome=await self.turn(self.message(id='11'))
        self.assertEqual(outcome['state'],'accepted')
        self.assertEqual(self.context(),[])
        events=self.core.call('correlation',{'correlation_id':outcome['correlation_id']})['events']
        received=next(e for e in events if e['payload'].get('type')=='conversation.received')
        self.assertEqual(received['payload']['context_error_category'],'RuntimeError')
        self.assertNotIn('PRIVATE FAILURE TEXT',json.dumps(events))

    async def test_append_failure_preserves_acceptance_and_logs_category(self):
        with patch.object(self.core.dialogue,'append',side_effect=RuntimeError('PRIVATE APPEND TEXT')):
            outcome=await self.turn(self.message())
        self.assertEqual(outcome['state'],'accepted')
        events=self.core.call('correlation',{'correlation_id':outcome['correlation_id']})['events']
        diagnostic=next(e for e in events if e['payload'].get('type')=='conversation.context_unavailable')
        self.assertEqual(diagnostic['payload']['error_category'],'RuntimeError')
        self.assertNotIn('PRIVATE APPEND TEXT',json.dumps(events))

    async def test_stop_and_restart_clear_context_not_profile_or_episodic_memory(self):
        mid=self.core.call('import',capture_fixture(self.root/'experience'))['memory_id']
        original=self.core.call('lookup',{'memory_id':mid})['hits'][0]
        profile=self.core.call('status')['profile']
        await self.turn(self.message(content='gregory: PRIVATE_CONTEXT_RESTART'))
        old=self.core
        await self.adapter.close()
        stopped=self.core.call('stop');self.core.thread.join(3)
        self.assertTrue(stopped['databases_closed'])
        self.assertEqual(old.dialogue.scopes,{})
        self.core=Core(self.root/'character',provider=self.provider).start()
        self.adapter=self.new_adapter()
        await self.turn(self.message(id='11'))
        self.assertEqual(self.context(),[])
        self.assertEqual(self.core.call('status')['profile'],profile)
        after=self.core.call('lookup',{'memory_id':mid})['hits'][0]
        self.assertEqual(after,original)

    async def test_raw_working_text_never_enters_durable_metadata_or_status(self):
        self.provider.generate=lambda profile,prompt:dict(say='PRIVATE_ASSISTANT_CONTEXT_981')
        result=await self.turn(self.message(content='gregory: PRIVATE_USER_CONTEXT_827'))
        status=self.core.call('status')
        events=self.core.call('correlation',{'correlation_id':result['correlation_id']})
        self.assertNotIn('PRIVATE_USER_CONTEXT_827',json.dumps([status,events]))
        self.assertNotIn('PRIVATE_ASSISTANT_CONTEXT_981',json.dumps([status,events]))
        await self.adapter.close();self.core.call('stop');self.core.thread.join(3)
        for db in ('core.sqlite3','episodes.sqlite3'):
            connection=sqlite3.connect(self.root/'character'/db)
            try:
                dump='\n'.join(connection.iterdump())
                self.assertNotIn('PRIVATE_USER_CONTEXT_827',dump)
                self.assertNotIn('PRIVATE_ASSISTANT_CONTEXT_981',dump)
            finally:connection.close()

    async def test_digest_mismatch_is_refused_before_accepted_state(self):
        import time
        ids=dict(guild_id='1',channel_id='2',message_id='70')
        self.core.call('conversation',dict(ids,operation='reserve',author_id='4',
            content_sha256=sha('real input'),source_at=time.time(),received_at=time.time(),trigger='prefix'))
        for state in ('intent','sending'):
            self.core.call('conversation',dict(ids,operation='transition',state=state))
        for user,reply,digest in [('other input','reply',sha('reply')),('real input','other reply',sha('reply'))]:
            with self.assertRaisesRegex(ValueError,'accepted digests'):
                self.core.call('conversation',dict(ids,operation='transition',state='accepted',
                    outbound_id='900',response_sha256=digest,context_user=user,context_reply=reply))
        row=self.core.call('conversation',dict(ids,operation='get'))
        self.assertEqual(row['state'],'sending')
        self.assertEqual(self.core.dialogue.scopes,{})

    async def test_new_prompt_budget_is_explicitly_bounded_at_core(self):
        accepted=self.core.call('think',{'prompt':'x'*6000,'metadata_only':True})
        self.assertIn('say',accepted)
        with self.assertRaises(ValueError):self.core.call('think',{'prompt':'x'*6001})
        self.assertEqual(self.adapter.turn_seconds,59)
        self.assertEqual(self.adapter.drain_bound,22)

    async def test_provider_voice_distinguishes_planning_dialogue_and_history(self):
        profile=self.core.call('status')['profile']
        provider=LMStudioProvider('http://127.0.0.1:1234/v1/chat/completions','test-only')
        with patch('greg_model.post_chat',return_value=Response('{"say":"next step"}')) as post:
            provider.generate(profile,'What should we do next?')
        system=post.call_args.kwargs['json']['messages'][0]['content']
        # Persona now comes from persona.md, not the stored one-line stub.
        self.assertIn('You are Gregory.',system)
        self.assertNotIn('AI character',system)
        self.assertIn('suggest a next step without a recorded precedent',system)
        self.assertIn('not proof of a past event',system)
        self.assertIn('Do not invent experiences, capabilities or completed actions',system)
        self.assertEqual(self.core.call('status')['profile'],profile)


if __name__=='__main__':unittest.main()
