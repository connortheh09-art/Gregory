# Gregory — real local Nomic benchmark results

Date: 2026-10-22 UTC. **TESTED: benchmark completed. Production readiness NOT established.** Independent results review pending; Greg cleared the frozen fixtures before measurement.

## Scope and fairness

Retrieval over **67 fixture-authored, evidence-linked reported narratives**, attached through the unchanged memory API. This does not measure automatic narrative consolidation, gameplay, a live-state adapter, or generated answers. 436 synthetic recorder events; 61 episodes remain after exactly three expiries and three forget operations.

Labels frozen at `9496aaf` before model scores: **24 dev / 75 held-out**, target episode sets disjoint, E001 held-out only. Five configurations share k=5, the final corpus hash, eligible IDs, domain/session filters and fixed clock. Temporal filters are supplied query context, not inferred date understanding. 59 held-out supported queries, 15 no-evidence queries, one assertion-only query; Q097/Q098 score historical retrieval separately from live assertions. No labels, methods or thresholds were revised after seeing held-out results.

Dev-only balanced-answerability threshold selection (highest-threshold tie): FTS 5.841723705891411; v1.5 cosine 0.6769125518493936; v2 cosine 0.36382727138745197. Each hybrid shares its semantic gate. `DEV_CALIBRATION.json` was written before held-out scoring and its SHA is bound in the evidence.

## Held-out results — accepted hits

Recall is mean per-query fraction of expected IDs found; MRR uses the first correct accepted hit. All 495 dev/test query/config rows contain expected_ids, ranked_ids, retrieved_ids, scores, thresholds, misses, wrong IDs and timings. No-evidence FPR is separate.

- **fts5**: R@1/3/5 **28.8% / 44.1% / 45.8%**; MRR 0.4054; false retrieval 2/15 (13.3%); false abstention 32/59.
- **semantic-v15**: R@1/3/5 **66.9% / 79.7% / 79.7%**; MRR 0.7797; false retrieval 3/15 (20.0%); false abstention 11/59.
- **semantic-v2**: R@1/3/5 **53.4% / 67.8% / 67.8%**; MRR 0.6525; false retrieval 4/15 (26.7%); false abstention 17/59.
- **hybrid-v15**: R@1/3/5 **50.0% / 74.6% / 74.6%**; MRR 0.6667; false retrieval 3/15 (20.0%); false abstention 11/59.
- **hybrid-v2**: R@1/3/5 **43.2% / 64.4% / 64.4%**; MRR 0.5819; false retrieval 4/15 (26.7%); false abstention 17/59.

Ungated Recall@5 (diagnostic, not the primary thresholded measure): FTS 84.7%; v1.5 semantic 93.2%; v2 semantic 96.6%; hybrid-v1.5 91.5%; hybrid-v2 91.5%. The dev gate materially changes coverage. Do not interpret a positive cosine as evidence of truth.

## Milestone and failures

**Q068: “Remember when you had trouble following me?” → E001.**

- FTS: E001 rank1, accepted.
- v1.5 semantic: E001 absent from raw top5; gate also rejects the query.
- v1.5 hybrid: E001 raw rank1, but rejected by the shared dev cosine gate.
- v2 semantic: E001 rank2, accepted.
- v2 hybrid: E001 rank1, accepted.

The milestone therefore passes for the installed v2 hybrid configuration, not for every Nomic lane. The keyword baseline also succeeds on this particular prompt; this one success is not proof of a semantic advantage.

Failure cases are retained, not tuned away: Q089 (real vs fictional dessert preference) produces false hits in all lanes; Q090/Q095 (unrecorded real-life achievements) fool both semantic configurations; Q092 (nonexistent private password) fools v2. FTS also falsely retrieves for Q094 (Mars spaceship). These are retrieved candidates, not generated factual assertions, but they demonstrate that similarity-only abstention does not reliably establish support.

## Local artifacts and prefix evidence

LM Studio0.4.22.0, native SDK1.5.0, HTTP localhost:1234 /v1/embeddings. Explicit LOCAL indexed paths selected (not duplicate LM Link models). gpu.ratio=0; contextLength=512; full768 vectors, L2 normalization, separate hash/config/prefix-specific spaces. v1.5 Q4_K_M vs v2 MoE Q8_0 is an **installed-configuration comparison**, not equal-precision model-family ranking.

- v1.5 key `text-embedding-nomic-embed-text-v1.5`; file `nomic-ai/nomic-embed-text-v1.5-GGUF/nomic-embed-text-v1.5.Q4_K_M.gguf`; 84106624 bytes; SHA256 `d4e388894e09cf3816e8b0896d81d265b55e7a9fff9ab03fe8bf4ef5e11295ac`.
- v2 key `text-embedding-nomic-embed-text-v2`; file `ggml-org/Nomic-Embed-Text-V2-GGUF/nomic-embed-text-v2-moe-q8_0.gguf`; 512225120 bytes; SHA256 `36c5817bc25f379e62021f49efde05b10ed3b0c93ab8059c43173a7a5de73565`.

Exactly one explicit `search_document: ` or `search_query: ` is included in every captured corpus/query input, following the [v1.5](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5) and [v2](https://huggingface.co/nomic-ai/nomic-embed-text-v2-moe) model-card instructions. Native tokenizer maxima:42/46 tokens, well below512. REST usage counters return zero and are NOT used as token measurements.

Raw/single/double-prefix probes: native SDK and HTTP vectors are byte-value identical for the same literal input (max absolute difference0); raw vs prefixed and single vs double-prefixed vectors differ for both installed artifacts. Thus no prefix stripping/dedup or API-vs-native formatting difference was observed; explicit single prefixes were retained. Backend-internal preprocessing common to both paths was not independently instrumented. All raw vectors, token IDs and probes are included; no opaque “prefix verified” claim substitutes for them.

## Timing and resources

Shared initial ingest/FTS construction, lifecycle preparation and both cached vector indexes took 0.261s on Windows, excluding real embedding capture. Dedicated FTS-only build latency was not separately isolated.

Main-PC captures: v1.5 then v2, serial CPU-only requests; 70 unique initial/corrected document variants once per model; all99 queries repeated3 full passes. Warm OS/model file caches after prefix probes; NOT cold-cache runs. Retrieval replay uses cached vectors, timed separately from actual HTTP query encoding. Hybrid and semantic share the same captured query embeddings (not additional inference runs). Indexing measurements are single observed builds, not latency distributions.

- v15: document encoding wall 3.119s (HTTP-call sum 2.613s); 67 initial vector inserts 0.046s; 3 corrected reindexes 0.002s. All repeat vectors identical (max delta0).
- v2: document encoding wall 3.726s (HTTP-call sum 3.092s); 67 initial vector inserts 0.048s; 3 corrected reindexes 0.002s. All repeat vectors identical (max delta0).
- fts5: held-out retrieval median/max 0.15/3.00ms (225 samples).
- semantic-v15: held-out retrieval median/max 4.07/15.18ms (225 samples); HTTP query embedding 15.30/40.73ms (225 samples).
- semantic-v2: held-out retrieval median/max 4.74/16.20ms (225 samples); HTTP query embedding 21.17/60.91ms (225 samples).
- hybrid-v15: held-out retrieval median/max 5.43/20.26ms (225 samples); HTTP query embedding 15.30/40.73ms (225 samples).
- hybrid-v2: held-out retrieval median/max 5.86/20.78ms (225 samples); HTTP query embedding 21.17/60.91ms (225 samples).

GPU snapshots: ~16.3GB total, >=12.0GB free during load snapshots; CPU-only configuration is confirmed, but observed GPU/RAM deltas are whole-system snapshots, not attributable process peaks. Available RAM: v1.5 before14.15GB / loaded13.64GB; v2 before13.21GB / loaded11.89GB. Repeated resource snapshots are in raw captures; peak VRAM, CPU-thread attribution, concurrency stress, GPU acceleration and long-context behavior are UNTESTED.

## Lifecycle, provenance and history safety

retention_seconds=2592000; fixed synthetic clock 2026-10-22T12:00→14:00Z. EXACT abort checks pass: expire E061/E062/E066, forget E063/E064/E067; correct E059/E060/E065. All other61 retained, expected targets eligible. Corrected FTS text replaced, vectors purged before reindex; forgotten/expired FTS/vectors/revisions/citations absent. Before/after search-ID snapshots and full provenance are included. Narrative attachment creates revision2, subsequent lifecycle correction revision3; these are reported owner claims, not new observations.

All returned history links to ingested event IDs and derived canonical envelope hashes. Integrity ok, FK violations0. Typed historical envelopes retain historical_only=true/current_world_state=unknown; zero typed live-state violations. Q097/Q098 can correctly return historical coordinates/door memories; they never authorize current coordinates/state. No text generator or actual live-game assertion path was tested. Cross-memory contested detection remains PROPOSED v0.2, not implemented here.

## Reproduction and limitations

Source branch `gordon/nomic-memory-benchmark`; engine `9ab1f17`, pinned Windows bootstrap `6131cae`. Run `python benchmarks/nomic/run_benchmark.py --captures <directory-containing-CAPTURE_*.json.gz> --out <new-output-directory>`. No model required for arithmetic replay. Capturing new embeddings is a separate, explicitly guarded local model action; published worker uses only installed files.

Windows Python3.15.1/SQLite3.53.4 source ID `bf7c7f30031888f4e796e429ab3978879485813aaca6f641c7b33e4e09459bcc`. Gateway replay Python3.11.2/SQLite3.40.1 reproduces all headline recall/MRR/FPR aggregates within1e-12. **53/495 raw rankings differ**, confined to keyword/hybrid equal-score ties: unchanged core generates random UUID4 memory IDs and uses those as tie-breaks. Neither semantic lane differs. This is not bit-identical per-query replay; original Windows IDs/outputs are preserved. A deterministic tie policy is a proposed subsequent engineering fix, not silently applied after results.

New harness tests5/5 pass: dev-only calibration, conservative selection, multi-target/abstention arithmetic, real-core lifecycle/model-space separation, drift abort. Independent metric arithmetic recomputation passes for all5 rows. No B0 87-test rerun or Lua execution.

## Decision / next gate

**TESTED:** real local configurations, five-row benchmark, raw per-query evidence, dev-only calibration, lifecycle/provenance and typed historical guard. **UNTESTED:** production answer support, generalization beyond this small curated corpus, equal-precision family quality, automatic consolidation quality, live voice/game integration.

**PROPOSED:** no production backend qualified yet. Keep installed v1.5 semantic as the stronger aggregate offline baseline; retain v2 hybrid as the successful headline-case comparison. Next evaluate a preregistered support/fictionality-aware abstention policy and deterministic tie handling on NEW held-out questions, then request independent review. Do not adjust this run’s thresholds to rescue Q068.

PR1 remains3add789; Memory v0.1 remainsc5e08e5. No recorder/CLI/Lua/Jeep changes, old-PC access, service restart, server/exposure edit, foreign-model unload, merge or deployment. Before/after loaded-model lists empty; existing gregman/gregctl PIDs unchanged. Private SDK dependencies only; no new model downloads.
