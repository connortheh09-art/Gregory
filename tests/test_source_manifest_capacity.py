from pathlib import Path
import sys,unittest
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'deployments/oldpc')]
sys.modules.setdefault('requests',SimpleNamespace())  # Offline collector import, never a real HTTP call.
import gmod_bridge as bridge
import greg_events
from greg_events import sanitize

class ManifestCapacity(unittest.TestCase):
    def test_recorded_build_keeps_every_manifest_file(self):
        snapshot=bridge.source_manifest()
        self.assertFalse(snapshot['truncated'])
        self.assertEqual(sanitize(snapshot)['files'],snapshot['files'])
        ids={entry['id'] for entry in snapshot['files']}
        self.assertTrue({'lua/greg_locomotion.lua','greg_controller_core.py','gmod_controller.py'}<=ids)

    def test_beyond_the_shared_cap_truncation_stays_explicit(self):
        with patch.object(greg_events,'MANIFEST_FILES',3):
            snapshot=bridge.source_manifest()
            self.assertTrue(snapshot['truncated'])
            self.assertEqual(len(snapshot['files']),3)
            self.assertEqual(sanitize(snapshot)['files'],snapshot['files'])

if __name__=='__main__':unittest.main()
