"""Slice 2 fixtures: Core's typed control decision -> GMod adapter -> controller -> wire.

Pins the decision contract (offer, turn-local labels, bounds), the GMod mapping,
publication in the actual bridge block and the task handoff. As in Slice 1 the game
is a model; none of this is evidence of Lua or live game behaviour.
"""
from pathlib import Path
from types import SimpleNamespace
import ast
import json
import math
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'deployments/oldpc'), str(ROOT / 'tests')]
try:
    import requests  # noqa: F401  (bridge imports; absent in some reviewer containers)
except ImportError:
    sys.modules['requests'] = SimpleNamespace(post=None, get=None, RequestException=Exception)

from gregory_core.decision_contract import (CONTROL_MOVES, CONTROL_PACES, CONTROL_TURNS,
                                            SchemaViolation, TurnChoices, enum, envelope, obj)
from gregory_core.runtime import FixtureProvider
from greg_controller_core import DirectController
from greg_supervised import CoreGameAuthority, bounded_turn_prompt, reply_surface
from greg_agenda import Agenda
from gmod_controller import GModAdapter, GModControl, translate, validate
import test_vc_game_tasks as fixture
from test_gmod_controller import Clock, Mailbox

OWNER = 'STEAM_0:1:1000'
OFFER = dict(mode='walk', active=False, seconds_left=0, max_seconds=30, fly=['on', 'off'])


def drive(**fields):
    return dict(action='control', command='drive', **{'move': 'forward', 'look': 'ahead', 'pace': 'walk', 'jump': 'none', 'seconds': 3, **fields})


class World(unittest.TestCase):
    """The fixture nav world plus a drive-capable client and one other player (Connor)."""
    def setUp(self):
        fixture.TaskTests.setUp(self)
        self.state.update(steamid='STEAM_0:0:7', seq=1, dead=False, menu=False, inVehicle=False,
                          ang=dict(p=0, y=170, r=0), capabilities=dict(playercore=True, drive=1),
                          drive=dict(v=1, ctl=0, active=False, gen=0, stopGen=0, held={}, mode='walk'),
                          players=[dict(steamid=OWNER, name='Connor', fresh=True, pos=dict(x=500, y=0, z=0))])
        self.link.update(self.runtime, self.state, 1)
        self.native = self.link.snapshot()
        self.binding = list(self.native['binding'])

    def contract(self, offer=OFFER, internal=False):
        c = TurnChoices(self.native)
        return c, c.schema(c.view, dict(binding=self.binding, control=offer), internal=internal)

    def surface(self, run_id=7):
        box = Mailbox(Clock())
        controller = DirectController(GModAdapter(), box, run_id=run_id)
        controller.observe(self.state)
        return GModControl(controller, people=self.link.people), controller, box


class Contract(World):
    def test_no_offer_or_internal_turn_means_no_control_branch(self):
        for offer, internal in [(None, False), (OFFER, True)]:
            c, s = self.contract(offer, internal)
            with self.subTest(offer=offer, internal=internal), self.assertRaises(SchemaViolation):
                c.decode(drive(), s)

    def test_owner_turn_offers_drive_and_stop_with_turn_local_labels(self):
        c, s = self.contract(dict(OFFER, active=True))
        self.assertEqual(c.decode(drive(look='P1'), s)['look'], dict(player=self.native['players'][0]['id']))
        self.assertEqual(c.decode(drive(look='D1'), s)['look'], dict(destination=self.native['destinations'][0]['id']))
        self.assertEqual(c.decode(drive(look='turn_left'), s)['look'], 'turn_left')
        self.assertEqual(c.decode(dict(action='control', command='stop'), s), dict(action='control', command='stop'))

    def test_lean_menu_and_hint(self):
        # Lean L1: the action is generated before the spoken line.
        c, s = self.contract()
        self.assertEqual(list(s['properties'])[:2], ['intent', 'say'])
        # Lean L3: beside control, drive covers relative moves and stop covers cancel.
        from greg_game_tasks import GameTasks
        self.assertNotIn('move', GameTasks.allowed_kinds(True, {}, True, True, control=True))
        self.assertIn('move', GameTasks.allowed_kinds(True, {}, True, True))
        # Lean L4: a jump example, and stop explained only when it is offered.
        from gregory_core.decision_contract import control_hint
        idle, busy = control_hint(OFFER), control_hint(OFFER, task=True)
        self.assertIn('"move":"none","look":"ahead","pace":"walk","jump":"tap"', idle)
        self.assertIn('"look":"turn_right","pace":"run"', idle)  # L6: run + turn example
        self.assertNotIn('"command":"stop"', idle)
        self.assertIn('"command":"stop"', busy)
        self.assertIn('When asked to stop, halt or stay put', busy)  # L8
        self.assertIn('"command":"stop"', control_hint(dict(OFFER, active=True)))
        # 0023: a talk-only example (intent null) and a back example, with walk listed last.
        self.assertIn('intent null', idle)
        self.assertIn('"move":"back"', idle)
        self.assertLess(idle.index('"move":"none"'), idle.index('"move":"forward","look":"ahead"'))
        # 0023: a running autonomous route (explore/tour) is something to stop.
        self.assertIn('"command":"stop"', control_hint(dict(OFFER, route=True)))

    def test_drive_must_choose_look_pace_and_jump(self):
        # Lean L6: no silent defaults for the modifiers Gemma dropped (0019 replay: run/turn 0/20).
        c, s = self.contract()
        for missing in ('look', 'pace', 'jump'):
            intent = drive(); intent.pop(missing)
            with self.subTest(missing=missing), self.assertRaises(SchemaViolation):
                c.decode(intent, s)
        self.assertNotIn('look', c.decode(drive(look='ahead'), s))  # ahead = keep facing

    def test_stop_is_offered_only_with_something_to_stop(self):
        # Lean L2: idle with no task, stop is not on the menu (the real-VC no-op stops).
        stop = dict(action='control', command='stop')
        c, s = self.contract()
        with self.assertRaises(SchemaViolation):
            c.decode(stop, s)
        self.assertEqual(c.decode(drive(move='none', jump='tap', seconds=1), s)['jump'], 'tap')
        native = dict(self.native, current_task=dict(id='t1', kind='follow', target=dict(id=self.native['players'][0]['id']), attempts=0))
        c = TurnChoices(native)
        s = c.schema(c.view, dict(binding=self.binding, control=OFFER))
        self.assertEqual(c.decode(stop, s), stop)
        for kind in ('cancel', 'move'):  # Lean L3: stop and drive cover these beside control
            with self.subTest(kind=kind), self.assertRaises(SchemaViolation):
                c.decode(dict(action='game_task', kind=kind, task_id='T1'), s)

    def test_unknown_labels_native_ids_bad_bounds_and_shapes_are_refused(self):
        c, s = self.contract()
        bad = [drive(look='P9'), drive(look=self.native['players'][0]['id']), drive(speed=1), drive(pace='sprint'),
               drive(seconds=0), drive(seconds=31), drive(seconds=2.5), drive(move='up'),
               dict(action='control', command='drive', seconds=3), dict(action='control', command='drive', move='forward'),
               dict(action='control', command='stop', seconds=3), dict(action='control', command='jump')]
        for intent in bad:
            with self.subTest(intent=intent), self.assertRaises(SchemaViolation):
                c.decode(intent, s)

    def test_look_targets_are_the_shown_rows_not_a_hidden_visit_target(self):
        native = dict(self.native, current_task=dict(id='t1', kind='visit', target=dict(id='gone'), attempts=0))
        c = TurnChoices(native)
        s = c.schema(c.view, dict(binding=self.binding, control=OFFER))
        hidden = 'D' + str(len(self.native['destinations']) + 1)
        c.decode(dict(action='game_task', kind='visit', target=hidden), s)  # still a visit option
        with self.assertRaises(SchemaViolation):
            c.decode(drive(look=hidden), s)  # but not a place the adapter could aim at

    def test_flight_fields_follow_the_offer(self):
        c, s = self.contract(dict(OFFER, fly=[]))
        for intent in [drive(fly='on'), drive(vertical='up')]:
            with self.subTest(intent=intent), self.assertRaises(SchemaViolation):
                c.decode(intent, s)
        c, s = self.contract()
        self.assertEqual(c.decode(drive(fly='on', vertical='up'), s)['fly'], 'on')

    def test_max_seconds_comes_from_the_offer_and_stays_bounded(self):
        c, s = self.contract(dict(OFFER, max_seconds=10))
        c.decode(drive(seconds=10), s)
        with self.assertRaises(SchemaViolation):
            c.decode(drive(seconds=11), s)
        for limit in (99, 'x', 0, True):
            c, s = self.contract(dict(OFFER, max_seconds=limit))
            with self.subTest(limit=limit):
                c.decode(drive(seconds=30), s)
                with self.assertRaises(SchemaViolation):
                    c.decode(drive(seconds=31), s)

    def test_screen_followup_keeps_a_control_proposal_only_in_game_scope(self):
        from gregory_core.screen import generate_with_screen
        schema = envelope([dict(type='null'), obj(dict(action=enum(['inspect_screen']))),
                           obj(dict(action=enum(['control']), command=enum(['stop'])))])
        for allowed in (True, False):
            replies = [dict(say='Looking.', intent=dict(action='inspect_screen'), used_memory_ids=[]),
                       dict(say='Stopping.', intent=dict(action='control', command='stop'), used_memory_ids=[])]

            class P(FixtureProvider):
                def generate(self, profile, prompt, **kw):
                    return replies.pop(0)
            source = SimpleNamespace(inspect=lambda session: (None, dict(status='unavailable')))
            reply = generate_with_screen(P(), {}, 'hi', source, 's', time.monotonic() + 2, [],
                                         allow_game_task=allowed, response_schema=schema)
            with self.subTest(allowed=allowed):
                self.assertEqual(reply.get('intent'), dict(action='control', command='stop') if allowed else None)

    def test_hint_renders_exactly_when_the_schema_offers_control(self):
        offered = dict(binding=self.binding, control=OFFER)
        for live, internal, shown in [(dict(activity_options=offered), False, True),
                                      (dict(activity_options=offered), True, False),
                                      (dict(activity_options=dict(binding=self.binding)), False, False)]:
            context = {}
            prompt, _ = bounded_turn_prompt('', 'walk to me', live, [], [], internal=internal,
                                            task_view=TurnChoices(self.native).view, decision_context=context)
            with self.subTest(internal=internal, shown=shown):
                self.assertEqual('BODY CONTROL' in prompt, shown)
                self.assertEqual('control' in context['live']['activity_options'], 'control' in live['activity_options'])

    def test_budget_pressure_drops_the_control_offer_not_the_turn(self):
        c = TurnChoices(self.native)
        context = {}
        live = dict(activity_options=dict(binding=self.binding, control=OFFER))
        bare = bounded_turn_prompt('', 'q', dict(activity_options=dict(binding=self.binding)), [], [],
                                   task_view=c.view, decision_context={})[0]
        # A prefix that fits without control but not with its hint and offer.
        room = 5800 - len('\nRECENT_DIALOGUE:[]') - len(bare.split('\nRECENT_DIALOGUE:')[0])
        prompt, _ = bounded_turn_prompt('x' * (room - 10), 'q', live, [], [], task_view=c.view, decision_context=context)
        self.assertNotIn('BODY CONTROL', prompt)
        schema = c.schema(context['task_view'], context['live']['activity_options'])
        with self.assertRaises(SchemaViolation):
            c.decode(drive(), schema)


class Mapping(World):
    def wire(self, intent, state=None):
        params, seconds, ignored = translate(intent, self.native, state or self.state,
                                             lambda alias, s: next((sid for r, sid in self.link.people(s) if r['id'] == alias), None))
        action, mode = GModAdapter().hold_action(SimpleNamespace(params=validate(params), generation=1), 1.5, 7)
        return action, seconds, ignored

    def test_every_core_vocabulary_value_maps_to_valid_inputs(self):
        for move in CONTROL_MOVES:
            for pace in CONTROL_PACES:
                self.wire(drive(move=move, pace=pace))
        for look in CONTROL_TURNS:
            self.wire(drive(look=look))

    def test_paces_and_diagonals_on_the_wire(self):
        action, _, _ = self.wire(drive(move='forward_left', pace='run'))
        self.assertAlmostEqual(action['move']['forward'], math.sqrt(.5))
        self.assertAlmostEqual(action['move']['right'], -math.sqrt(.5))
        self.assertEqual(action['move']['speed'], 1.)
        self.assertEqual(self.wire(drive(pace='sneak'))[0]['move']['speed'], .25)
        self.assertEqual(self.wire(drive())[0]['move']['speed'], .5)  # walk when no pace is given
        self.assertEqual(self.wire(drive(move='back'))[0]['move']['forward'], -1.)
        self.assertEqual([self.wire(drive(move=m))[0]['move']['right'] for m in ('left', 'right')], [-1., 1.])

    def test_relative_turns_use_the_heading_at_publication(self):
        for look, yaw in [('turn_left', 260.), ('turn_right', 80.), ('turn_around', 350.), ('slight_right', 140.)]:
            with self.subTest(look=look):
                self.assertEqual(self.wire(drive(look=look))[0]['look'], dict(yaw=yaw, rate=180.))
        self.assertEqual(self.wire(drive(look='up'))[0]['look'], dict(pitch=-45., rate=180.))
        self.assertNotIn('look', self.wire(drive())[0])  # no look: the view is left alone
        with self.assertRaisesRegex(ValueError, 'heading'):
            self.wire(drive(look='turn_left'), dict(self.state, ang=None))

    def test_tracked_targets_carry_a_stand_off(self):
        player = dict(player=self.native['players'][0]['id'])
        self.assertEqual(self.wire(drive(look=player))[0]['look'], dict(steamid=OWNER, rate=180., near=80.))
        point = [float(v) for v in self.native['destinations'][0]['position']]
        destination = dict(destination=self.native['destinations'][0]['id'])
        self.assertEqual(self.wire(drive(look=destination))[0]['look'], dict(point=point, rate=180., near=40.))
        gone = dict(self.state, players=[dict(self.state['players'][0], fresh=False)])
        with self.assertRaisesRegex(ValueError, 'not present'):
            self.wire(drive(look=player), gone)
        with self.assertRaisesRegex(ValueError, 'unoffered'):
            self.wire(drive(look=dict(destination='elsewhere')))

    def test_flight_and_vertical(self):
        action, _, ignored = self.wire(drive(fly='on', vertical='up'))
        self.assertEqual((action['mode'], action['move']['up'], ignored), ('noclip', 1., []))
        action, _, ignored = self.wire(drive(vertical='up'))
        self.assertEqual((action.get('mode'), action['move']['up'], ignored), (None, 0., ['vertical']))
        flying = dict(self.state, drive=dict(self.state['drive'], mode='noclip'))
        self.assertEqual(self.wire(drive(vertical='down'), flying)[0]['move']['up'], -1.)
        self.assertEqual(self.wire(drive(fly='off', vertical='down'), flying)[2], ['vertical'])

    def test_use_is_one_flag_and_slice1_envelopes_are_unchanged(self):
        self.assertIs(self.wire(drive(use=True))[0]['use'], True)
        self.assertNotIn('use', self.wire(drive())[0])
        action, _ = GModAdapter().hold_action(SimpleNamespace(params=validate(dict(forward=1., yaw=90.)), generation=1), 1.5, 7)
        self.assertEqual(set(action), {'action', 'v', 'ctl', 'gen', 'lease', 'move', 'jump', 'crouch', 'look'})
        self.assertEqual(action['look'], dict(yaw=90., rate=180.))

    def test_validate_refuses_bad_look_targets(self):
        for params in [dict(look_steamid='Connor'), dict(look_point=[0, 0]), dict(look_point=[0, 0, float('nan')]),
                       dict(look_point=[0, 0, 1e9]), dict(look_steamid=OWNER, yaw=10), dict(look_point=[0, 0, 0], pitch=5),
                       dict(look_near=50), dict(look_steamid=OWNER, look_near=600), dict(use=1)]:
            with self.subTest(params=params), self.assertRaises(ValueError):
                validate(params)

    def test_translate_refuses_unbounded_shapes(self):
        for intent in [dict(drive(), speed=1), dict(drive(), seconds=31), dict(drive(), seconds=True), drive(move='up'),
                       drive(pace='sprint'), drive(look='sideways'), drive(look=dict(player='a', destination='b')),
                       drive(fly='maybe'), dict(action='control', command='stop'), dict(action='game_task', kind='hold')]:
            with self.subTest(intent=intent), self.assertRaises(ValueError):
                self.wire(intent)


class Surface(World):
    def test_offer_appears_only_when_a_decision_could_be_accepted(self):
        surface, _, _ = self.surface()
        self.assertEqual(surface.offer(self.state), OFFER)
        refused = dict(self.state, seq=2, drive=dict(self.state['drive'], noclip=dict(state='refused')))
        self.assertNotIn('fly', surface.offer(refused))
        self.assertIsNone(self.surface(run_id=None)[0].offer(self.state))  # no reserved run: fail closed
        old = dict(self.state, capabilities=dict(playercore=True))
        old.pop('drive')
        surface, controller, _ = self.surface()
        controller.observe(dict(old, seq=2))
        self.assertIsNone(surface.offer(old))  # old Lua is never offered a verb it would ignore

    def test_drive_publishes_one_tracked_hold_and_reports_active(self):
        surface, controller, box = self.surface()
        detail = surface.apply(drive(look=dict(player=self.native['players'][0]['id']), pace='run', seconds=5),
                               self.native, self.state)
        self.assertEqual((detail['generation'], detail['transport']), (1, 'published'))
        hold = box.actions('drive')[-1]
        self.assertEqual((hold['ctl'], hold['gen'], hold['look']['steamid'], hold['move']['speed']), (7, 1, OWNER, 1.))
        offer = surface.offer(self.state)
        self.assertTrue(offer['active'])
        self.assertEqual(offer['seconds_left'], 5)

    def test_a_new_decision_mid_move_replaces_without_a_release(self):
        surface, _, box = self.surface()
        surface.apply(drive(), self.native, self.state)
        surface.apply(drive(move='left', look='turn_left'), self.native, self.state)
        self.assertEqual([a['action'] for a in box.actions()], ['drive', 'drive'])
        self.assertEqual(box.actions()[-1]['gen'], 2)

    def test_stop_wins_even_from_a_stale_view(self):
        surface, controller, box = self.surface()
        surface.apply(drive(), self.native, self.state)
        stale = dict(self.native, binding=['other_map', 's', 1])
        surface.apply(dict(action='control', command='stop'), stale, self.state)
        release = box.actions()[-1]
        self.assertEqual((release['action'], release['ctl'], release['reason']), ('wait', 7, 'model_stop'))
        self.assertIsNone(controller.status()['intent'])

    def test_stale_or_refused_drive_changes_nothing(self):
        surface, controller, box = self.surface()
        with self.assertRaisesRegex(ValueError, 'stale control decision'):
            surface.apply(drive(), dict(self.native, binding=['other_map', 's', 1]), self.state)
        controller.observe(dict(self.state, seq=2, dead=True))
        with self.assertRaisesRegex(ValueError, 'not_actionable'):
            surface.apply(drive(), self.native, self.state)
        self.assertEqual((controller.generation, box.actions()), (0, []))

    def test_yield_to_task_releases_a_hold_then_lets_routes_write(self):
        surface, controller, box = self.surface()
        surface.apply(drive(), self.native, self.state)
        self.assertEqual(controller.publish_task({'action': 'navigate'}, 'route')[1], 'direct_active')
        surface.yield_to_task()
        self.assertEqual(box.actions()[-1]['reason'], 'task_selected')
        self.assertEqual(controller.publish_task({'action': 'navigate'}, 'route'), ('published', ''))
        sent = len(box.actions())
        surface.yield_to_task()  # nothing held: no extra release
        self.assertEqual(len(box.actions()), sent)


class Publication(World):
    """The actual gmod_bridge publication block, extracted and run as in test_core_game_authority."""
    def publish(self, intent, *, control=None, offer='default', internal=False, view=None, stale=False):
        import gmod_bridge as bridge
        tree = ast.parse((ROOT / 'deployments/oldpc/gmod_bridge.py').read_text())
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.If)
                    and ast.unparse(n.test).startswith('supervised_say is not None and now >= command_due'))
        delivered, ended = [], []
        authority = CoreGameAuthority(None)
        authority.observe(self.state, {})
        self.runtime.end_goal = lambda status, reason: ended.append((status, reason))

        class Catalog:
            def entries(c, state):
                return [dict(id='entity:car', name='Car', key='car')], {}
        stamp = ('voice', 1)
        request = dict(generation=0, voice_metadata=dict(request_id='r'), delivery_stamp=('voice', 0) if stale else stamp,
                       trace=None)
        if internal:
            request.pop('voice_metadata')
            request.update(game_attention=True, output_surface='voice')
        offered = dict(binding=self.binding, control=OFFER) if offer == 'default' else offer
        row = dict(request=request, say='On my way.', game_intent=intent, game_task_view=view or self.link.snapshot(),
                   screen_observations=[], activity_options=offered)
        env = dict(bridge.__dict__)
        env.update(supervised_say=row, now=2, command_due=0, game_tasks=self.link, game_authority=authority,
                   supervised=SimpleNamespace(generation=0, published=lambda row, ok, **kw: delivered.append(row)),
                   agenda=Agenda(Catalog(), 'unused', 'unused'), voice_activity=None, latest=self.state,
                   voice_session=SimpleNamespace(stamp=lambda: stamp, offer=lambda row: True), PLAYERCORE=self.runtime,
                   tracker=SimpleNamespace(pending_speech_trace=None, decision_result=lambda *a, **kw: None),
                   ready=None, run_voice_log=None, game_screen=None, reply_surface=reply_surface, log=lambda *a: None,
                   DIRECT_CONTROL=control)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), 'actual-publication', 'exec'), env)
        return delivered[0], authority, ended

    def follow(self):
        self.assertEqual(self.link.apply(dict(action='game_task', kind='follow', target=self.native['players'][0]['id']),
                                         self.native, self.state, self.runtime, 2), 'accepted')

    def test_accepted_drive_pauses_the_task_and_notes_a_request_not_a_result(self):
        self.follow()
        surface, controller, box = self.surface()
        row, authority, ended = self.publish(drive(), control=surface)
        self.assertEqual(row['task_outcome'], dict(verdict='accepted', kind='control_drive', generation=1,
                                                   transport='published', ignored=[], task='paused'))
        self.assertEqual(row['say'], 'On my way.')
        self.assertEqual(self.link.active['paused_at'], 2)  # Slice 4: paused, not ended
        self.assertEqual(ended, [('abandoned', 'core_direct_control')])
        self.assertEqual({k: authority.events[-1][k] for k in ('kind', 'command', 'qualification')},
                         dict(kind='control', command='drive', qualification='requested_not_confirmed'))
        self.assertEqual(box.actions()[-1]['action'], 'drive')

    def test_a_drive_can_end_the_task_instead(self):
        self.follow()
        surface, _, _ = self.surface()
        row, _, _ = self.publish(drive(task='end'), control=surface)
        self.assertEqual((row['task_outcome']['task'], self.link.active), ('ended', None))

    def test_stop_ends_direct_control_and_the_task(self):
        self.follow()
        surface, controller, box = self.surface()
        row, _, ended = self.publish(dict(action='control', command='stop'), control=surface, offer={})
        # Lean L3: one stop. No hold of his to release, but the task ends (route dropped).
        self.assertEqual((row['task_outcome']['verdict'], row['task_outcome'].get('task'), self.link.active),
                         ('accepted', 'ended', None))
        self.assertEqual(box.actions(), [])
        row, _, ended = self.publish(dict(action='control', command='stop'), control=surface, offer={})
        self.assertEqual((row['task_outcome']['verdict'], row['task_outcome']['reason']), ('unchanged', 'nothing_to_stop'))
        surface.apply(drive(), self.native, self.state)
        row, _, ended = self.publish(dict(action='control', command='stop'), control=surface, offer={})
        self.assertEqual((row['task_outcome']['verdict'], box.actions()[-1]['action'], ended), ('accepted', 'wait', []))
        self.assertEqual(controller.publish_task({'action': 'navigate'}, 'route'), ('published', ''))

    def test_refused_control_changes_nothing_and_is_not_a_task_refusal(self):
        self.follow()
        task = dict(self.link.active)
        for control, offer, internal, reason in [
                (None, 'default', False, 'direct control unavailable'),
                (self.surface()[0], dict(binding=self.binding), False, 'control was not offered'),
                (self.surface()[0], 'default', True, 'owner turns only')]:
            with self.subTest(reason=reason):
                row, authority, ended = self.publish(drive(), control=control, offer=offer, internal=internal)
                self.assertEqual(row['task_outcome']['verdict'], 'refused')
                self.assertIn(reason, row['task_outcome']['reason'])
                self.assertNotEqual(row['say'], 'On my way.')
                self.assertEqual((self.link.active, self.link.refusals, self.link.last_refusal, ended), (task, 0, None, []))
                self.assertEqual(authority.events[-1]['kind'], 'control_refused')

    def test_stop_ends_an_autonomous_route_and_holds_the_agenda(self):
        # 0023 (live 0022 FAIL 2): explore/tour is neither a drive nor a task, so stop was never offered.
        import gmod_bridge as bridge
        self.assertNotIn('route', bridge.route_offer(dict(OFFER), self.runtime))
        self.runtime.goals.start('explore', 'agenda', self.state, 1)
        self.assertIs(bridge.route_offer(dict(OFFER), self.runtime)['route'], True)
        c = TurnChoices(self.native)
        s = c.schema(c.view, dict(binding=self.binding, control=dict(OFFER, route=True)))
        stop = dict(action='control', command='stop')
        self.assertEqual(c.decode(stop, s), stop)
        surface, controller, box = self.surface()
        from unittest.mock import patch
        held = []
        with patch.object(Agenda, 'hold', lambda agenda, now, seconds=60: held.append(now)):
            row, _, ended = self.publish(stop, control=surface, offer={})
        self.assertEqual((row['task_outcome']['verdict'], row['task_outcome'].get('route')), ('accepted', 'ended'))
        self.assertEqual((ended, held), ([('abandoned', 'core_control_stop')], [2]))
        agenda = Agenda(None, 'unused', 'unused')
        agenda.hold(10)
        self.assertEqual((agenda.next_at, agenda.reconsider_at), (70, 70))
        self.assertEqual(box.actions(), [])  # nothing of his held: no release that would cancel Lua routes

    def test_a_refused_stop_is_not_reported_as_a_refused_move(self):
        row, _, _ = self.publish(dict(action='control', command='stop'), control=None, offer={})
        self.assertEqual((row['task_outcome']['kind'], row['say']), ('control_stop', "I couldn't stop just now."))
        row, _, _ = self.publish(drive(), control=None)
        self.assertEqual(row['say'], "I can't move like that right now.")

    def test_accepted_task_or_moving_activity_hands_the_body_back(self):
        calls = []
        control = SimpleNamespace(yield_to_task=lambda: calls.append('yield'), apply=None)
        row, _, _ = self.publish(dict(action='game_task', kind='follow', target=self.native['players'][0]['id']),
                                 control=control)
        self.assertEqual((row['task_outcome']['verdict'], calls), ('accepted', ['yield']))
        self.link.update(self.runtime, self.state, 3)
        row, _, _ = self.publish(dict(action='game_task', kind='continue'), control=control)
        self.assertEqual((row['task_outcome']['verdict'], calls), ('continued', ['yield']))  # not a new plan
        row, _, _ = self.publish(dict(action='game_activity', choice=dict(activity='rest')), control=control)
        self.assertEqual((row['task_outcome']['verdict'], calls), ('accepted', ['yield', 'yield']))

    def test_a_stale_voice_delivery_applies_no_control(self):
        calls = []
        control = SimpleNamespace(apply=lambda *a: calls.append(a), yield_to_task=None)
        row, authority, ended = self.publish(drive(), control=control, stale=True)
        self.assertEqual((calls, row.get('task_outcome'), row['say'], ended), ([], None, 'On my way.', []))

    def test_bridge_feeds_the_controller_offer_to_the_turn_context(self):
        tree = ast.parse((ROOT / 'deployments/oldpc/gmod_bridge.py').read_text())
        call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call) and ast.unparse(n.func) == 'game_authority.offer')
        self.assertEqual([ast.unparse(k.value) for k in call.keywords if k.arg == 'control'],
                         ['route_offer(DIRECT_CONTROL.offer(latest), PLAYERCORE) if DIRECT_CONTROL is not None else None'])  # 0023

    def test_owner_turn_reaches_the_wire_as_one_tracked_hold(self):
        surface, controller, box = self.surface()
        offered = dict(binding=self.binding, control=surface.offer(self.state))
        c = TurnChoices(self.native)
        schema = c.schema(c.view, offered)
        intent = c.decode(dict(action='control', command='drive', move='forward', pace='run', look='P1', jump='none', seconds=5), schema)
        row, _, _ = self.publish(intent, control=surface, offer=offered, view=self.native)
        self.assertEqual(row['task_outcome']['verdict'], 'accepted')
        hold = box.actions('drive')[-1]
        self.assertEqual((hold['move']['forward'], hold['move']['speed'], hold['look']), (1., 1., dict(steamid=OWNER, rate=180., near=80.)))
        self.assertTrue(0 < hold['lease'] <= 1.5)


class Authority(World):
    def test_offer_reaches_the_turn_context_as_a_copy(self):
        authority = CoreGameAuthority(None)
        authority.observe(self.state, {})
        catalog = SimpleNamespace(choices=lambda state: [])
        offer = dict(OFFER, fly=['on'])
        authority.offer(self.state, catalog, [], True, 10, control=offer)
        offer['fly'].append('off')
        self.assertEqual(authority.context(self.state)['activity_options']['control'], dict(OFFER, fly=['on']))
        authority.offer(self.state, catalog, [], True, 20)
        self.assertNotIn('control', authority.context(self.state)['activity_options'])


if __name__ == '__main__':
    unittest.main()
