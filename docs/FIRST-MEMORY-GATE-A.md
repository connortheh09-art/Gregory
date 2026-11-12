# First memory canary — Gate A offline candidate

Owner authorization: Connor message `1562957287822196827`, 2026-10-22 22:34 UTC.
Based on reviewed v1.1 + Greg R2/R2A + supplement v1.1A. Isolated branch
`gordon/first-memory-milestone-1`, based on memory v0.1 `c5e08e5` (includes PR1 `3add789c`).
No baseline overwrite, v0.2 promotion, Jeep changes, node access, model calls or gameplay.

## Result and limits

Revised candidate: **168/168 Python tests pass**, including **44 canary/control tests**. Greg
independently reproduced the initial162/162 at cd7dea0; G1–G3 fixes add6 regressions. Revised
results have not yet been independently ratified. Python compilation and
`git diff --check` pass. The test provider is fake; it checks transport/prompt binding, not model
truthfulness. No Lua interpreter exists in this workspace: the additive Lua eye descriptor is
source-reviewed only, not executed. Windows ctypes sampling is source-only, not target-qualified.

This is an engine-observation persistence/provenance prototype, NOT independent visual recognition,
a completed cross-session game trial, retrieval-quality improvement or production promotion.
Correct dialogue is still an independently scored live acceptance condition. Submission receipts
deliberately say `delivered: false`; only supervisor corroboration can establish in-game delivery.

## Implemented chain

1. **Explicit eye descriptor.** Additive Lua fields distinguish hit/miss/world/entity, include model,
   source-scoped index and hit-entity position separately from the ray impact. The recorder accepts
   two physics-prop classes only. A bounded v1 descriptor excludes names/captions/arbitrary fields.
   Its keys are accepted **inside `landmark_observation` only**. Bare class/hit/index keys retain
   legacy drop semantics, including malformed values; no global whitelist widening.
2. **Opt-in capture.** `--first-memory-capture` requires playercore, recording, metadata mode, an
   explicit recorder path/budget <=64MiB, social disabled and an external monitor status. It reuses
   the existing controller/action path. One annotation cites an already-pinned accepted observation;
   annotation contains no duplicated object fact. A negative hit is recorded, never promoted.
   Five-minute cap; errors fail closed. Stop is submitted once, fresh same-context acknowledgement
   plus two still positions are required. Failure is inconclusive; no kill/reconnect/relaunch loop.
3. **Supervised export/promotion.** `tools/greg_first_memory.py promote` reads a real committed
   recorder export, requires a fresh empty canary store and exactly one positive annotation, ingests
   and consolidates one episode. Observation carries an instant claim, map/class/model/position,
   source ID/hash. Unknown navigation outcome stays unknown. Envelope/SQLite schema remains v1.
4. **Seal and recall.** Count 0 before A, exactly 1 before positive B. Fixed retention 604800s;
   actual stored expiry exceeds window end +3600s. Compare logical rows (including citations,
   revisions, tombstones, vectors and FTS contents), never SQLite/WAL bytes. B sets query-only
   after normal MemoryStore open. Calls real `last_session(domain='gmod')`, then compares returned
   identity with the runtime seal. No expected-ID lookup. Source validator reads only retrieved
   citation IDs; it does not search the source DB or feed alternative facts.
5. **Bound model input.** Before generation, source/projection/seal/fact/block digests must match.
   Exact model-visible JSON and generation budget are receipted. Neutral question + static persona
   + retrieved history only; no live-eye, catalog, chat, lessons or world-memory input. Revalidate
   before publication. A case-insensitive, word-bounded question check rejects the retrieved class,
   model basename and absolute coordinates (including signed/decimal/exponent equivalents).
   Passed checks are in request receipts; rejected questions produce a rejection receipt before any
   model call. Empty control does not load A facts for this check. This is bounded token checking,
   NOT proof against semantic paraphrase leakage or facts already known by the model.
   Only exact `{say: string}` is accepted; any action key rejects the whole
   response. Existing dialogue filter and mailbox submit the newly constructed say action.
   A pre-submission English phrase scan records `current_state_claim` in the speech-assessment and
   submission receipts. It flags direct presence/absence statements, but remains a non-blocking
   scoring aid: false positives/negatives are possible. False current-state prose fails the trial
   even when the scanner misses it; a false flag never proves a safe answer. Supervisor transcript
   review remains mandatory and `delivered:false` is unchanged.

## Explicit arming and eligible prop — G4/G5

Capture has **no delayed manual-arm switch**: it fires once on the first open active trace after
baseline. Before releasing the first supervised controller directive, the supervisor must confirm
the camera already eye-traces the intended harmless prop. Do not let a generic policy start first
and assume capture waits for arrival. Stage any approach/aim setup separately under the approved
live procedure, then explicitly release the capture-producing directive after aim and CSV are ready.

Referee must use **`prop_physics` or `prop_physics_multiplayer`**; no other entity class qualifies.
Check class from engine telemetry, not entity name. Miss/world/non-prop/invalid first hit ends the
attempt as `no_valid_prop`; it is not retried. Preserve the failed recorder/export/receipts. A new
attempt needs a fresh canary DB/run and the approved trial procedure, not silent reuse or promotion.

## Clean B boundary

No automated archival or live cleanup is included. Supervisor archives canonical `data/greg`
while both processes are down, preserves original hashes/sizes/mtimes, and writes only the approved
marker and map-matched static navdump. No `--data` redirection shortcut; Lua paths remain fixed.

`tools/greg_first_memory.py preflight-b` empirically inventories fresh bridge/core source, bootstrap
and absent source-relative context paths. A separate **after-start** inventory permits only explicitly
reviewed new B files. This avoids requiring an empty transport after GMod has already started writing.
It validates loaded module paths, rejects symlinks/legacy survivors/environment path overrides, and
requires a different adapter session from A. Source/core and bootstrap content stay pinned.
Timestamp check declares **one-second filesystem precision slack**; the absence manifest and fresh
adapter identity are primary, mtime alone never proves isolation. This is not an OS sandbox or an
authentication boundary: trusted supervisor manifests and actual process-exit verification remain
load-bearing. Seals/receipts/oracle/archives must be isolated by the reviewed live procedure.

B uses a fresh source tree. The episodic DB is its only allowed historical answer input, with
citation-only access to sealed source rows. Legacy DBs/audits/archives/oracle are excluded. Output
receipts and trace go outside B input roots. Blind B consolidation stays disabled.

## Monitoring source (not run on Windows)

`tools/greg_canary_monitor.py` is a stdlib Windows read-only sampler: explicit discovered game/bridge
PIDs + creation time, separate working set/private bytes, host available RAM, UTC/monotonic elapsed,
state age/death, map/gamemode, recorder DB/WAL size and event count, CSV every5s outside game data.
It does not add overlapping metrics or assign a cause to the reported ~17GB incident.

Pure limit rules are tested:120s warm baseline; +1GiB per process metric; +500MiB/60s; available<2GiB;
5min active/30min total; stale heartbeat>15s; death, changed PID identity, stale state or recorder health
loss abort. Operator-owned active/supervision markers and actual line-of-sight supervision are required.
Sampler emits failure status, not kill commands. Both collector modes require a fresh PID-bound
heartbeat and warmed baseline. A missing/failed/stale sampler blocks the lane. Human normal game
closure, actual process exit, rollback and restoration of temporary settings remain Gate C duties.

## Offline verification

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q gregory_core deployments/oldpc tools tests
git diff --check
```

New controls cover real Recorder sanitizer/admission/export/import; positive/negative descriptors;
pin/source order; missing/wrong-session/future/stale/context refs; queued-source refusal; instant
entity-position facts; owner/cardinality/expiry seals; deleted/altered/replaced source or memory;
post-retrieval block tamper; empty store first in a distinct reader; paraphrased neutral queries;
same-class/index-reused decoy excluded from prompt; action-bearing output rejection; changed actual
request rejection; clean-source/transport/bootstrap path checks; supervision/stop rules; separate-process
CLI reopen and the actual A/B collector branches with fake provider/no game.

Initial failed logs are retained. First broad run exposed an existing single-argument tracker spy
being passed a new keyword even in disabled mode; default construction is now exactly the old call.
An intermediate preflight fixture-placement error and sub-second filesystem mtime mismatch were fixed;
the precision slack is explicit above. No test assertion was weakened to bank a pass. Existing recorder
off/on command-cadence assertions and privacy/storage/lifecycle tests still pass.

## Remaining gates

- **Review:** Greg independently reviews this concrete diff, failure logs, source pins and receipts.
- **B unsigned:** Connor approves discovered target/account/private scratch/existing interpreter,
  exact staged manifest and bounded target checks. Windows sampler and Lua execution need target
  qualification; no installs or permission changes. Permission failures stop for Connor.
- **C unsigned:** separately approve one supervised live A/B window, map/route/prop, actual installed
  Lua/source hashes, single command writer, model/settings/privacy/7day evidence retention, baseline CSV,
  normal close/relaunch, archived transport/bootstrap, oracle isolation and verified rollback. Freeze
  referee object/answer hash before A. Empty/decoy/paraphrase controls plus actual speech/reinspection
  remain required. No unsupervised play, services restart, forced termination or production promotion.

The untested Jeep prototype and PR1/v0.1/v0.2 refs remain preserved. This document does not grant B/C.
