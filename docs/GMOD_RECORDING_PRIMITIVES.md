# Gregory — Recorder/Core primitives candidate

Repository: https://github.com/connortheh09-art/Gregory . Base: accepted `161c738`.
Implements the amended boundary `ca2cb0c681e73958b6a1db78bdb5122b8ed21a5d63c8346aada34f9b404bef02`,
accepted in Greg's corrected disposition `2f592aafe2dbe72bee2218640edef9001e1f1726e56c116ec73d106407016cf6`.

## What is implemented

- `gregory_core/gmod_recording.py`: one read-only bounded Recorder snapshot, database/first/tail cursor
  checks, canonical identity/digest validation, atomic journal/idempotency-key insertion and durable cursor
  update after a matching committed Core receipt. The accepted Recorder implementation is unchanged.
- `runtime.py`: separate observation freshness and adapter heartbeat clocks; session-bound
  `recorded_batch` adapter operation. No owner endpoint or new dispatch authority. Owner imports now record
  actor, source label and correlation in the observation audit row.
- `tools/gregory_gmod_adapter.py`: **one-page CLI**, not a daemon or supervised trial launcher. Connect,
  one bounded page, committed receipt/cursor, disconnect. A cursor-only writer lock prevents competing
  cursor updates; it has no Recorder-writer or game-command ownership. Cursor metadata must have a real,
  separate directory outside the entire Recorder directory subtree. No automatic retry/rebind.
- Control Center uses its existing event view, with recorded origin/source age, explicit adapter-heartbeat
  meaning and Core-provider counter scope. No UI control, new endpoint or model routing.

Core journal and MemoryStore remain separate: this seam writes operational reports only. Recorder
`model.*` events are observation subtypes, not Core-provider calls. Dispatch, controller feedback and
`outcome.evaluated` retain original event types/qualifications, including inconclusive results. It never
creates an executed outcome from a proposal. `live_state_available` remains false and memory count is
unchanged by ingestion. Importing closed evidence remains a separate explicit owner operation.

## Identity, clocks and failure behavior

Recorder namespace is `recorder:<database_id>`. The unique source key is the canonical JSON tuple
`[source_instance_id, source, source_sequence]`; event_id is independently unique within that namespace.
An identical canonical envelope digest is a counted duplicate; a reused source identity or event_id with
different identity/content refuses the batch. SHA-256 is over sorted canonical JSON, not raw JSON byte
formatting. The journal UUID is not the idempotency key.
Receipts name `source_namespace` and whether it already had ingestion rows (`namespace_preexisting`).
An explicitly rebound new database_id is a new namespace, even with overlapping envelopes; its receipt
says it is not proof of continuity with another database_id. Deduplication is namespace-local.

`recorded_at` is the original envelope source timestamp; `seen_at` is adapter receipt; `occurred` is Core
acceptance. Replay may have old source/receipt times and is never current. A live label requires a fresh
delivery, fresh original source time, the bound Recorder run/session, and matching supplied game control
context; an observation must carry the matching bridge session/control epoch. Fixture rows always retain
`fixture=true`/`origin=fixture`; their emulated stream origin is explicitly in the payload. No fixture
is claimed as live GMod evidence.

`with open_reader(...)` uses the existing ReadConnection BEGIN/finally-close primitive. Database identity,
available tail, first cursor and bounded rows are from that snapshot; the handle is closed before HTTP or
sleep. A missing DB is not created. Changed database, older same-ID restore beyond cursor, retention gap,
oversize event/batch or identity conflict refuses instead of resetting/rebinding. An empty page exactly at
the tail is healthy; it is not proof the game is alive. Reported source age is diagnostic, not world state.

The default page budget is 64 events / 256 KiB; per-journal report is capped at 16 KiB, with a typed refusal
rather than silent truncation of a larger source envelope. Latest-100 journal status remains bounded.
Per-batch journal/key inserts are atomic; command-result persistence is still a later transaction. As in
Slice1, a crash can leave partial cross-database/command effects. A lost acknowledgement is retried by
source identity, not declared rolled back. No cross-database atomicity claim.

## Owner-prepared connection, not an OS security boundary

The one-page CLI requires an adapter-only JSON receipt with exactly:
`url`, `adapter_token`, `recording`, `fixture`. `recording` contains `database_id`, `run_id`, `session_id`,
`bridge_session`, `control_epoch`. It deliberately rejects the combined owner `control.json`.
Use a separate adapter root and explicit fresh trial Recorder identity. Same-account processes can still
read each other's files: this is accidental-use containment and endpoint capability enforcement, **not OS
isolation**. No user, ACL, AV or network changes are implied.

Future authorized execution shape, **not executed against a live installation**:

```text
python tools/gregory_gmod_adapter.py --connection <adapter-only.json> --recorder-db <explicit.db> --cursor <cursor.json>
```

Replay is the default. This tool has no game command path, model loop, MemoryStore import, kill, restart,
Lua edit or installed-service management. Reserved cursor `.tmp` files left by interruption are discarded
under the cursor lock after validating a durable receipt, then recomputed; aliases/nonregular files are
refused, never followed or recursively deleted. Source binding covers one run/session. It fails closed on a
different run rather than skipping it; rebind is explicit. In a multi-run DB, the starting cursor must be
chosen explicitly or the trial must use a fresh DB. Do not treat a sidecar heartbeat as game liveness.

## Verification and remaining work

New tests use real temporary Recorder/Core databases and synthetic fixture gameplay. Cases include
lost-ack retry across Core restart, conflicting duplicate with batch rollback, older same-ID backup,
empty restore, changed DB, retention gap, stale replay over the HTTP surface, fresh-source positive control,
source/session/delivery rejection, separate clocks, snapshot closure before delivery and on error, wrong
receipts, bounded empty polls and the one-page subprocess with adapter-token owner-import refusal.
Accepted parent51c356e: author204/2040skips28.414s; Greg independently204/2040skips32.176s.
Correction candidate: **206/206, 0 skips, 30.996s** (prior188 unchanged;16 primitive cases retained,
one footprint case strengthened;2 new cases for stale-temp recovery and explicit namespace rebind).
Two guard-removal mutations against51c356e each failed the requested named assertion; M1/N1 regression
probes also failed before the correction. Focused18/18 passes afterward; all red/green logs are labelled.
Earlier focused runs were 13/13, then15/15 before the cursor-footprint guard, not extra full-suite runs.
Logs and exact source commit are supplied in the review bundle; no live/browser/Windows acceptance is claimed.

The continuous observer/supervised runner is **not implemented** in this primitives candidate. Windows Core
and adapter remain unqualified. SQLite3.49.1 still fails the approved fixed-WAL runtime gate; loaded SQLite,
JSON1/FTS5 must be checked in a reviewed side-by-side runtime. Live collector single-writer handoff, graceful
game stop and rollback, full 120-second sampler baseline and an explicit owner-supervised window remain.
No deployment, target command, live memory import, production promotion or Jeep change follows from tests.
