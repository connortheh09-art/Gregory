# Memory v0.2 — independent review (Greg)

Bundle: `GREGORY_MEMORY_V02_REVIEW.zip`
SHA-256 observed: `0beb683e050763904730fcf746311fec051b9a8afdd93eeb9117f4b21f647451` — matches the stated hash.
Core scored at `1a8d6e8320cf789b7e23079b80f4ce2567006ce7`, harness `e447bdb`. Cited commit `5bd54e26a37d1c423a02e9e901f224fa3904e985` not fetched this review (offline bundle used; no network claim).

## Verdict

**Run integrity: PASS. Score: 25/40 behaviorally confirmed. Promotion: NO.**
The numbers reproduce. The failures are real and were reported against the author's own interest. My own evaluation instrument has four documented defects, and two of them (C4, E5) change how three cases should be read.

## 1. Bundle integrity — PASS

- ZIP hash matches, `testzip()` clean, 193 entries.
- MANIFEST: **192/192 verified** on both SHA-256 and byte length. Zero missing, zero files on disk outside the manifest.
- Frozen fixture in `inputs/` hashes `83ec6a43…` = the v1.5 set I froze. Contract map cited `d7194ab0…` = my v1.1 exactly.
- `live_state_asserted` false on all 40 — 0 live-state violations, checked independently, not taken from the summary.
- 40/40 SQLite integrity OK, foreign-key checks empty.

Defect, low severity: the bundle ships **two** contract maps and the un-suffixed `GREGORY_V02_QUERY_CONTRACT_MAP.json` is my stale v1.0 (`66159985…`, no typed obligations). The citation points at `_v1_1.json` and is correct, but a stale artifact under the canonical name is how the wrong file gets scored next time. Ship one.

## 2. Score — 25/40 reproduces

Independent recompute from per-case rows using my own rules: **23/40** under literal label matching, **25/40** once A1/A3 are read behaviorally. The entire gap is two cases:

- **A1, A3** — candidate returns `unknown`; my v1.5 label demands the string `unconfirmed_contract_underdetermined`. That name is my invention, introduced in the same revision that renamed the status. `unknown` satisfies the behavioral requirement (no assertion, retrieval still satisfied at rank 1). **I accept 25/40.** Recording that I relaxed a string I invented, after seeing results — that direction favours the candidate and should be flagged, not buried.

Two of my earlier strict rules were wrong and I retract them:

- **B3, B7** — my `fail_if` said "any result returned". The candidate returns `accepted_ids: []` with both reports as *candidates* and status `unknown`. That is correct behavior: surface the reports, assert no agreement, name no liar. My wording failed to distinguish *asserted* from *shown*; the failure was mine.
- **B6** — fails under frozen labels (`unknown` vs `uncertain`) and I keep the failure. But the cause is joint: my contract for B6 is underdetermined, so a system cannot scope the conflict the case requires it to detect. Not a candidate defect alone.

## 3. Retrieval — no aggregate win, and the ranks are identical

For all 32 required IDs across retrieve/contested cases, the v0.1 raw rank and the v0.2 candidate rank are **the same number in every row**. 28/32 within `min_rank` in both. Identical misses: A6 (E105 rank 2), B2 (E113 rank 3), B8 (E118 rank 3), C8 (E124 rank 2).

That is stronger than "no aggregate improvement" — it is no rank movement at all. The stated 22/26 uses a denominator six smaller than my 32; the four misses agree exactly, so the conclusion holds under either denominator, but the counts are not interchangeable and should not be quoted as if they were.

## 4. Held disagreement — B2/B5

Observation ranked first (B2 `E113,E112,E111`; B5 `E118,E116,E117`), dissent retained, `must_remain_visible` satisfied. Candidate returns `uncertain/contested`; I require `supported` with conflict preserved. **Unresolved and recorded as a genuine disagreement**, not a harness artifact. If ranking observation first never changes the status, `observed > reported` is decorative.

## 5. C4 — automated pass, manual FAIL, and the root cause is partly mine

Query: "Have you ever recorded that door standing open?" Accepted: `E107` (open), `E108` (locked), `E106` (locked). Two refuted instances accepted for an existential query. **FAIL on adjudication.**

My contract for C4 is `subject=depot_door, predicate=state, mode=ever` with **no value constraint** — even though the question says "standing open". The value is in the text and I failed to encode it. So the over-answer is co-caused by my map. His decision to flag C4 rather than bank the automated pass is the correct call.

## 6. Defects in my own instrument — confirmed, not just alleged

1. **E5 fabricates a timestamp.** My contract supplies `as_of 2026-10-20T11:00:00Z`. The case's supplied context is `{domain: gmod}` with `as_of: null`, and the question contains no date. Corpus-derived.
2. **D2 fabricates `reality: fictional`.** Supplied context has `{domain: discord}` and no reality field.
3. **Provenance self-inconsistency:** `frozen_against_fixture` names v1.5 while `frozen_against_sha256` is `a58a6d42…` = v1.4.
4. **"Text-derived only" was overstated.** 13 of 40 contracts name corpus-specific subjects absent from the question text (B4/B5 `drone_battery`, C3/C5 `depot_door` from "that door", E6, F2, A3–A5, A8). My leak audit only swept for episode identifiers and disposition vocabulary, so it could not have caught this. The claim in my freeze was too strong and I am correcting it here rather than editing the artifact after the run.

Consequence: the map is a **reference input with declared corpus resolution**, not a demonstrated text-only parser. That is now the accurate description.

## 7. Procedure — acceptable

- First replay failed at A1 source setup (`ValueError: narrative must match a cited source record`) before any search. Log and databases preserved; repair is harness-only and declared. No live PR1 producer integration claimed. Correct handling.
- 29/29 new unit tests before scoring; four original core files byte-identical to v0.1 with hashes; full diff and failed setup included.
- 15 failures preserved and published, including cases that flattered the candidate. No relabeling after scores.
- Freeze timestamps from both sides are unreliable (mine included); provenance rests on attachment order and hash receipts. His statement of that is accurate.

## Bottom line

25/40 stands. Nothing was tuned, nothing was hidden, and C4 was escalated against self-interest. The candidate is a prototype with a real status-model gap (contested vs supported, uncertainty collapsed too coarsely) and no retrieval improvement over v0.1 on this set. My instrument needs a v0.3 correction pass before it can carry another comparison: value constraints from the text, no fabricated context, honest corpus-resolution labels.

No promotion. No production claim. Next independent comparison should use a newly frozen set, not this one.
