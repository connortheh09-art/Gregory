"""Execute the real bridge's chat/preemption AST blocks with fixture telemetry.

No rewritten copy of their logic, no game/model/Windows claims.
"""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'deployments/oldpc')]
import gmod_bridge as bridge
from greg_supervised import TickWriter, SessionWindow



# The only change to the qualified shutdown since the 2026-11-12 baseline (Slice 4 R1, Gordon
# S4-R1): the final stop may carry the direct-control fence. Default behaviour is unchanged.
QUALIFIED_SHUTDOWN_DELTA=((", stop_action=None)", ")"),
                          ("dict(stop_action or {'action': 'wait'})", "{'action': 'wait'}"))

class Lane:
    def __init__(self): self.messages=[];self.invalidated=0
    def hear(self, text): self.messages.append(text)
    def invalidate(self): self.invalidated+=1


def exercise_chat(source, text, *, supervised, draining=False, game_tasks=None):
    tree=ast.parse(source)
    run=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_run_bridge')
    chat=next(n for n in ast.walk(run) if isinstance(n,ast.For) and
              ast.unparse(n.iter)=='chat_tail.read_new()')
    context=next(n for n in ast.walk(run) if isinstance(n,ast.Assign) and
                 any(isinstance(t,ast.Name) and t.id=='context' for t in n.targets))
    preempt=next(n for n in ast.walk(run) if isinstance(n,ast.If) and
                 ast.unparse(n.test).startswith('context != previous_context'))
    intent=bridge.Intent();intent.self_goal='visit the park'
    state=dict(map='gm_construct',bridgeSession='fixture-bridge',controlEpoch=1)
    mode=intent.choose(1)[0]
    previous=(bridge.interaction_context('STEAM_0:0:2000',state,intent.version,mode,True)
              if supervised else ('STEAM_0:0:2000','fixture-bridge',1,intent.version,False))
    lane=Lane() if supervised else None
    runtime=SimpleNamespace(goal_active=True)
    def directive(*a): runtime.goal_active=False
    runtime.directive=directive
    row=json.dumps(dict(user='Connor',steamid='STEAM_0:1:1000',msg=text,t=1))
    writes=[]
    env=dict(bridge.__dict__)
    env.update(game_screen=None,run_voice_log=None,game_tasks=game_tasks,intent=intent,latest=state,target='STEAM_0:0:2000',allow={'Connor'},now=2,
        chat_tail=SimpleNamespace(read_new=lambda:[row]),chat_gate=bridge.ChatGate(),
        a=SimpleNamespace(no_social=True,supervised_session=supervised,
                          supervised_owner_steamid='STEAM_0:1:1000'),
        supervised=lane,supervised_say=None,session_window=SessionWindow(0,300),supervised_draining=draining,
        CHAT_MEMORY=SimpleNamespace(add=lambda *a:None,kind=lambda *a:False),
        PLAYERCORE=runtime,tracker=None,ready_trace=None,pending_say=None,ready=None,
        previous_context=previous,valid=True,was_actionable=True,command_due=0,
        cmd_path='fixture-mailbox',seq=0,session='fixture-session',mode=mode,
        write_cmd=lambda *a,**k:writes.append(a[2]) or True,log=lambda *a:None)
    choose=ast.parse('mode, goal = intent.choose(now)').body[0]
    unit=ast.Module(body=[chat,choose,context,preempt],type_ignores=[])
    exec(compile(ast.fix_missing_locations(unit),'<actual-bridge-caller-blocks>','exec'),env)
    return intent,runtime,lane,writes


class BridgeTests(unittest.TestCase):
    def test_baseline_reproduces_chat_preemption_and_candidate_preserves_goal(self):
        base=ROOT/'recovery/2026-11-12/fixtures/baseline/gmod_bridge.py'
        old_intent,old_runtime,_,old_writes=exercise_chat(base.read_text(),
            'Nice barrel you found.',supervised=False)
        self.assertIn({'action':'wait'},old_writes)
        self.assertFalse(old_runtime.goal_active)
        self.assertEqual(old_intent.self_goal,'')
        intent,runtime,lane,writes=exercise_chat(Path(bridge.__file__).read_text(),
            'Nice barrel you found.',supervised=True)
        self.assertEqual(writes,[])
        self.assertTrue(runtime.goal_active)
        self.assertEqual(intent.self_goal,'visit the park')
        self.assertEqual(intent.version,0)
        self.assertEqual(lane.messages,['Nice barrel you found.'])

    def test_stop_preempts_with_wait_in_same_actual_caller_tick(self):
        intent,runtime,lane,writes=exercise_chat(Path(bridge.__file__).read_text(),
            'stop',supervised=True)
        self.assertEqual(writes,[{'action':'wait'}])
        self.assertFalse(runtime.goal_active)
        self.assertGreater(intent.version,0)
        self.assertGreater(lane.invalidated,0)

    def test_one_write_per_tick_and_stop_bypasses_normal_cadence(self):
        writes=[]
        writer=TickWriter(lambda *a,**k:writes.append(a[2]) or True)
        def send(action, mode='chat'):
            return writer.publish('fixture',1,action,{},'session',mode)
        writer.begin_tick(1)
        self.assertTrue(send({'action':'navigate'}))
        self.assertFalse(send({'action':'say','text':'hello'}))
        self.assertFalse(send({'action':'wait'},'stop'))
        writer.begin_tick(1.1)
        self.assertEqual(writes,[{'action':'navigate'},{'action':'wait'}])
        self.assertFalse(send({'action':'say','text':'hello'}))
        writer.begin_tick(1.5)
        self.assertTrue(send({'action':'say','text':'hello'}))

    def test_pending_speech_no_longer_blocks_the_real_movement_tick_condition(self):
        tree=ast.parse(Path(bridge.__file__).read_text())
        expr=next(n.test for n in ast.walk(tree) if isinstance(n,ast.If) and
                  ast.unparse(n.test).startswith('now >= command_due and (pending_say'))
        compiled=compile(ast.Expression(expr),'<actual-movement-condition>','eval')
        for active,expected in [(True,True),(False,False)]:
            self.assertEqual(eval(compiled,dict(now=10,command_due=9,pending_say=(20,1,'hello'),
                a=SimpleNamespace(supervised_session=active))),expected)

    def test_qualified_shutdown_and_producer_group_unchanged(self):
        base=ROOT/'recovery/2026-11-12/fixtures/baseline'
        def function(p,name,delta=()):
            text=ast.unparse(next(n for n in ast.parse(p.read_text()).body if
                isinstance(n,ast.FunctionDef) and n.name==name))
            for new,old in delta:
                self.assertEqual(text.count(new),1,new);text=text.replace(new,old)
            return ast.dump(ast.parse(text),include_attributes=False)
        self.assertEqual(function(base/'gmod_bridge.py','shutdown_bridge'),
                         function(Path(bridge.__file__),'shutdown_bridge',QUALIFIED_SHUTDOWN_DELTA))
        self.assertEqual((base/'greg_producers.py').read_bytes(),
                         (ROOT/'deployments/oldpc/greg_producers.py').read_bytes())


if __name__=='__main__':unittest.main()
