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
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'deployments/oldpc'), str(ROOT / 'tests')]
from test_gmod_control_contract import OFFER, World, drive  # also stubs requests if missing
from gregory_core.decision_contract import SchemaViolation, TurnChoices
from greg_controller_core import DirectController
from greg_game_tasks import GameTasks
from gmod_controller import GModAdapter, GModControl, bridge_publisher, shutdown_fence, translate
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

    def test_settling_a_paused_task_starts_a_fresh_stay(self):
        # Gordon S4-R3: settle installs fresh timestamps, so the pause must be reconciled first.
        self.link.apply(dict(action='game_task', kind='visit', target=self.native['destinations'][0]['id'],
                             completion='observe_cover'), self.native, self.state, self.runtime, 2)
        self.link.active.update(phase='needs_review', review_until=50)
        self.link.pause(10)
        self.link.update(self.runtime, self.state, 30)
        frame = [dict(status='ready', session='screen', captured_at=time.time())]
        self.assertEqual(self.link.apply(dict(action='game_task', kind='settle', task_id=self.link.active['id'],
                                              stay_seconds=20), self.link.snapshot(), self.state, self.runtime, 30,
                                         screen_observations=frame, screen_session='screen'), 'accepted')
        self.assertNotIn('paused_at', self.link.active)
        self.link.resume(31)
        self.assertEqual(self.link.active['expires_at'], 50)

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


    def test_a_retired_run_never_lets_legacy_movement_or_release_through(self):
        # Gordon S4-R2: a newer run owns the fence; the old run's core refuses publish_task, and
        # the legacy gate must agree instead of reading "not holding" as "free".
        surface, controller, box = self.control()
        surface.apply(drive(), self.native, self.state)
        surface.observe(self.tele(ctl=8, active=True, gen=1, held=['forward']))
        self.assertEqual(controller.retired, 'controller_superseded')
        self.assertFalse(surface.holding())
        self.assertEqual(controller.publish_task({'action': 'wait'}, 'route')[0], 'refused')
        for action, allowed in [({'action': 'wait'}, False), ({'action': 'navigate'}, False),
                                ({'action': 'say', 'text': 'hi'}, True)]:
            with self.subTest(action=action):
                self.assertEqual(surface.allows(action), allowed)

    def shutdown(self, retired=False):
        """The bridge's actual finally block and shutdown_bridge, after a tick that already wrote
        (Gordon S4-R1/R2 probes). Returns every envelope written, in order, and the hold."""
        from unittest.mock import patch
        from greg_supervised import TickWriter
        import gmod_bridge as bridge
        sent = []

        def raw(path, seq, action, state, session, mode, observer=None):
            sent.append(dict(seq=seq, action=dict(action), session=session, mode=mode))
            if observer is not None:
                observer(sent[-1], write_result='written')
            return True
        tick, seqs, state = TickWriter(raw), iter(range(1, 100)), self.state
        controller = DirectController(GModAdapter(), bridge_publisher(tick.publish, 'cmd', lambda: next(seqs),
                                                                      lambda: state, 's'),
                                      run_id=7, clock=self.clock)
        surface = GModControl(controller, people=self.link.people)
        surface.observe(state)
        tick.begin_tick(0)
        surface.apply(drive(), self.native, state)  # consumes this tick
        if retired:
            state = self.tele(ctl=8, active=True, gen=1, held=['forward'])
            surface.observe(state)
        run_bridge = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == '_run_bridge')
        final = next(n for n in ast.walk(run_bridge) if isinstance(n, ast.Try) and n.finalbody
                     and 'shutdown_bridge' in ast.unparse(n.finalbody)).finalbody
        env = run(ast.fix_missing_locations(ast.Module(body=final[:2], type_ignores=[])),
                  DIRECT_CONTROL=surface, tick_writer=tick, log=lambda line: None)
        self.assertIsNone(tick.pending_stop)  # nothing left queued
        call = next(n for n in ast.walk(ast.Module(body=final, type_ignores=[])) if isinstance(n, ast.Call)
                    and ast.unparse(n.func) == 'shutdown_bridge')
        kw = {k.arg: ast.unparse(k.value) for k in call.keywords}
        target = eval(kw['target'], dict(env, target='fixture'))
        stop_action = eval(kw['stop_action'], env)
        noop = SimpleNamespace(request_stop=lambda: None, join_until=lambda _: None, pending=0)
        social = SimpleNamespace(request_stop=lambda: None, close=lambda **_: None, worker=noop)
        with patch.object(bridge, 'write_cmd', raw), patch.object(bridge, 'log', lambda _: None):
            bridge.shutdown_bridge(worker=noop, social=social, tracker=None, recorder=None, cmd_path='cmd',
                                   latest=state, target=target, stop_sequence=next(seqs), session='s',
                                   capture=False, state_tail=None, stop_action=stop_action)
        return sent, sent[0]

    def test_the_final_shutdown_stop_carries_the_fence(self):
        # Gordon S4-R1: a latest-envelope reader may see only the final write. It must fence.
        from test_gmod_controller import DriveReceiver
        sent, hold = self.shutdown()
        final = sent[-1]
        self.assertEqual((final['mode'], final['action']['action'], final['action']['ctl']), ('stop', 'wait', 7))
        rx = DriveReceiver()
        rx.deliver(hold, 0)
        rx.deliver(final, .4)  # only the last write is ever read
        self.assertEqual(rx.deliver(dict(hold), .41), 'released_generation')  # a delayed old hold
        self.assertFalse(rx.active)
        self.assertEqual([e['action']['action'] for e in sent], ['drive', 'wait', 'wait'])  # queued fence flushed too

    def test_a_retired_run_shuts_down_without_any_stop(self):
        # Gordon S4-R2: even a plain wait would cancel the newer owner.
        from test_gmod_controller import DriveReceiver
        sent, hold = self.shutdown(retired=True)
        self.assertEqual([e['action']['action'] for e in sent], ['drive'])
        rx = DriveReceiver()
        owner = dict(hold, action=dict(hold['action'], ctl=8))
        rx.deliver(owner, 0)
        for envelope in sent[1:]:
            rx.deliver(envelope, .4)
        self.assertTrue(rx.active)  # ctl8's hold survives

    def test_shutdown_with_nothing_held_still_fences_the_final_stop(self):
        from greg_supervised import TickWriter
        written = []
        tick = TickWriter(lambda *a, **k: written.append(a) or True)
        tick.begin_tick(10.)
        surface, controller, box = self.control()
        stop = shutdown_fence(surface, tick)
        self.assertEqual(written, [])  # nothing was queued, nothing re-sent
        self.assertEqual((stop['stop'], stop['stop_action']['ctl'], stop['stop_action']['action']), (True, 7, 'wait'))


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
        self.assertIn('if latest and (DIRECT_CONTROL is None or not DIRECT_CONTROL.controller.retired):', SOURCE)
        self.assertIn('if DIRECT_CONTROL is None or DIRECT_CONTROL.allows({"action": "look"}):write_cmd(', SOURCE)
        self.assertIn('if valid and mode == "chat" and (DIRECT_CONTROL is None or DIRECT_CONTROL.allows({"action": "wait"})):', SOURCE)


class Integration(Base):
    """Flag-gated construction (--core-direct-control): one controller per bridge run."""
    def construct(self, run_id):
        node = next(n for n in ast.walk(TREE) if isinstance(n, ast.If)
                    and ast.unparse(n.test) == "getattr(a, 'core_direct_control', False)"
                    and 'DirectController' in ast.unparse(n))
        # The block declares `nonlocal seq`, so run it inside a function like _run_bridge.
        harness = ast.parse('def harness(a, write_cmd, cmd_path, latest, session, game_tasks, log):\n'
                            '    seq = 0\n    DIRECT_CONTROL = None\n')
        fn = harness.body[0]
        fn.body += [node, ast.parse('return DIRECT_CONTROL, next_seq').body[0]]
        scope = run(ast.fix_missing_locations(harness))
        written, logs = [], []

        def write_cmd(path, seq, action, state, session, mode, observer=None):
            written.append((seq, action, mode))
            observer(action, write_result='written')
            return True
        surface, next_seq = scope['harness'](SimpleNamespace(core_direct_control=True, controller_run=run_id), write_cmd,
                                            'cmd.json', self.state, 's', self.link, logs.append)
        return surface, next_seq, written, logs

    def test_a_retired_run_skips_the_legacy_shutdown_stop(self):
        # Gordon S4-R2 (shutdown): the plain wait would cancel the newer owner. shutdown_bridge is
        # pinned unchanged and only stops when given a target, so the call site withholds it.
        run_bridge = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == '_run_bridge')
        final = ast.unparse(next(n for n in ast.walk(run_bridge) if isinstance(n, ast.Try) and n.finalbody
                                 and 'shutdown_bridge' in ast.unparse(n.finalbody)).finalbody)
        self.assertLess(final.index("shutdown_stop = dict(stop_action=None, stop=True)"), final.index('if DIRECT_CONTROL is not None'))
        self.assertIn("target=target if shutdown_stop['stop'] else None", final)
        self.assertIn("stop_action=shutdown_stop['stop_action']", final)
        shutdown = ast.unparse(next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == 'shutdown_bridge'))
        self.assertIn("if latest and target:\n        attempt('stop', stop)", shutdown)

    def test_construction_shares_the_writer_and_seq_counter(self):
        surface, next_seq, written, logs = self.construct(41)
        self.assertEqual(logs, ['CORE_DIRECT_CONTROL {"run": 41}'])
        self.assertIs(surface.people.__self__, self.link)
        surface.observe(self.state)
        surface.apply(drive(), self.native, self.state)
        self.assertEqual([(s, a['action'], a['ctl'], m) for s, a, m in written], [(1, 'drive', 41, 'direct')])
        self.assertEqual(next_seq(), 2)  # the bridge's own writes continue the same sequence

    def test_without_a_run_id_it_fails_closed(self):
        surface, _, written, _ = self.construct(None)
        surface.observe(self.state)
        self.assertIsNone(surface.offer(self.state))
        with self.assertRaisesRegex(ValueError, 'no_controller_run'):
            surface.apply(drive(), self.native, self.state)
        self.assertEqual(written, [])

    def test_run_id_is_reserved_under_the_writer_lock_and_shutdown_disconnects_first(self):
        lock = next(n for n in ast.walk(TREE) if isinstance(n, ast.With)
                    and 'command_writer_lock' in ast.unparse(n.items[0].context_expr))
        body = ast.unparse(lock)
        self.assertLess(body.index('reserve_run('), body.index('_run_bridge('))
        self.assertIn("initialize=getattr(a, 'core_direct_control_init', False)", body)
        run_bridge = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == '_run_bridge')
        final = ast.unparse(next(n for n in ast.walk(run_bridge) if isinstance(n, ast.Try) and n.finalbody
                                 and 'shutdown_bridge' in ast.unparse(n.finalbody)).finalbody)
        self.assertLess(final.index('shutdown_fence(DIRECT_CONTROL, tick_writer)'), final.index('shutdown_bridge('))
        self.assertIn('DIRECT_CONTROL', ast.unparse(run_bridge.body[0]))  # declared global
        self.assertIn("ap.error('--core-direct-control requires --supervised-session and --core-game-tasks')", SOURCE)


if __name__ == '__main__':
    unittest.main()
