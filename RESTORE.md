# Gregory recovery snapshot — 2026-11-12

This is a **source recovery checkpoint**, not a turnkey installer or a new deployment. It consolidates the qualified Cookie Silence R2 source, including Core harness, turn ledger, retry exhaustion and voice turn-taking, plus the seven Lua files compared with the old-PC installation on November 12. It does not contain the proposed advanced controller.

## What is preserved

- `gregory_core/`: the single Core authority and SQLite/FTS memory implementation.
- `deployments/oldpc/`: bridge, playercore, Recorder, voice client/session/protocol and game helpers.
- `deployments/oldpc/lua/`: seven current Lua files, retaining the installed directory structure.
- `tests/`: the qualified snapshot's regression fixtures.
- `recovery/2026-11-12/`: original source pins and qualification reports, current Lua pins, sanitized model-load example and a voice-host reference.

The original R2 report says "not deployed" because that was its qualification status. A later isolated supervised run queued replies to 18/18 admitted utterances, but did not prove every reply was audible or complete exact cookie/door/stop acceptance. A subsequent cross-PC relay experiment failed; those relay modifications are deliberately **not** overlaid onto this qualified baseline. No performance improvement is claimed.

## Placement and prerequisites

Last normal placement: old PC hosts GMod, Lua, capture, bridge/Core and local memory; the rig hosts LM Studio/Gemma and the Discord voice/STT/TTS client. Routine rig execution is as `openclaw`; old PC execution is as `lesle`. Discover current machines and paths; do not assume former node IDs, addresses or drive letters remain valid.

1. Clone the exact recovery branch/commit and run `python recovery/verify_snapshot.py` from its root. The manifest verifies the preserved source files, not Git history or a live installation.
2. Prepare an isolated Python environment. Install `deployments/oldpc/requirements.txt`; optional capture dependencies are in `requirements-vision.txt`, and media dependencies in `requirements-inbox-media.txt`. The last cross-PC comparison used Python 3.15.1; this is historical evidence, not a promise every dependency supports it on a clean host. Core requires working SQLite FTS5 and JSON support. Voice requires an `audioop` implementation on Python versions that removed it.
3. Obtain the model separately in LM Studio: `google/gemma-4-12b-qat`, context 16384, evaluation batch 2048, flash attention and GPU KV cache enabled. The sanitized load example uses loopback; configure the actual authorized connection locally. No model weights are stored here. Use the local/Codex lane only; do not add an OpenAI Platform key or embedding service.
4. Restore GMod and the correct map/addons separately. Back up existing Lua before copying `deployments/oldpc/lua/` into the matching `garrysmod/lua/` tree. This is the controller installation for Gregory, **not** a friend-facing addon release. Reload the appropriate client/server Lua or restart the game deliberately, then verify the actor, map and fresh telemetry. File presence alone does not prove loaded code.
5. Restore private state from a separate consistent backup **before** starting a writer: Core/Recorder/episodes SQLite databases, player/map memory directories, verified landmark provenance, nav graph and relevant local settings. Use SQLite's online backup API for active databases, or stop writers cleanly before copying. Never copy only a live main DB while ignoring its WAL. Run `PRAGMA integrity_check` on restored databases. Keep the old backup and do not attach two Core writers to it.
6. Supply Discord credentials and allowlisted owner/guild/channel settings privately on the hosts. Do not commit tokens, RPC capability receipts, live configurations, player memories or transcripts. The voice reference uses `GREGORY_DISCORD_TOKEN` and `GREGORY_LM_TOKEN`; the older `config.example/README.md` describes legacy token-file conventions, not the current reference's environment handling.

## Verify before launching

From the repository root, with dependencies installed:

```sh
python recovery/verify_snapshot.py
python -m unittest discover -s tests
python deployments/oldpc/gmod_bridge.py --help
```

Run tests in a disposable directory/environment; no live game/model/voice activity is needed for the regression suite. Original qualification: Linux 740/740 and isolated Windows 213/213. Those historical results do not establish a clean-machine restore; the packaging run's result is recorded separately.

## Launch contract — not an automatic startup script

Choose new run-local receipt/stop/transcript paths. Use the bridge's `--help` and the Core/voice docs in `docs/` to construct the supervised launch for the restored installation. The tested combination used `--playercore`, `--no-social`, Recorder options, `--supervised-session`, `--core-root`, `--memory-dir`, `--core-game-tasks`, `--voice-turn-taking`, `--core-harness`, `--quiet-test-profile` and optionally `--core-screen`. Supply the actual GMod data path, model endpoint, actor SteamID and owner identity explicitly. Do not invent defaults for private actor/owner/config fields.

Start one bridge/Core writer, verify its fresh private loopback receipt, then establish the approved voice connection/tunnel and start one voice client. Keep RPC services loopback-scoped; do not open firewall rules as a restore shortcut. Start with a bounded supervised session and drain/stop it afterwards. Confirm actual game-side input release, not merely transport ACK.

## Remaining recovery gaps — do not call this a full backup

- `recovery/2026-11-12/voice-reference/gdiscord.py` is the frozen review/fixture sibling, **not an independently qualified full voice-host installation**. Windows launch/tunnel/bootstrap details and exact installed dependency versions are not fully captured here. It needs the current `greg_voice_*` and `greg_sapi4` modules on its import path.
- Bonzi/SAPI4 requires separately installed compatible Windows components and the local engine setup. Alternative Piper assets and Whisper/STT weights are also external. No complete voice dependency lock or installer is included.
- Private state/backups and map/nav/landmark data are intentionally absent. Without them code can be recovered, but Gregory's current memories cannot.
- Known open issues include provider validation silence, failed relay/shutdown recovery, navigation/release acceptance and the advanced direct controller. Do not launch the failed relay experiment as the normal configuration.
- A fresh-machine, end-to-end restore has **not** been performed. Close the above gaps and pass owner-supervised speech, movement and stop checks before claiming one.

## Packaging-only differences from frozen qualification

Production Core/bridge/voice-client/Lua bytes are preserved. The historical inbox live-test tool is omitted because it embeds a machine address, account/channel IDs and an old message cursor; it is not a runtime dependency. The voice-host reference's old machine-specific Minecraft file-server URLs now point to loopback placeholders. Three test files now resolve their voice/bridge historical fixtures inside this repository instead of external stage/sibling directories; original baseline bytes and assertions are retained. The README gains a recovery notice, and the model-load example uses loopback. These are not new gameplay fixes. `QUALIFIED_SOURCE_MANIFEST.json` remains historical provenance; `SNAPSHOT_MANIFEST.json` describes the actual published recovery files.

Friend downloads belong in the separate Gregory-addons repo, GMod first; this recovery branch does not publish a client addon or change repository visibility.
