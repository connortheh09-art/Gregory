# Project Gregory — Memory Architecture v0.1

**Offline prototype, not deployed.** One Gregory, multiple worlds. Recorder evidence
is the input; memories are a separate, derived store. PR1, existing voice/game
implementations, model services and protected Jeep files are unchanged.

## Small architecture

```mermaid
flowchart LR
    R[Immutable recorder export] --> V[Identity/scope validation + metadata projection]
    V --> E[Evidence IDs + canonical envelope hashes]
    E --> C[Deterministic episode consolidation]
    C --> M[SQLite episodic memories + claim citations]
    M --> F[FTS5 keyword index]
    M --> N[Optional local Nomic callable]
    N --> X[Model/revision-specific vectors]
    F --> Q[Rank fusion + historical-only results]
    X --> Q
    L[Fresh live adapter state] -. separate authority .-> G[Future Gregory Core consumer]
    Q --> G
```

`gregory_core/memory.py` owns storage, consolidation, correction, retention,
inspection and forgetting. `embeddings.py` is a local inference boundary;
`evaluation.py` measures labelled retrieval. No model, game, voice or network
service starts on import. SQLite FTS5 and standard-library cosine scans keep the
first implementation dependency-free. The semantic scan is capped at 5,000
eligible vectors; this is a prototype, not a large-corpus ANN implementation.

Working context, owner-controlled core identity and semantic facts remain separate
future modules. This slice deliberately does not auto-promote one episode into an
enduring fact, relationship, preference or personality change. No fine-tuning.

## What is stored and what is claimed

- Import **snapshots**, not a live collector. Input uses complete PR1 envelope
  fields, UUID identities, source-instance sequences, UTC timestamps and bounded
  JSON. Structural validation is not proof that every recorded statement is true.
- Store metadata-only projections and SHA256 of canonical original envelopes
  (excluding export cursor), plus the caller's source label. Original full payloads
  remain in their source export. Raw dialogue, prompts, credentials and media are
  not copied by this importer. Do not put private text in source labels.
- One `(run_id, correlation_id)` becomes one episode. All source event IDs remain
  linked, even when 200 low-level feedback events collapse into a short summary.
  The current snapshot is immutable: repeat consolidation does not silently
  overwrite it or an owner correction. Late evidence needs explicit owner review
  and rebuilding, not an automatic reinterpretation of history.
- Every claim has `kind` and evidence IDs: **observed** recorder/action/controller
  facts, **reported** owner corrections, **inferred** evaluator conclusions, or
  **unknown** outcomes. Evaluator success is never relabelled direct observation.
- Missing terminals/stages, bad observation scope, stale observations, evidence
  gaps, conflicting terminals and mixed restart source instances block a success
  conclusion. Source sequence orders one process; wall-clock shifts do not reorder
  its causal chain. Mixed process clocks are conservatively uncertain.
- Action submission alone never proves arrival. Target identity is not invented:
  a metadata-only follow trace says "a target", not Connor unless an authorized,
  evidence-linked identity adapter establishes that later.
- Every result declares `historical_only=True` and current world state **unknown**.
  `last_session()` answers the latest retained episode session by recorded UTC time,
  not import order; cross-session clock accuracy still depends on source clocks.
  Yesterday's Minecraft memory is not evidence that Minecraft is running now.

## Retrieval and local Nomic contract

FTS treats input as literal tokens, not executable FTS operators. Session/domain
and expiry filters apply before both keyword and vector ranking. Reciprocal-rank
fusion exposes retrieval channels rather than equating BM25 and cosine scales.
Scores are retrieval relevance, **not truth confidence**. Cite source IDs and show
uncertainty when a future voice/model consumer uses a memory; stored text is data,
never an instruction that can override the Core or owner.

`LocalNomic(encode, revision=...)` wraps an **already-loaded local callable**.
It uses full 768-dimensional vectors and explicit `search_document:` / `search_query:`
prefixes for [v1.5](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5) and, later,
[v2 MoE](https://huggingface.co/nomic-ai/nomic-embed-text-v2-moe). No HTTP embedding
API, key, automatic download or model loading is implemented. Vector spaces include
model, revision, dimensions, prefixes and normalization; incompatible spaces cannot
mix. Invalid vectors are rejected. An unavailable model gives an explicit keyword
fallback. Corrections invalidate vectors; changes during encoding reject stale work.

The offline tests use **hand-labelled synthetic vectors, NOT Nomic embeddings**.
Actual v1.5 acceptance and v2 MoE comparison remain UNRUN. Next model gate: identify
the intended local artifacts and pin their file hashes/runtime, qualify prefix,
dimension and normalization behavior on held-out queries, then compare v1.5/v2 in
separate indexes using recall@k, MRR, latency, footprint and evidence correctness.
Do not load/unload LM Studio models or change its live services for this prototype.
See the [SQLite FTS5 reference](https://www.sqlite.org/fts5.html) for lexical indexing.

## Owner control and privacy

The trusted host must supply the authenticated actor ID; this Python library is
not an authentication service. All memory APIs require the configured owner.
There is no guest sharing or automatic private-memory injection into group chat.
New-store retention is explicitly supplied (`seconds`, or deliberately `None`);
expiry is based on event time, hidden from retrieval immediately and purged during
maintenance. Owners can inspect expired entries until maintenance removes them.

Corrections retain inspectable revisions but only the current text is searchable;
the correction stays labelled owner-reported. Forgetting removes the episode,
revision history, citation links, FTS rows, vectors and unshared projected evidence.
Deleting evidence invalidates every dependent episode. Content-free event-ID
fingerprints prevent the same forgotten export being accidentally re-imported.
Unconsolidated evidence also expires. Another episode's still-referenced evidence
is preserved when forgetting only one memory.

This is **logical deletion**, not certified physical SSD/WAL/backup erasure. Source
exports and backups have separate owners/retention; memory deletion does not rewrite
the recorder. SQLite `secure_delete` is best-effort defense, not an erasure claim.
No Control Center UI is built; inspect/correct/forget APIs are its future boundary.

## Run and review

```bash
python3 -B -m unittest discover -s tests -p 'test_core_*.py' -v
python3 -B tools/greg_memory_demo.py
```

The demo uses a disposable directory and synthetic PR1 events only. It answers
"What happened last time we played?" with one short cited episode, includes source
envelopes so citations/hashes can be independently checked, and compares keyword
retrieval with fixture-vector fusion. Its tiny labelled scores validate plumbing,
not real semantic accuracy. A test also exports a real, unchanged offline PR1
Recorder database and verifies importing it leaves the source database untouched.

Greg's independent review should challenge what is remembered/omitted, whether
unknown outcomes stay unknown, stale-world leakage, correction/deletion and
evidence support. Ask for adversarial synthetic cases, not another production run.
The separate Windows Lua harness remains pending its own owner-approved scope.
