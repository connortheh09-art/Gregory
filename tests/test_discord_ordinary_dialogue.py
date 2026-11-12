"""Regression for the owner's screenshot: conversation is not a lookup report."""
import unittest
import test_discord_text as fixture
from core_fixture_experience import capture_fixture


class OrdinaryDialogueTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixture.TextTests.asyncSetUp
    asyncTearDown=fixture.TextTests.asyncTearDown
    new_adapter=fixture.TextTests.new_adapter
    message=fixture.TextTests.message
    turn=fixture.TextTests.turn

    def answer(self,text,used=()):
        def generate(profile,prompt):
            self.provider.calls.append((profile,prompt))
            return {'say':text,'used_memory_ids':list(used)}
        self.provider.generate=generate

    async def test_plain_chat_and_feedback_are_not_decorated_as_memory_misses(self):
        self.answer("Sure. Let's figure it out together.")
        for index,text in enumerate(("I'm not sure, I'd have to figure that out",
                'Can you stop saying that?', 'What is your opinion on Garrys Mod?')):
            result=await self.turn(self.message(id=str(300+index),content='gregory: '+text))
            self.assertEqual(result['state'],'accepted')
            self.assertEqual(self.transport.posts[-1][1],"Sure. Let's figure it out together.")
            self.assertNotIn('[Retrieval:',self.transport.posts[-1][1])
            prompt=self.provider.calls[-1][1]
            self.assertIn(text,prompt)
            self.assertNotIn('If no matching memory, say you have no persisted memory',prompt)
            self.assertIn('Treat feedback about your replies as feedback',prompt)

    async def test_real_retrieved_hit_keeps_historical_citation_and_evidence(self):
        mid=self.core.call('import',capture_fixture(self.root/'experience'))['memory_id']
        self.answer('I remember that recorded prop observation; its outcome is unknown.',[mid])
        result=await self.turn(self.message(content='gregory: wood_crate001a'))
        self.assertEqual(result['state'],'accepted')
        self.assertIn('[Historical memory '+mid+'; not current state]',self.transport.posts[0][1])
        self.assertIn(mid,self.provider.calls[0][1])
        self.assertIn('Historical memory is not current observation',self.provider.calls[0][1])
        self.assertNotIn('[Retrieval:',self.transport.posts[0][1])

    async def test_explicit_unsupported_recall_can_still_acknowledge_uncertainty(self):
        self.answer("I don't remember that event.")
        result=await self.turn(self.message(content='gregory: Do you remember our first trip to Mars?'))
        self.assertEqual(result['state'],'accepted')
        self.assertEqual(self.transport.posts[0][1],"I don't remember that event.")
        self.assertIn('Only when asked about past experiences',self.provider.calls[0][1])
        self.assertIn('never invent an encounter',self.provider.calls[0][1])


if __name__=='__main__':unittest.main()
