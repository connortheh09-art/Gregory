"""Verify the frozen recovery inputs without game, model or network access."""
from pathlib import Path
import hashlib
import json

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / 'recovery/2026-11-12/SNAPSHOT_MANIFEST.json').read_text())
failed = []
for row in manifest['files']:
    path = root / row['path']
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
        failed.append(row['path'])
if failed:
    raise SystemExit('Recovery hash mismatch: ' + ', '.join(failed))
print(f"Verified {len(manifest['files'])} recovery file hashes")
