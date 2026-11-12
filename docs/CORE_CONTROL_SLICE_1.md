# Gregory Core / Control Center — first isolated vertical slice

**One Gregory. Multiple worlds.** This is an isolated development prototype, not a live migration.
The Core owns persistent character identity, goals and evidence-linked memory. Adapters and the
dashboard may disconnect or restart without replacing the character. The UI is not an identity store.

## Reuse, not a rewrite

| Component | Reuse / seam | Evidence and limit |
| --- | --- | --- |
| Recorder | Existing `Recorder`, export and admission/close contract; adapter produces canonical evidence | Existing `greg_recorder.py`, `ExperienceTracker`; prototype fixtures use the real path, not invented memory rows |
| Memory | Existing `gregory_core.memory.MemoryStore`, FTS-only ingest/consolidate/search | v0.1-based first-memory baseline; no embeddings or v0.2 promotion; all retrieval remains historical |
| Model | Existing `deployments/oldpc/greg_model.py` budgeted `post_chat` | LM Studio/Gemma request seam; no model service starts/loads. Offline tests fake the transport explicitly |
| GMod | Existing playercore goals + deterministic controller remain adapter-owned | No new movement controller; this slice does not alter the installed bridge or dispatch live actions |
| Voice | Supplied Greg Local `gdiscord.py`: Discord VC/DAVE, faster-whisper small/CUDA, Piper | Preserve audio pipeline; source verified, live runtime not requalified. Context fix is staged separately, not deployed |
| Manager | Archived `legacy/rig-2026-10-15/playercore/gregman.py`/`gregctl.py` show status/lifecycle patterns | Not current installed Manager. Do not reuse historical service/model start/kill commands or assume decoder fixed |
| Historical voice | SAPI4 Bonzi/TruVoice, ElevenLabs references retained in project checkpoints | No claim current supplied Piper bot implements those selectors |

The voice attachment contains unconditional game context and identity tied to its old bot; the staged
mitigation has 29 offline tests but is not a full game adapter. Do not import/start it to inspect source,
read Discord tokens, join VC, load STT/TTS/GPU models, or restore an old version over the working bot.

## Small first slice

- One standalone Python Core process, a serialized command queue and durable operational journal.
- Core-owned profile/character UUID/goals persist independently of adapter sessions and the UI.
- Real Recorder exports import into the existing external MemoryStore. Search is FTS-only and returns
  source IDs/hashes, historical flags, and `current_world_state=unknown`; no answer is hardcoded.
- Adapter session connect/heartbeat/disconnect is independent. Old-session packets reject, process
  restart requires a new session, stale heartbeat is shown as stale, and Core restart does not restore
  old observations as current state. Fixture adapters are visibly labelled fixtures, not live wiring.
- Loopback-only, read-only dashboard: Core/adapter health, typed recent events, memory lookups,
  model-call metadata, decisions, outcomes and errors. Closing it has no process-lifecycle side effect.
- Owner CLI can request graceful Core stop. Stop closes admission, drains already accepted commands,
  commits the stop receipt, closes databases and releases the writer lock. No kill/restart loop.
- Separate owner/adapter capabilities; an adapter cannot stop Core, change goals or import arbitrary
  experience as the owner. No API to replace identity/personality from the dashboard or adapter.

Operational journal categories are **observation, memory, inference, decision, outcome, error,
lifecycle, model**. A journal event is not itself qualified Recorder evidence. Model output is not an
observation, a decision is not dispatch, and an adapter report is not proof of action success. Raw
private reasoning and credentials are not operational log fields. Fixture inputs remain labelled.

## Frozen acceptance and present status

Binding: Greg's `GREGORY_CORE_SLICE1_ACCEPTANCE_RATIFIED.md`, SHA-256
`2f5a2b89f5ee76806a20d9b2974e6fba4f1a1bdfe574e297cfc89ce9c9a53048`, 6430 bytes,
A1–A8 plus A7b. The standalone six are supporting history, not a replacement contract.

- A1: independent fixture game/voice process restarts; same Core instance, increasing uptime,
  no intervening boot, sub-2s health. Forced exit affects a test-owned fixture child only.
- A2: real Recorder fixture export → original MemoryStore → same memory ID, claims and evidence
  hashes after Core restart. No generation is involved in recall; no canned character sentence.
- A3: adapter attempts stop/goals/import/profile; four typed refusals and four journal errors
  with actor/scope, unchanged profile; owner control still works.
- A4: before observation, after change, after removal; both exact-ID and FTS lookup preserve
  MemoryStore's historical/state contract verbatim, with identical evidence and claims. A negative
  search/inspect fault probe proves Core does not hide a bad backend flag or current-state claim.
  No live-state adapter exists here; non-implementation is not evidence of restraint. The original
  `0971973` review accepted A4 only as "no promotion observed"; the R1 correction supplies this
  missing falsifiability. No MemoryStore baseline or live observation subsystem is changed.
- A5: one fixture workflow correlation joins historical observation import, consolidation,
  inference, decision and executor-reported outcome in order. The separate explicitly invoked
  fixture executor writes/reads back a marker in a fresh private directory. It is not a game
  action dispatcher; an intent alone never creates an outcome.
- A6: positive memory ID is queried unchanged against empty and different-episode control stores;
  both return zero matching episodes and no substitute prose.
- A7: 40 accepted writes, contiguous durable command-result sequences, bounded drain, journaled
  post-stop refusal, integrity OK, writer reacquisition. Post-close refusals use a separate fsynced
  control journal so SQLite need not reopen or take over a new writer.
- A7b: forced SQLite busy at stop produces a typed `core_degraded` receipt naming commands with
  no durable result; failure file, actual process exit 1, a replacement process acquires the
  writer and answers health. No claim that partial cross-database effects were rolled back.
- A8: actual private Chromium/Playwright fixture proof compares rendered memory ID, historical flag,
  fixture origin and citation hashes against SQLite rows. Simulated polling failure recovers; page
  close and three reconnects leave instance/uptime/boot count intact. No page POST requests.
  Managed-browser discovery failed; private Chromium libraries/fonts were staged without a system
  install. The first fontless browser timeout is preserved separately, not a passing check.

Model rows use explicit `type=model.request` / `model.response`; counting uses JSON field equality,
not substring matching. Legacy prototype rows without `type` use the exact `phase=requested` field
without rewriting history. Arbitrary provider text cannot increment counters. SQLite JSON functions
are used in this isolated prototype; Core on the Windows target remains unqualified.

Every journal row has an explicit origin; memory lookup rows derive fixture origin from cited source
labels. Fixture model requests have a separate counter and do not increment live-model counters.
The dashboard never receives control tokens. Lookup requests can add operational audit rows, but
cannot mutate the character profile, evidence, episodes or adapter lifecycle. Loopback access is
not isolation from other software running as the same OS account.

The LM Studio seam reuses `greg_model.post_chat` with explicit per-request settings and no process-wide
`configure()` mutation. Its transport is unit-mocked only; CLI selects no model or the clearly labelled
fixture provider. No live model route is enabled in this slice. Owner-stop timing is qualified only for
these bounded fixture workloads, not an uncooperative future model/plugin.

## Run locally (isolated fixture only)

Use Python 3.11+ from the repository root. No package installation is needed for the Core/HTTP fixture.
Choose a new real directory outside active game/voice installations; do not reuse any existing DB root.

```sh
python3 -B tools/gregory_control.py serve --root /absolute/private/core-demo --fixture-provider
```

Open the loopback URL printed by that process in a browser on the same machine. Do not expose the
listener or publish `control.json`; it contains private local control capabilities. In another terminal:

```sh
python3 -B tools/core_fixture_experience.py --root /absolute/private/recorder-fixture
python3 -B tools/gregory_control.py import --control /absolute/private/core-demo/control.json --file /absolute/private/recorder-fixture/fixture-import.json
python3 -B tools/gregory_control.py lookup --control /absolute/private/core-demo/control.json wood_crate001a
python3 -B tools/gregory_control.py fixture-adapter --control /absolute/private/core-demo/control.json --kind game --seconds 3
python3 -B tools/gregory_control.py fixture-adapter --control /absolute/private/core-demo/control.json --kind voice --seconds 3
python3 -B tools/gregory_control.py stop --control /absolute/private/core-demo/control.json
```

Restart only this test Core with the same private root to inspect persistent identity/memory. Profile
and episode stores survive; adapter sessions do not. Existing GMod, Discord voice, model services and
Manager are never launched, stopped or restarted by these commands. The fixture speaks to no game.

## Explicit remaining gates

Old-PC SQLite 3.49.1 does not satisfy the existing fixed-WAL-version gate merely because scratch tests
pass. No shared DLL/PATH/runtime change is authorized by this prototype. Live integration still needs
reviewed source/identity mapping, one game command writer, exact stop/rollback paths, privacy/retention,
current model configuration, sampler CSV and active owner supervision. Ask before any active-install,
service/game restart, network/security change or live trial. No Jeep dependency or production promotion.
