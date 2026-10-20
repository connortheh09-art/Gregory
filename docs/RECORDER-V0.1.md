# Experience Recorder v0.1 — review and operation reference

**Development/offline only. Not deployed or enabled in production.** Baseline
`194ed3d`; branch `gordon/experience-recorder-v0.1`. No Lua, navigation algorithm,
Jeep, model assignment/configuration, network or service changes.

## Enablement boundary

Without `--recorder`, no recorder DB/directory/thread/health file is created.
`--recorder-db` alone does not enable it. Existing legacy logs are unaffected.
Example options for an **approved future** test command, not deployment approval:

```text
--recorder
--recorder-db <absolute-local-path>/experience.sqlite3
--recorder-text metadata
--recorder-retention-days 7
--recorder-max-mib 1024
```

Default DB path is `greg_recorder/experience.sqlite3` beside the collector.
Use local disk, not UNC, SMB, OneDrive or another synced directory. The code
rejects UNC syntax; it cannot reliably discover every sync/remote-volume setup.
Do not edit current launchers or start a second collector to test this feature.

## Contracts and storage

- `greg_events.py`: frozen serialized v1 envelopes, UUID4 IDs, source instance/
  sequence, UTC + per-process monotonic clock, control/correlation/decision/
  goal/action/observation/causation references; bounded allow-list sanitation.
- `greg_recorder.py`: queues, writer-owned SQLite connection, local lifetime
  lock, schema marker + `user_version=1`, `runs/events/links/experiences/meta`.
  Canonical envelope JSON is stored once alongside query indexes. Projections
  update atomically with events. Unknown/foreign schemas are not reconfigured.
- `greg_experience.py`: collector-thread-only episode/correlation registry,
  bounded sample pinning, native goal/route aliases, passive evaluator/deadlines.
- `tools/greg_experience.py`: read-only inspection, bounded sanitized JSONL
  export, consistent SQLite online backup. No OpenClaw/Companion dependency.

Native telemetry `seq` is **not** a command acknowledgement. A route renewal
has the same logical action ID with a distinct dispatch attempt ID. Replans get
new action IDs under the episode. Social compound speech is linked separately;
literal speech does not steal locomotion's active trace. Idle wait ticks do not
manufacture new goals. Source clocks are never subtracted across processes.

Events admitted to queues are **not durable** until COMMIT. Queues reserve 1024
normal / 256 critical slots, with a bounded 64-event inflight batch. Envelopes
are capped at 16 KiB normal / 64 KiB critical; route points retain the existing
256-point limit. Periodic observation baseline is <=1 Hz; pre/post/transition/
arrival evidence is additionally pinned. Re-admitting the same pinned event is
idempotent. Drops count rejected admissions, not necessarily permanently missing
unique events (a later pin can restore an earlier dropped observation).

Critical preference cannot guarantee zero loss. Health exposes queue/inflight,
admission/commit/drop/error counts, last durable ingest cursor/time, and storage
size and quarantined identity conflicts. A health file is refreshed at most once per two seconds; its timestamp
must be checked. SQLite/file errors degrade the recorder and emit fixed error
categories, not payloads. Writer retries are bounded-memory, fixed 500 ms
backoff; control producers never wait for DB I/O.

Identity conflicts are **not** storage faults: the original committed event is
never overwritten. A different envelope with the same event ID, or a different
ID reusing a source sequence, is rejected in the writer transaction. A
`recorder.loss` event with `mode=quarantine` retains only IDs, sequence, reason
and the rejected sanitized envelope's SHA-256, not its payload. Healthy peers
commit in the same transaction. `quarantined`, `dropped` and categorized losses
advance only after COMMIT; failed transactions retry without double-counting.
`mode=cumulative` loss events are counter snapshots, not additional loss deltas.
Exact byte-identical replay remains idempotent. Transient storage faults still
retry; deterministic identity violations cannot poison that retry batch.

The writer alone uses WAL + FULL synchronous mode and performs retention/
checkpointing. Read-only connections use short snapshot transactions and close
after context exit; they cannot write/checkpoint/migrate. Lifetime lock is per
recorder directory. A second recorder is refused; this is not a new general
game-process singleton.

## Outcomes and recovery

Dispatch success means file written, not gameplay succeeded. The navigation
evaluator requires matching route/control context, fresh accepted samples,
<=100 planar units, <48 vertical units, <=10 units/s, >=0.5-second dwell, no
sample gap >1.5 seconds and no observed rescue ownership. Evidence includes the
pre-action sample and samples needed to reconstruct speed/dwell. Controller
failure reports remain distinct from overall goal failure/replanning.

At >3 seconds without accepted telemetry, emit a gap; >30 seconds closes a
recording attempt unknown. A 600-second observation window also closes unknown.
Neither changes live goals, leases or movements. Late continuing activity opens
an explicitly linked new recording segment. Unsupported primitive outcomes stay
unknown; game chat submission is not confirmed audible Discord playback.

On restart, committed open prior runs/experiences become unknown/unclean_restart;
previous terminal records remain unchanged. Each affected correlation receives
`outcome.evaluated` + `experience.closed`, linked to its last recorded event.
Those events belong to the **original logical run/session** for export/retention,
with the recovering process's source-instance ID, UTC/monotonic clock and source
sequence. Never compare monotonic clocks across source instances. An orderly
writer shutdown also closes residual correlations this way. Startup recovery,
projections and run closure are one transaction; a failed recovery commit leaves
the old run open for the next attempt. No old command or task is resumed.

Legacy goal selection is a decision-only experience: accepted/rejected/empty
choices finalize immediately, with accepted choices linked to a native goal alias
and `world_outcome=not_applicable`, **not** a successful executed goal. Primitive
legacy gameplay still has dispatch-only outcome coverage. Vision acquisition is
a sensor child under the parent inspect correlation; its result/error closes that
inspection without changing the active navigation/action trace. No new independent
sensor gameplay decision is fabricated. `model.request` carries model/settings;
`decision.requested` is emitted once per policy decision.
Graceful recorder shutdown drains for up to two seconds; pending loss on an
abrupt crash may be unknowable. Do not present queued events as committed.

Seven-day retention deletes closed runs' whole graphs in bounded chunks, hiding
an expiring run from readers until deletion completes. Active runs are not
partially pruned; reaching 95% of the 1024-MiB DB/WAL budget or low disk halts
new admissions, not gameplay. No live VACUUM. Exports/backups outside that
directory require their own deletion/storage policy; the cap is not an OS quota.

## Privacy

Metadata-first default omits raw conversations, prompts, speech text and model
prose; parsed action/goal choices, geometry/settings/usage/status stay available.
Per-run actor aliases replace native identity in new recorder records.
`--recorder-text visible` explicitly permits bounded sanitized generated visible
output, never hidden reasoning fields or raw prompts. Inline reasoning/credential
markers cause unsafe text omission. Redaction is not a universal secret detector:
typed allow-lists and avoiding raw inputs are the primary protection.

No raw audio/screenshots/media are recorded. Missing/redacted parameters and
unresolved evidence are labeled; `trace_complete` is independent of world
success. Existing `greg_model_audit.jsonl`, chat/P0/world memory files are not
imported, deleted, or made public by this feature.

**Canary privacy prerequisite:** the pre-existing `greg_model_audit.jsonl` writes
raw model-visible content independently of `--recorder-text`. Metadata mode only
covers the new recorder; it does **not** make all existing logs metadata-only.
Its disablement/retention/access policy must be agreed before a live canary.
Exclude legacy audit/chat/memory files from shared bundles. This patch changes
neither that sink nor its production configuration.

## Read-only review commands

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 tools/greg_experience.py --db /path/history.sqlite3 status
python3 tools/greg_experience.py --db /path/history.sqlite3 sessions --limit 20
python3 tools/greg_experience.py --db /path/history.sqlite3 experiences --last 10m
python3 tools/greg_experience.py --db /path/history.sqlite3 show --correlation <uuid>
python3 tools/greg_experience.py --db /path/history.sqlite3 events --after 0 --limit 100
python3 tools/greg_experience.py --db /path/history.sqlite3 export --run <uuid> --output session.jsonl
python3 tools/greg_experience.py --db /path/history.sqlite3 backup --output snapshot.sqlite3
```

Output destinations must not exist. Cursor is local ingest order, not source
sequence or a globally comparable clock. Export preserves globally unique IDs;
its extra `ingest_sequence` is transport metadata, not part of the canonical
envelope's identity. Future mirror ingestion must strip/retain that separately
and reject conflicting IDs; no mirror/import server is included. `show` reports
missing parent/evidence refs and coverage, including incomplete recorded success.
`terminal_resolved` reports whether the terminal ID exists in the returned trace;
`missing_stages` and `exact_dispatch_recorded` explain why the **observed game
action chain** is incomplete. Speech, status, goal-selection and sensor-only
experiences need not contain controller feedback; a closed record is not thereby
a complete game-action chain. A crash before dispatch remains incomplete, even
with a correctly linked terminal event. Legacy v1 run-level terminal IDs are
resolved read-only without rewriting old events or inventing missing closures.
Readers hide a run marked `retention_expiring` for the whole deletion interval.
Failed export/backup removes its newly reserved partial output; existing files
are never overwritten or removed.
CLI exit codes: 0 query success, 2 usage, 3 unavailable/busy/output failure,
4 unsupported/corrupt data, 5 not found/expired. Unknown outcome is valid data.

## Spec deviations / limitations for review

1. Canonical envelope JSON plus indexed keys replaces duplicated DDL payload/
   control columns; a schema marker adds protection against unrelated SQLite DBs.
2. Startup records a **review baseline reference**, Python source hashes and
   locally accessible Lua-tree hashes (bounded at 32, with truncation flagged).
   The resolved model ID, Python/SQLite versions are already recorded. Actual
   build commit is **unknown**, not inferred from the branch/baseline. A tree
   snapshot does not attest to installed addon copies, launchers or bundle hash.
   Before an authorized Windows canary, stage a separately hashed deployment
   manifest against those actual files/commit. Do not capture raw launcher args
   or full paths indiscriminately: they can contain credentials/private identity.
3. Queue commits wake promptly rather than a strict timed batch scheduler;
   writer retry uses a simple 500 ms backoff, not escalating intervals.
4. Optional CPU/GPU/process/RTT monitoring, full prompt reconstruction, media,
   external event ingestion, admin API and durable remote replica are deferred.
5. Non-playercore outcome guarantees are limited; human/primitive/voice coverage
   is partial and unsupported completions stay unknown. Privacy-omitted command
   fields prevent an exact-parameter claim for that dispatch.
6. Target Windows filesystem/locking and actual SQLite version, live cadence,
   curb/gameplay and real enabled-recorder acceptance are **not tested** here.
   Linux test runtime uses SQLite 3.40.1; before enablement review the documented
   WAL-reset fix (3.51.3 / supported backports) and target runtime. Only this
   writer checkpoints/writes; no environment upgrade is automatic.
7. An off-host reader cannot query a powered-off game PC without a future
   replica or previously exported snapshot. Local durability is not availability.

## Rollback and pending security

No production rollback is needed: nothing was deployed. Future approved canary
rollback removes `--recorder` under the existing single-writer handoff; if code
reversion is necessary, restore the coherent prior Python bundle and leave Lua,
nav/chat/world memory, Jeep and model settings alone. Preserve DB+WAL safely;
never copy only the active DB or auto-downgrade a newer schema. No gateway/game
restart, ACL change or network remediation is implied.

SEC-PENDING-01: prior unauthenticated LM Studio model-list exposure remains an
owner task. No ports/authentication/firewalls/tunnels/services were changed.
Deployment, recorder enablement and any target runtime upgrade require separate
Connor approval. Windows prerequisites remain unverified: local unsynced volume,
real `msvcrt` locking/reader URI behavior, supported SQLite WAL fix/backport,
WAL/FULL settings, supervised kill/restart and measured gameplay cadence. Do not
upgrade Python, touch logs/services, or start that canary under this patch's
coding-only authorization.
