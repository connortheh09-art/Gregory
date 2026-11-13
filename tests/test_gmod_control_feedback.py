"""Slice 3 fixtures: what the game observed for a control decision, in model terms.

Telemetry here is hand-written in the documented `state.drive` shape (docs/GMOD_CONTROLLER.md);
tests/test_drive.lua checks that the Lua draft produces that shape. Not evidence of live play.
"""
from pathlib import Path
from types import SimpleNamespace
import ast
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'deployments/oldpc'), str(ROOT / 'tests')]
from test_gmod_control_contract import OFFER, OWNER, World, drive  # also stubs requests if missing
from gregory_core.decision_contract import TurnChoices
from gregory_core.screen import ScreenBuffer
from greg_controller_core import DirectController
from greg_supervised import CoreGameAuthority, bounded_turn_prompt
from gmod_controller import GModAdapter, GModControl, observed
from test_gmod_controller import Clock, Mailbox


class Feedback(World):
    def setUp(self):
        super().setUp()
        self.seq = 1

    def tele(self, **fields):
        self.seq += 1
        block = dict(v=1, ctl=7, active=False, gen=0, stopGen=0, held={}, mode='walk')
        block.update(fields)
        return dict(self.state, seq=self.seq, drive=block)

    def result(self, surface, state):
        surface.observe(state)
        return (surface.offer(state) or {}).get('result')

    def test_nothing_to_report_before_a_decision(self):
        surface, _, _ = self.surface()
        self.assertNotIn('result', surface.offer(self.state))

    def test_pending_then_active_then_ended_from_game_reports_only(self):
        surface, controller, _ = self.surface()
        surface.apply(drive(pace='run', seconds=5), self.native, self.state)
        self.assertEqual(self.result(surface, self.tele()), dict(status='pending'))
        motion = dict(gen=1, ctl=7, t=1.24, moved=105, dz=32, air=[dict(up=50, land=32, dist=55)], drop=0)
        active = self.result(surface, self.tele(active=True, gen=1, held=['forward'], speed=210, blocked=True,
                                                jump='done', motion=motion))
        self.assertEqual(active, dict(status='active', speed_mps=4.0, blocked=True, jump='done', seconds=1.2,
                                      moved_m=2.0, rise_m=0.6, air=[dict(up_m=1.0, landed_m=0.6, fwd_m=1.0)]))
        ended = self.result(surface, self.tele(gen=1, lastEnd='expired', prevMotion=motion,
                                               motion=dict(motion, gen=9)))
        self.assertEqual((ended['status'], ended['ended'], ended['moved_m']), ('ended', 'time_up', 2.0))
        self.assertNotIn('speed_mps', ended)  # live readings only while it holds

    def test_endings_map_to_plain_reasons(self):
        surface, _, _ = self.surface()
        surface.apply(drive(), self.native, self.state)
        self.result(surface, self.tele(active=True, gen=1, held=['forward']))
        for raw, plain in [('model_stop', 'stopped'), ('lease_expired', 'lost_contact'), ('task_selected', 'task_took_over'),
                           ('interlock', 'interrupted'), (None, 'interrupted')]:
            with self.subTest(raw=raw):
                self.assertEqual(self.result(surface, self.tele(gen=1, lastEnd=raw))['ended'], plain)

    def test_a_decision_the_game_never_applied_says_so(self):
        clock = Clock()
        controller = DirectController(GModAdapter(), Mailbox(clock), run_id=7, clock=clock)
        surface = GModControl(controller, people=self.link.people)
        surface.observe(self.state)
        surface.apply(drive(seconds=1), self.native, self.state)
        clock.t += 1.1
        controller.tick()
        self.assertEqual(self.result(surface, self.tele()), dict(status='not_applied'))

    def test_another_run_or_world_reports_nothing(self):
        surface, controller, _ = self.surface()
        surface.apply(drive(), self.native, self.state)
        status = controller.status()
        self.assertIsNone(observed(self.tele(ctl=8, active=True, gen=1), status, 7))
        self.assertIsNone(observed(dict(self.tele(active=True, gen=1), bridgeSession='other'), status, 7))
        self.assertIsNone(observed(dict(self.state, drive='x'), status, 7))
        self.assertIsNone(observed(self.tele(), status, None))

    def test_motion_facts_are_metres_bounded_and_never_guessed(self):
        surface, controller, _ = self.surface()
        surface.apply(drive(), self.native, self.state)
        air = [dict(up=10, land=0, dist=20), dict(up='x', land=0, dist=0), dict(up=60, land=-200, dist=40),
               dict(up=52.5, land=52.5, dist=105), dict(up=1, land=-1, dist=1)]
        motion = dict(gen=1, ctl=7, t=2, moved=52.5, dz=4, drop=210, air=air, airborne=True)
        facts = observed(self.tele(gen=1, motion=motion), controller.status(), 7)
        self.assertEqual(facts['air'], [dict(up_m=1.1, landed_m=-3.8, fwd_m=0.8), dict(up_m=1.0, landed_m=1.0, fwd_m=2.0),
                                        dict(up_m=0.0, landed_m=-0.0, fwd_m=0.0)])
        self.assertEqual((facts['moved_m'], facts['dropped_m'], facts['airborne']), (1.0, 4.0, True))
        self.assertNotIn('rise_m', facts)  # under 8 u is noise, not a climb
        other = observed(self.tele(gen=1, motion=dict(motion, gen=2), prevMotion=dict(motion, ctl=8)), controller.status(), 7)
        self.assertNotIn('moved_m', other)  # neither record belongs to this decision of this run
        empty = observed(self.tele(gen=1, motion=dict(gen=1, ctl=7, air={}, moved='far')), controller.status(), 7)
        self.assertEqual(set(empty), {'status'})

    def test_flight_and_look_results_belong_to_this_decision(self):
        surface, controller, _ = self.surface()
        surface.apply(drive(fly='on'), self.native, self.state)
        state = self.tele(active=True, gen=1, noclip=dict(state='refused', gen=1),
                          reject=dict(gen=1, reason='look_target_missing'))
        self.assertEqual({k: observed(state, controller.status(), 7)[k] for k in ('fly', 'look')},
                         dict(fly='refused', look='target_missing'))
        older = self.tele(active=True, gen=1, noclip=dict(state='active', gen=0), reject=dict(gen=0, reason='look_target_missing'))
        self.assertFalse({'fly', 'look'} & set(observed(older, controller.status(), 7)))

    def test_jump_and_blocked_are_live_readings(self):
        surface, controller, _ = self.surface()
        surface.apply(drive(jump='tap'), self.native, self.state)
        self.result(surface, self.tele(active=True, gen=1, held=['forward']))
        moving = observed(self.tele(active=True, gen=1, held=['forward'], blocked=False), controller.status(), 7)
        self.assertNotIn('blocked', moving)
        ended = observed(self.tele(gen=1, jump='missed', blocked=True), controller.status(), 7)
        self.assertFalse({'jump', 'blocked'} & set(ended))
        other = observed(self.tele(active=True, gen=5, held=['forward']), controller.status(), 7)
        self.assertEqual(other['status'], 'ended')  # a hold of another generation is not this decision


class Context(World):
    def test_the_turn_sees_the_latest_control_offer_not_a_3s_old_one(self):
        authority = CoreGameAuthority(None)
        authority.observe(self.state, {})
        catalog = SimpleNamespace(choices=lambda state: [])
        authority.offer(self.state, catalog, [], True, 10, control=dict(OFFER, result=dict(status='pending')))
        authority.offer(self.state, catalog, [], True, 11, control=dict(OFFER, result=dict(status='active')))
        self.assertEqual(authority.context(self.state)['activity_options']['control']['result'], dict(status='active'))
        self.assertTrue(authority.context(self.state)['activity_options']['spawn_choices'] == [])
        other = dict(self.state, bridgeSession='next')
        authority.observe(other, {})
        self.assertNotIn('control', authority.context(other).get('activity_options', {}))

    def test_players_carry_distance_and_bearing_but_no_position(self):
        row = self.native['players'][0]
        self.assertEqual((row['distance_m'], row['bearing_relative']), (9.5, -170))
        prompt, _ = bounded_turn_prompt('', 'where is Connor', {}, [], [], task_view=TurnChoices(self.native).view)
        self.assertIn('"distance_m":9.5', prompt)
        self.assertNotIn('"position"', prompt)

    def test_budget_drops_bearings_then_result_then_control(self):
        c = TurnChoices(self.native)
        live = dict(activity_options=dict(binding=self.binding, control=dict(OFFER, result=dict(status='active', moved_m=2.0))))
        seen = set()
        base = len(bounded_turn_prompt('', 'q', live, [], [], task_view=c.view)[0].split('\nRECENT_DIALOGUE:')[0])
        room = 5800 - len('\nRECENT_DIALOGUE:[]') - base
        for size in range(room - 50, room + 1000, 5):
            context = {}
            try:
                bounded_turn_prompt('x' * size, 'q', live, [], [], task_view=c.view, decision_context=context)
            except ValueError:
                continue
            control = context['live']['activity_options'].get('control')
            kept = (any('bearing_relative' in p for p in context['task_view']['players']), bool(control and 'result' in control),
                    bool(control))
            self.assertTrue((not kept[0] or kept[1]) and (not kept[1] or kept[2]), kept)
            seen.add(kept)
        self.assertEqual(seen, {(True, True, True), (False, True, True), (False, False, True), (False, False, False)})


class Frames(World):
    def test_an_inspected_frame_is_stamped_with_movement_since_capture(self):
        surface, _, _ = self.surface()
        for seq, (when, x, z) in enumerate([(100., 0, 0), (100.5, 52.5, 0), (101., 105, -52.5)], 10):
            surface.observe(dict(self.state, seq=seq, pos=dict(x=x, y=0, z=z)), now=when)
        surface.observe(dict(self.state, seq=12, pos=dict(x=999, y=0, z=0)), now=101.2)  # same sample again
        self.assertEqual(len(surface.track), 3)
        self.assertEqual(surface.since(100.25), dict(moved_m_since=1.5, rise_m_since=-1.0))
        self.assertEqual(surface.since(101.3), dict(moved_m_since=0.0, rise_m_since=0.0))
        for outside in (99.9, 101.6, float('nan'), 'x'):
            self.assertIsNone(surface.since(outside))
        surface.observe(dict(self.state, seq=13, bridgeSession='next', pos=dict(x=0, y=0, z=0)), now=101.4)
        self.assertIsNone(surface.since(100.25))  # another world's history says nothing about this one

    def test_screen_buffer_adds_the_adapter_note_only_when_small_and_sane(self):
        buffer = ScreenBuffer('src', 'sess')
        buffer.frames.append((b'jpeg', dict(frame_id='f', game='gmod', sha256='0', source='src', session='sess',
                                            captured_at=time.time(), width=1, height=1), buffer.clock()))
        self.assertNotIn('game_facts', buffer.inspect('sess')[1])
        for note, expected in [({'moved_m_since': 1.5}, {'moved_m_since': 1.5}), ({}, None), ('x', None),
                               ({'k': 'v' * 300}, None)]:
            buffer.annotator = lambda captured_at, note=note: note
            with self.subTest(note=note):
                meta = buffer.inspect('sess')[1]
                self.assertEqual((meta.get('game_facts'), meta['game']), (expected, 'gmod'))  # never the game label
        buffer.annotator = lambda captured_at: 1 / 0
        self.assertEqual(buffer.inspect('sess')[1]['status'], 'ready')  # a broken hook never costs the frame

    def test_bridge_wires_the_frame_stamp_and_feeds_samples(self):
        source = (ROOT / 'deployments/oldpc/gmod_bridge.py').read_text()
        self.assertIn('game_screen.buffer.annotator=lambda captured_at: DIRECT_CONTROL.since(captured_at) '
                      'if DIRECT_CONTROL is not None else None', source)
        self.assertIn('if DIRECT_CONTROL is not None and latest:DIRECT_CONTROL.observe(latest)', source)


if __name__ == '__main__':
    unittest.main()
