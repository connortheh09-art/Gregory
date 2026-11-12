"""Negative probes for the reviewed sampler baseline seam; no live processes."""
from pathlib import Path
import importlib.util
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gregory_core.canary_preflight import Monitor


def sample(elapsed, active=0):
    return dict(elapsed=elapsed, active=active, game_pid=1, game_start=1,
        bridge_pid=2, bridge_start=2, game_ws=2*1024**3, game_private=2*1024**3,
        bridge_ws=100*1024**2, bridge_private=100*1024**2, available=4*1024**3,
        state_age=.1, alive=True, supervised=True, recorder_ok=True)


class BaselineProbes(unittest.TestCase):
    def test_overflow_rejection_cannot_be_caught_and_rewarmed(self):
        monitor = Monitor(); monitor.accept(sample(0))
        with self.assertRaises(OverflowError):
            monitor.accept(dict(sample(5), game_ws=10**1000))
        ready = False
        for elapsed in range(10, 136, 5):
            try: ready |= monitor.accept(sample(elapsed))['baseline_ready']
            except ValueError: pass
        self.assertFalse(ready, 'an overflow rejection was caught and rewarmed')
        self.assertTrue(monitor.baseline_failed)

    def test_activity_latches_even_when_another_guard_also_rejects_the_sample(self):
        failures = [dict(state_age=4), dict(available=1), dict(supervised=False),
            dict(alive=False), dict(recorder_ok=False), dict(active=301),
            dict(elapsed=1801), dict(elapsed=20), dict(elapsed=0),
            dict(bridge_start=3), dict(bridge_pid=3), dict(game_ws=float('nan')),
            dict(available=None)]
        for changes in failures:
            with self.subTest(changes=changes):
                monitor = Monitor(); monitor.accept(sample(0))
                value = dict(sample(5, active=1), **changes)
                with self.assertRaises(ValueError): monitor.accept(value)
                ready = False
                for elapsed in range(10, 136, 5):
                    try: ready |= monitor.accept(sample(elapsed))['baseline_ready']
                    except ValueError: pass
                self.assertFalse(ready, 'a rejected active sample was caught and rewarmed')
                self.assertTrue(monitor.baseline_failed)

    def test_rejected_growth_cannot_be_caught_and_counted_as_a_valid_baseline(self):
        monitor = Monitor(); monitor.accept(sample(0))
        value = dict(sample(5), game_ws=3*1024**3)
        with self.assertRaisesRegex(ValueError, 'growth rate'): monitor.accept(value)
        with self.assertRaisesRegex(ValueError, 'baseline'): monitor.accept(sample(10))
        self.assertTrue(monitor.baseline_failed)

    def test_sampler_started_during_activity_cannot_build_a_baseline(self):
        monitor = Monitor()
        with self.assertRaisesRegex(ValueError, 'baseline'):
            monitor.accept(sample(0, active=10))
        self.assertIsNone(monitor.baseline)

    def test_activity_before_full_baseline_cannot_be_cleared_and_rewarmed(self):
        monitor = Monitor()
        for elapsed in range(0, 61, 5):
            monitor.accept(sample(elapsed))
        with self.assertRaisesRegex(ValueError, 'baseline'):
            monitor.accept(sample(65, active=1))
        with self.assertRaisesRegex(ValueError, 'baseline'):
            monitor.accept(sample(70))
        self.assertIsNone(monitor.baseline)

    def test_one_late_timestamp_is_not_a_120_second_observed_baseline(self):
        monitor = Monitor()
        self.assertFalse(monitor.accept(sample(120))['baseline_ready'])
        for elapsed in range(125, 240, 5):
            self.assertFalse(monitor.accept(sample(elapsed))['baseline_ready'])
        self.assertTrue(monitor.accept(sample(240))['baseline_ready'])

    def test_active_run_after_a_complete_inactive_baseline_is_allowed(self):
        monitor = Monitor()
        for elapsed in range(0, 121, 5):
            monitor.accept(sample(elapsed))
        self.assertTrue(monitor.accept(sample(125, active=5))['baseline_ready'])


class SamplerFailureProbes(unittest.TestCase):
    def module(self):
        file = Path(__file__).resolve().parents[1] / 'tools/greg_canary_monitor.py'
        spec = importlib.util.spec_from_file_location('canary_sampler_probe', file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def args(self, root):
        return ['sampler', '--game-pid', '1', '--bridge-pid', '2',
            '--csv', str(root/'samples.csv'), '--status', str(root/'status.json'),
            '--state', str(root/'state.json'), '--recorder-db', str(root/'recorder.sqlite3'),
            '--active-marker', str(root/'active'), '--supervisor-marker', str(root/'supervisor')]

    def test_preexisting_active_marker_refuses_before_sampling(self):
        sampler = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'active').touch()
            with patch.object(sys, 'argv', self.args(root)), patch.object(sampler, 'process_memory') as process:
                with self.assertRaises(SystemExit):
                    sampler.main()
                process.assert_not_called()

    def test_status_publication_failure_does_not_mask_sample_failure(self):
        sampler = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(sys, 'argv', self.args(root)), \
                    patch.object(sampler, 'process_memory', side_effect=RuntimeError('sample-origin')), \
                    patch.object(sampler, 'atomic_status', side_effect=OSError('publish-failed')):
                with self.assertRaisesRegex(RuntimeError, 'sample-origin'):
                    sampler.main()

    def test_failure_publication_interrupt_never_masks_the_primary_exception(self):
        sampler = self.module()
        for primary in (RuntimeError, KeyboardInterrupt, SystemExit):
            for secondary in (KeyboardInterrupt, SystemExit):
                with self.subTest(primary=primary, secondary=secondary), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    with patch.object(sys, 'argv', self.args(root)), \
                            patch.object(sampler, 'process_memory', side_effect=primary('original')), \
                            patch.object(sampler, 'atomic_status', side_effect=secondary('publication')):
                        observed = None
                        try: sampler.main()
                        except BaseException as exc: observed = exc
                        self.assertIs(type(observed), primary)
                        self.assertEqual(str(observed), 'original')


if __name__ == '__main__':
    unittest.main()
