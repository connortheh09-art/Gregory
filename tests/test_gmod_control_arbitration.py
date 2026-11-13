"""Slice 4 fixtures: direct control and game tasks share one body.

A drive pauses the current task (or ends it with task:"end"); the paused task resumes once
direct control has settled; nothing bypassing the controller may move or release him while it
holds. Bridge blocks are extracted from gmod_bridge.py and run against fakes, as in Slice 2.
Not evidence of live play.
"""
from pathlib import Path
from types import SimpleNamespace
import ast
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'deployments/oldpc'), str(ROOT / 'tests')]
from test_gmod_control_contract import OFFER, World, drive  # also stubs requests if missing
from gregory_core.decision_contract import SchemaViolation, TurnChoices
from greg_controller_core import DirectController
from greg_game_tasks import GameTasks
from gmod_controller import GModAdapter, GModControl, translate
from test_gmod_controller import Clock, Mailbox

SOURCE = (ROOT / 'deployments/oldpc/gmod_bridge.py').read_text()
TREE = ast.parse(SOURCE)


def block(predicate):
    """The first statement list in gmod_bridge.py matching predicate(body, index) -> length."""
    for node in ast.walk(TREE):
        for field in ('body', 'orelse'):
            body = getattr(node, field, None)
            if isinstance(body, list):
                for i in range(len(body)):
                    n = predicate(body, i)
                    if n:
                        return ast.fix_missing_locations(ast.Module(body=body[i:i + n], type_ignores=[]))
    raise AssertionError('bridge block not found')


def run(module, **env):
    import gmod_bridge as bridge
    scope = dict(bridge.__dict__)
    scope.update(env)
    exec(compile(module, 'gmod_bridge-extract', 'exec'), scope)
    return scope


class Base(World):
    def setUp(self):
        super().setUp()
        self.seq = 1
        self.clock = Clock()

    def control(self):
        controller = DirectController(GModAdapter(), Mailbox(self.clock), run_id=7, clock=self.clock)
        surface = GModControl(controller, people=self.link.people)
        surface.observe(self.state)
        return surface, controller, controller._write

    def tele(self, **fields):
        self.seq += 1
        block_ = dict(v=1, ctl=7, active=False, gen=0, stopGen=0, held={}, mode='walk')
        block_.update(fields)
        return dict(self.state, seq=self.seq, drive=block_)

    def follow(self, now=2):
        self.assertEqual(self.link.apply(dict(action='game_task', kind='follow', target=self.native['players'][0]['id']),
                                         self.native, self.state, self.runtime, now), 'accepted')
        return dict(self.link.active)


class Pause(Base):
    def test_a_paused_task_plans_nothing_and_its_clocks_stand_still(self):
        task = self.follow()
        self.assertTrue(self.link.pause(10))
        self.assertFalse(self.link.pause(11))  # the first pause time is kept
        self.assertIsNone(self.link.tick(self.runtime, self.state, 12))
        self.assertTrue(self.link.engaged)  # still his task: autonomous play stays out
        self.assertTrue(self.link.resume(40))
        self.assertFalse(self.link.resume(41))
        self.assertEqual(self.link.active['deadline'], task['deadline'] + 30)
        self.assertNotIn('paused_at', self.link.active)
        self.assertEqual(self.link.tick(self.runtime, self.state, 41)['action'], 'navigate')

    def test_stay_and_review_clocks_shift_too(self):
        self.link.apply(dict(action='game_task', kind='hold', stay_seconds=20), self.native, self.state, self.runtime, 2)
        self.link.active['review_until'] = 50
        self.link.pause(5)
        self.link.resume(15)
        self.assertEqual((self.link.active['expires_at'], self.link.active['review_until']), (32, 60))

    def test_a_world_change_still_ends_a_paused_task(self):
        self.follow()
        self.link.pause(3)
        self.assertEqual(self.link.tick(self.runtime, dict(self.state, bridgeSession='next'), 4), {'action': 'wait'})
        self.assertIsNone(self.link.active)

    def test_replan_or_cancel_while_paused(self):
        task = self.follow()
        self.link.pause(10)
        self.link.update(self.runtime, self.state, 20)
        view = self.link.snapshot()
        self.assertEqual(self.link.apply(dict(action='game_task', kind='continue'), view, self.state, self.runtime, 20), 'continued')
        self.assertIn('paused_at', self.link.active)  # continuing is not a new plan
        self.assertEqual(self.link.apply(dict(action='game_task', kind='hold', task_id=task['id']), view, self.state,
                                         self.runtime, 30), 'accepted')
        self.assertEqual((self.link.active['deadline'], 'paused_at' in self.link.active), (task['deadline'] + 20, False))
        self.link.pause(31)
        self.link.update(self.runtime, self.state, 32)
        self.link.apply(dict(action='game_task', kind='cancel'), self.link.snapshot(), self.state, self.runtime, 32)
        self.assertIsNone(self.link.active)

    def test_the_model_sees_a_paused_task(self):
        self.follow()
        self.link.pause(3)
        self.link.update(self.runtime, self.state, 4)
        self.assertIn('"paused":true', GameTasks.instruction(self.link.snapshot()))


class Contract(Base):
    def schema(self, internal=False):
        self.link.update(self.runtime, self.state, 3)
        c = TurnChoices(self.link.snapshot())
        return c, c.schema(c.view, dict(binding=self.binding, control=OFFER), internal=internal)

    def test_task_choice_is_offered_only_with_a_task(self):
        c, s = self.schema()
        with self.assertRaises(SchemaViolation):
            c.decode(drive(task='pause'), s)
        self.follow()
        c, s = self.schema()
        for choice in ('pause', 'end'):
            self.assertEqual(c.decode(drive(task=choice), s)['task'], choice)
        with self.assertRaises(SchemaViolation):
            c.decode(drive(task='cancel'), s)
        c.decode(drive(), s)  # optional: absent means pause

    def test_translate_refuses_an_unknown_task_choice(self):
        with self.assertRaisesRegex(ValueError, 'pause or end'):
            translate(drive(task='later'), self.native, self.state)
        translate(drive(task='end'), self.native, self.state)


class Lifecycle(Base):
    def test_holding_gates_movement_until_the_game_settles_the_release(self):
        surface, controller, box = self.control()
        self.assertEqual((surface.holding(), surface.allows({'action': 'navigate'})), (False, True))
        surface.apply(drive(seconds=1), self.native, self.state)
        surface.observe(self.tele(active=True, gen=1, held=['forward']))
        for action, allowed in [({'action': 'navigate'}, False), ({'action': 'wait'}, False), ({'action': 'use'}, False),
                                ({'action': 'select'}, False), ({'action': 'say', 'text': 'hi'}, True),
                                ({'action': 'spawn_item', 'id': 'x'}, True)]:
            with self.subTest(action=action):
                self.assertEqual(surface.allows(action), allowed)
        self.assertIsNone(surface.settle())
        self.clock.t += 1.1
        surface.tick()  # the intent expires: a fenced release goes out
        self.assertEqual(box.actions()[-1]['action'], 'wait')
        self.assertTrue(surface.holding())  # not settled until the game says so
        self.assertIsNone(surface.settle())
        surface.observe(self.tele(gen=1, stopGen=2))
        self.assertFalse(surface.holding())
        self.assertEqual(surface.settle(), 'expired')
        self.assertIsNone(surface.settle())  # once
        self.assertEqual(controller.publish_task({'action': 'navigate'}, 'route'), ('published', ''))

    def test_the_game_acknowledging_the_stop_settles_it(self):
        surface, controller, _ = self.control()
        surface.apply(drive(), self.native, self.state)
        surface.apply(dict(action='control', command='stop'), self.native, self.state)
        surface.observe(self.tele(gen=1, stopGen=2, held=['duck']))  # fence raised; clearance not yet seen
        release = controller.status()['release']
        self.assertEqual((release['acknowledged'], release['released']), (True, False))
        self.assertFalse(surface.holding())
        self.assertEqual(surface.settle(), 'model_stop')

    def test_an_unconfirmed_release_settles_after_its_retries(self):
        surface, _, _ = self.control()
        surface.apply(drive(seconds=1), self.native, self.state)
        self.clock.t += 1.1
        surface.tick()
        for _ in range(8):  # the game never answers: retries run out
            self.clock.t += .5
            surface.tick()
        self.assertTrue(surface.controller.status()['release']['unconfirmed'])
        self.assertFalse(surface.holding())
        self.assertEqual(surface.settle(), 'expired')

    def test_a_new_decision_mid_move_is_not_an_ending(self):
        surface, _, _ = self.control()
        surface.apply(drive(), self.native, self.state)
        surface.apply(drive(move='left'), self.native, self.state)
        self.assertTrue(surface.holding())
        self.assertIsNone(surface.settle())

    def test_stop_with_nothing_held_sends_nothing(self):
        surface, controller, box = self.control()
        self.assertEqual(surface.apply(dict(action='control', command='stop'), self.native, self.state)['noop'], True)
        self.assertEqual((box.actions(), controller.generation, surface.settle()), ([], 0, None))
        surface.apply(drive(), self.native, self.state)
        self.assertNotIn('noop', surface.apply(dict(action='control', command='stop'), self.native, self.state))
        surface.observe(self.tele(gen=1, stopGen=2))
        self.assertEqual(surface.settle(), 'model_stop')


class Bridge(Base):
    LOOP = staticmethod(lambda body, i: 1 if isinstance(body[i], ast.If) and ast.unparse(body[i].test) == 'DIRECT_CONTROL is not None'
                        and 'settle' in ast.unparse(body[i]) else 0)
    WRITE = staticmethod(lambda body, i: 3 if isinstance(body[i], ast.Assign) and ast.unparse(body[i]) == 'held_back = False' else 0)
    PLAN = staticmethod(lambda body, i: 1 if isinstance(body[i], ast.If) and ast.unparse(body[i].test) == 'chosen_voice_activity' else 0)

    def test_owner_loop_resumes_the_paused_task_once_control_settles(self):
        task = self.follow()
        surface, _, _ = self.control()
        surface.apply(drive(seconds=1), self.native, self.state)
        self.link.pause(5)
        logs, loop = [], block(self.LOOP)
        env = dict(DIRECT_CONTROL=surface, latest=self.tele(active=True, gen=1, held=['forward']), game_tasks=self.link,
                   now=6, log=logs.append)
        run(loop, **env)
        self.assertIn('paused_at', self.link.active)
        self.clock.t += 1.1  # loop tick expires it
        run(loop, **env)
        run(loop, **dict(env, latest=self.tele(gen=1, stopGen=2), now=9))
        self.assertNotIn('paused_at', self.link.active)
        self.assertEqual(self.link.active['deadline'], task['deadline'] + 4)
        self.assertEqual(logs, ['CORE_CONTROL_ENDED {"reason": "expired", "task_resumed": true}'])

    def write(self, action, holding):
        written = []
        surface = SimpleNamespace(allows=lambda a: not holding or a.get('action') not in {'wait', 'navigate', 'move'})
        env = run(block(self.WRITE), DIRECT_CONTROL=surface, action=action, seq=0, cmd_path=None, latest={}, session='s',
                  mode='free', game_authority=None, MEMORY=None, now=0, interval=.5, goal='',
                  write_cmd=lambda path, seq, a, *rest: written.append(a) or False, log=lambda *a: None)
        return written, env['held_back']

    def test_legacy_movement_is_held_back_but_its_speech_still_goes_out(self):
        self.assertEqual(self.write({'action': 'navigate', 'id': 'r'}, True), ([], True))
        self.assertEqual(self.write({'action': 'wait', 'speech': {'id': 'x', 'text': 'Nice.'}}, True),
                         ([{'action': 'say', 'text': 'Nice.'}], False))
        self.assertEqual(self.write({'action': 'navigate', 'id': 'r'}, False), ([{'action': 'navigate', 'id': 'r'}], False))

    def test_no_route_or_autonomous_plan_while_direct_control_holds(self):
        def boom(*a):
            raise AssertionError('planned while direct control held the body')
        for holding, expected in [(True, None), (False, {'action': 'navigate'})]:
            env = run(block(self.PLAN), chosen_voice_activity=False, action={'action': 'wait'},
                      DIRECT_CONTROL=SimpleNamespace(holding=lambda h=holding: h),
                      game_tasks=SimpleNamespace(engaged=True, tick=(boom if holding else lambda *a: {'action': 'navigate'})),
                      PLAYERCORE=SimpleNamespace(autonomous=boom), latest={}, now=0, intent=None)
            with self.subTest(holding=holding):
                self.assertEqual(env['action'], expected)

    def test_stop_paths_and_other_legacy_writes_respect_direct_control(self):
        self.assertIn("if DIRECT_CONTROL is not None:DIRECT_CONTROL.controller.stop('supervised_drain')", SOURCE)
        self.assertIn('if DIRECT_CONTROL is None or DIRECT_CONTROL.allows({"action": "look"}):write_cmd(', SOURCE)
        self.assertIn('if valid and mode == "chat" and (DIRECT_CONTROL is None or DIRECT_CONTROL.allows({"action": "wait"})):', SOURCE)


if __name__ == '__main__':
    unittest.main()
