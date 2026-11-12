"""RAM-window bounds, expiry and scope isolation without a clock sleep."""
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gregory_core.dialogue import DialogueWindow


class DialogueWindowTests(unittest.TestCase):
    def setUp(self):
        self.now=100
        self.window=DialogueWindow(clock=lambda:self.now)
        self.scope=dict(guild_id='1',channel_id='2',author_id='3')

    def test_retains_complete_recent_pairs_and_evicts_oldest(self):
        for n in range(7):self.window.append(self.scope,str(n),'user '+str(n),'reply '+str(n))
        messages=self.window.snapshot(self.scope)
        self.assertEqual(len(messages),8)
        self.assertEqual(messages[0],dict(role='user',content='user 3'))
        self.assertEqual(messages[-1],dict(role='assistant',content='reply 6'))
        self.window.append(self.scope,'6','duplicate','not actually spoken again')
        self.assertEqual(messages,self.window.snapshot(self.scope))

    def test_age_limit_is_per_exchange_and_reads_do_not_refresh_it(self):
        self.window.append(self.scope,'a','old','old reply')
        self.now+=600
        self.window.append(self.scope,'b','new','new reply')
        self.now+=600
        self.assertEqual([m['content'] for m in self.window.snapshot(self.scope)],['new','new reply'])
        self.now+=600
        self.assertEqual(self.window.snapshot(self.scope),[])
        self.assertFalse(self.window.scopes)

    def test_scope_isolation_lru_eviction_and_clear(self):
        self.window.append(self.scope,'a','private user','private reply')
        for key in ('guild_id','channel_id','author_id'):
            self.assertEqual(self.window.snapshot(dict(self.scope,**{key:'999'})),[])
        for n in range(7):
            self.window.append(dict(self.scope,author_id=str(10+n)),str(n),'other','other reply')
        self.window.snapshot(self.scope)  # Reading makes this scope most recent.
        self.window.append(dict(self.scope,author_id='100'),'extra','extra','extra reply')
        self.assertEqual(len(self.window.scopes),8)
        self.assertTrue(self.window.snapshot(self.scope))
        self.assertEqual(self.window.snapshot(dict(self.scope,author_id='10')),[])
        self.window.clear()
        self.assertEqual(self.window.snapshot(self.scope),[])

    def test_unicode_quotes_and_long_replies_stay_serialized_bounded(self):
        for n in range(8):
            self.window.append(self.scope,str(n),'秘密\\"'*400,'😀\\"'*500)
        messages=self.window.snapshot(self.scope)
        self.assertTrue(messages)
        self.assertLessEqual(len(json.dumps(messages)),3000)
        self.assertEqual(len(messages)%2,0)
        self.assertTrue(any(m['content'].endswith('…') for m in messages))
        messages[0]['content']='outside mutation'
        self.assertNotIn('outside mutation',json.dumps(self.window.snapshot(self.scope)))


if __name__=='__main__':unittest.main()
