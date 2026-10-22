# Memory v0.2 candidate — results and remaining failures

**Verdict: prototype only; do not promote.** The first complete replay passes 25/40 automated strict checks and fails 15. No relabeling, gate tuning or core/adapter revision followed these scores. Independent review is pending.

## Frozen source and evidence

- Core scored at `1a8d6e8320cf789b7e23079b80f4ce2567006ce7`; replay harness at `e447bdb`. Branch `gordon/memory-architecture-v0.2`. Baseline v0.1 `c5e08e5`, PR1 `3add789c` and main-checkout Jeep work preserved. Four original core files are byte-identical to v0.1; receipt included.
- 29/29 new unit tests passed before scoring, including source binding, overlapping intervals, source-time guards, complete dissent, typed-premise checks, source identity, correction/vector invalidation, shared-evidence deletion, tombstones, restart and expiry. Existing 37/87-test batches were not rerun.
- Fixture v1.5 SHA `83ec6a431f58108370b97e77803d426285714aab1722b6895c65e9eb19be8ea9`; contract v1.1 SHA `d7194ab0816788a515e238bf1dd5d47fba652065067647479effbfd296d102fc`. Original files and all pre-score revisions preserved.
- Map names v1.5 but still declares v1.4 SHA `a58a6d42...`; separate receipt verifies identical source corpora and query text, not byte equality. Author-declared freeze timestamps are later than observed UTC; provenance is attachment order plus hash receipts, not those timestamps.
- Real local Nomic v1.5 Q4_K_M, 768 dimensions, CPU ratio0/context512, literal single prefixes. 255 document spans and 51 distinct queries; two timestamp-only document additions. Capture hashes: `026fcc193d4522c426bc4deaa55a66d123f5ad2cf9c6217afc737bf6e665f0e0`, delta `d84ddddfa76ec4212147a2509ddee7087af904c22cd90daa10334774458cbf7a`. No inference rerun for transfer or replay. Initial/final loaded lists empty; own instance unloaded. Whole-system GPU snapshots vary; no zero-delta claim.

## Q068 diagnosis and fresh developer retrieval

- Original E001 rank6, cosine .592587; rank5 E055 .593555, rank1 E012 .622215. Correct prefix, full vector, 42 tokens, native/HTTP parity: no observed preprocessing or truncation fault. Pooling/quantization causality was not isolated. A threshold cannot fix absence from top5.
- Fixed exact-source-span maximum (full narrative plus first three sentences, no keyword fusion) moves E001 to rank4 (.610889), not rank1. This is a known-case diagnostic, never a fresh held-out win.
- Twelve genuinely new developer episodes/questions: top1 is 10/12 for BOTH full-narrative and span-max; T02/T09 remain rank2. No aggregate improvement. Cached diagnostic reproduction has identical ranks, maximum floating-point score delta 6.7e-16.

## Independent-case replay

- 40 cases, 17 declared scenario partitions, 30 episode definitions. Each case gets a fresh store containing its complete declared scenario; both versions get identical text/evidence partitions. Singleton scenarios are not evidence of global semantic discrimination.
- Five candidate-layer and35 hit-layer cases retained. Both layers and every accepted ID are in JSON. All five underdetermined contracts return candidates plus unknown/no hits: A1,A3,B3,B6,B7. B6 still fails its stricter uncertain-answer expectation; safety does not cancel that failure.
- Automated strict checks25/40; live-state assertions0/40; all40 SQLite integrity checks OK and foreign-key checks empty. C1/C7 live requests remain unknown; C2 returns latest historical E108, not live state.
- Observation ordering succeeds for B2/B5 and all dissent remains visible: B2 hits E113,E112,E111; B5 hits E118,E116,E117. Both fail because the candidate returns uncertain rather than supported.
- Raw required-ID rank bounds:22/26 in BOTH baseline full-text semantic and v0.2 span-max; misses A6,B2,B8,C8. Baseline frozen cosine gate .6769125518493936 accepts required IDs within bounds8/26. These are retrieval-only counts, NOT comparable end-to-end truth scores; v0.1 has no matching answer-contract/status API.
- D1/D2 forgotten and D3/F3 expired evidence leave no candidates or hits. Exactly E128 expires per applicable scenario. D4 deletes both declared shared-evidence dependents. v0.1 cannot attach this cross-run dependency through its public API: the baseline setup gap is marked explicitly, not advertised as a pure retrieval gain. F1/F2 retain two stable episodes after reopen/re-ingest; F3 expiry occurs after reopen.

## Every automated failing case (actual accepted IDs)

- **A4** — accepted `[]`; candidates `E102`; missing_or_late:E102; answer_status:unknown expected:supported.
- **A5** — accepted `[]`; candidates `E101`; missing_or_late:E101; answer_status:unknown expected:supported.
- **A6** — accepted `[]`; candidates `E104,E105`; missing_or_late:E105; answer_status:unknown expected:supported.
- **A7** — accepted `[]`; candidates `E104,E105`; missing_or_late:E104; answer_status:unknown expected:supported.
- **A8** — accepted `[]`; candidates `E123`; missing_or_late:E123; answer_status:unknown expected:supported.
- **B2** — accepted `E113,E112,E111`; candidates `E112,E111,E113`; answer_status:uncertain expected:supported.
- **B5** — accepted `E118,E116,E117`; candidates `E118,E116,E117`; answer_status:uncertain expected:supported.
- **B6** — accepted `[]`; candidates `E109,E110`; answer_status:unknown expected:uncertain.
- **B8** — accepted `[]`; candidates `E116,E117,E118`; missing_or_late:E118; answer_status:unknown expected:supported.
- **C1** — accepted `[]`; candidates `E107,E108,E106`; answer_status:unknown expected:supported.
- **C7** — accepted `[]`; candidates `E124,E125`; answer_status:unknown expected:supported.
- **C8** — accepted `[]`; candidates `E125,E124`; missing_or_late:E124; answer_status:unknown expected:supported.
- **D5** — accepted `E122`; candidates `E122`; answer_status:uncertain expected:supported.
- **D6** — accepted `E119`; candidates `E119`; answer_status:uncertain expected:supported.
- **D7** — accepted `E122`; candidates `E122`; answer_status:uncertain expected:supported.

## Interpretation and unresolved boundaries

- A4/A7/A8 free-text premises deliberately remain unresolved. A6/C8 lack typed replacement/relocation proof; A5 asks predicate reached while the store records outcome=reached; B8 asks measured while claims record charge. A6/B8/C8 also miss raw rank1. These are genuine capability gaps, not an invitation to use expected IDs to repair the adapter.
- B2/B5, B6, C1/C7 and D5/D6/D7 expose a status-model mismatch: relevant historical evidence, contested evidence, supported correction/unknown outcome, and answer certainty are collapsed too coarsely. Preserve strict failures; do not resolve them by changing labels after seeing results.
- Automated grading checks explicit ID/rank/status/guard rules, not every English fail_if clause. **C4 requires manual adjudication:** it passes explicit checks but also returns dated locked observations alongside the open record because the supplied contract lacks value=open. The bridge similarly does not implement general existential/all-history reasoning or verified transitions. 25/40 is an automated-check count, not independent acceptance or a proven complete semantic score.
- The supplied map is a reference input, not a demonstrated text-only parser. Its regex leak audit is not semantic provenance proof: e.g. E5 supplies an exact date absent from its question/context, D2 assigns fictional without a reality field in supplied context, and some contracts name corpus-specific instances not stated in the question. No expected IDs/dispositions enter the bridge; literal subject resolution consults the source claim catalog and is logged. No blanket claim that all map fields are text-derived.
- The first attempt failed during A1 source setup before search/scoring: unchanged PR1 EventFactory omits new narrative keys. A harness-only repair attaches bounded synthetic v0.2 fields after constructing the standard envelope; failed log/databases preserved. No live PR1 producer/adapter integration is claimed. Source expansion follows v0.1 outcome-before-close order with+1ms timestamps and exports shared OBS-A explicitly.
- Source claims/narratives are explicitly supplied, bounded and citation-bound; this does not establish the correctness of a future extractor. Original envelopes are externally exported; store keeps hashes, projections and bounded typed claims/narratives. Correction history is retained until forgetting/expiry; active text/vectors are invalidated. File-page forensic erasure is not qualified.
- This is synthetic/offline gateway replay plus previously captured main-PC vectors, not Windows v0.2 qualification, live GMod/voice acceptance, production migration, general NL answering or a new model recommendation. No service/configuration/deployment changes.

## Reproduce without model calls

See REVIEW_README.md in the evidence ZIP. Use Python stdlib, run new v0.2 unit tests, replay into a NEW output directory, and compare per-case IDs/status/guards, not random v0.1 UUIDs. All raw vectors, source events, frozen labels/maps, original benchmark fixture/capture, source tree, failed setup, full diff and SHA-256 manifest are included.

Next engineering proposal (not implemented on this holdout): explicit ontology/existence/value/time contracts and separate retrieval-support/answer-certainty/contested-evidence statuses; test on new developer cases, then use a newly frozen independent set. Keep current15 failures and C4 adjudication visible.
