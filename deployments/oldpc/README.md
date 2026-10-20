# Old-PC deployment snapshot

Captured from KELLENWORKSPACE as `lesle` on 2026-10-20. This is a verified
**on-disk source snapshot**, not a runtime acceptance result. No matching
Python/GMod/hl2 processes were returned during capture. No game was started,
stopped, or updated.

This directory is separate from the rig-era top-level `bridge/`, `playercore/`
and `lua/` imports. Do not mix their revisions. Keep these eight Python files
together: the collector imports its siblings directly. The `lua/` subtree
preserves the installed relative paths, including client/server autorun files.

## Provenance and changes

`SOURCE-MANIFEST.json` records original absolute paths, exact original mtimes,
byte counts, full original SHA-256 and imported SHA-256 for all 15 files.
Both transfer archives and every member were verified locally against the
node's hashes. Backup iterations, chat memory, logs, tokens, navigation dumps,
catalog state and generated media were not imported.

Only scrub: the personal P0 trace output path in `gmod_bridge.py` now uses
`GREG_TRACE_PATH`, defaulting to `trace.jsonl` beside the collector. Set this
to the previous absolute path to reproduce the original trace location.
No goal, movement, dialogue or timing changes were made.

## Setup reference (not performed by this import)

Use Python 3.10+ and install `requirements.txt`. The collector's `--help`
lists its options. Its existing `--data` argument selects the local GMod
`garrysmod/data` directory; `--lm` selects a local/OpenAI-compatible chat
endpoint, defaulting to `http://127.0.0.1:1234/v1/chat/completions`.
These instructions do not authorize using the paid OpenAI Platform API.

Copy the Lua subtree into the matching GMod `garrysmod/lua` tree only as a
separate deployment step. Use the existing single-writer collector handoff;
do not start another collector beside one already running. An intended
playercore launch must explicitly include `--playercore` and select the
correct actor, data directory, map/nav assets and model.

## Checks and remaining gaps

- Eight Python files compile; all local `greg_*` imports are present.
- All three client Lua includes resolve in this snapshot.
- Credential-format scan and targeted credential/path inspection completed;
  that is not a guarantee of absence of every possible secret.
- `requests` is the only third-party Python import found.
- The original collector's `--help` succeeds on the old PC and reports the
  expected bridge/playercore module paths. Gateway-side CLI checking was
  blocked by missing `requests` (and unavailable `venv` bootstrap); no host
  packages were installed to work around it.
- No Lua interpreter/GMod runtime acceptance, model request, movement test,
  or game deployment was performed.
- Runtime nav/world/catalog inputs and exact former collector command line
  remain to be established before reproducible gameplay acceptance.
- Rig launcher repair and legacy Minecraft separation remain independent
  review items on Greg's import branch.

## Transfer limitation

This Windows Companion 2026.9.8-1 connection did not advertise `file.fetch`.
The existing authorized `system.run` path was used for bounded read-back.
No gateway allowlists, sandbox settings or execution privileges were changed.
