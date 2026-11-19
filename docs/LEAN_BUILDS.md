> This branch: **0018**. Source commit before publication notes: `05059e8f26c18a5770e77c0a1f13c06b7bf16488`.

# Preserved lean build history

Published 2026-11-19 as experimental source branches, not a promotion to `main`.
Each branch contains its complete source and tests. The original review worktrees,
patch kits and private evidence are retained separately. Models, bot credentials,
runtime databases, voice recordings, conversations and model-request captures are
not included in this publication. See `RESTORE.md` for source-only recovery limits.

## Versions

| Branch | Changes | Previously completed Linux suite |
| --- | --- | --- |
| [controller-qualified-0018](https://github.com/connortheh09-art/Gregory/tree/gordon/controller-qualified-0018) | Recovery base plus controller slices, one-writer arbitration, feedback and fenced shutdown fallback | 865/865 |
| [lean-0019](https://github.com/connortheh09-art/Gregory/tree/gordon/lean-0019) | Action before reply; smaller positive prompts; stop menu scoped to active drive/task; one stop ends body and task | 867/867 |
| [lean-0020](https://github.com/connortheh09-art/Gregory/tree/gordon/lean-0020) | Required drive look/pace/jump; ahead means keep facing; provider-level capture; no-change draft removed | 868/868 |
| [lean-0021](https://github.com/connortheh09-art/Gregory/tree/gordon/lean-0021) | Null-intent speech schema, explicit stop wording and no-change response rule | 870/870 |
| [lean-0022](https://github.com/connortheh09-art/Gregory/tree/gordon/lean-0022) | Only the applicable receipt-status rule appears in finalization | 870/870 |

These are prior qualification runs, not new tests run for publication. Publication
reconstructed all 17 pinned patches and verified every build byte-for-byte against
its preserved source worktree (213 files through 0020; 214 for 0021/0022). Original
patch authorship is retained where supplied. `LEAN_BUILD_PROVENANCE.json` records
this branch's source commit, patch hashes and pre-documentation source inventory.

## Offline results: keep batches separate

- Early 8K decision replay at temperature 0.4: stock Gemma original prompt 29/100
  versus 0019 79/100; Qwen 9B 23 to 32, Qwen 4B 10 to 20. These are not 16K runs.
- Paired 16K 0019 versus 0020: Gemma 78 to 100/100 at 0.4, 73 to 95/100 at 1.0.
- A separate paired 16K 0020 versus 0021 batch: Gemma 99 to 100/100 at 0.4 and
  96 to 100/100 at 1.0. Coding Monkey 45 to 43 and 55 to 54 respectively; all
  40 of its 0021 stop trials selected null. These results do not support a swap.
- 0021's speech schema fixed observed reply structure but introduced accepted-action
  deferrals. The 48-request 0021/0022 speech comparison reduced those deferrals
  from 6/6 to 0/6; all 48 replies passed schema/null-intent checks. Four of six
  0022 accepted-jump replies copied the irrelevant "lead the way" example.
- No decision tests were rerun for 0022: decision code was unchanged.

Each scored decision arm contains 100 action trials plus separate chat cases;
100/100 is fixture action accuracy, not universal reliability or gameplay success.
The required-field/example changes were bundled, so they do not isolate a single
causal mechanism. Temperature 1.0 remains the live reference; no permanent model
or temperature change is implied. HTTP timing is not voice or movement latency.

## Supervised 0022 gameplay observations, 2026-11-18

- Walking reached about 200 units/s; explicit running about 400 units/s and 640
  units of displacement. Right and left-plus-forward turning were observed.
- Four correctly selected jump taps reached the receiver's `done` state but
  produced zero recorded airtime. Jump is NOT qualified. Consuming a one-shot
  press on an unsent CreateMove command is a hypothesis requiring server input
  evidence, not an established fix.
- Stop/cancel was absent from the decision schema during some autonomous routes
  when the direct drive/task state was empty. This is a menu/route coverage bug.
- Chat, screen and backwards requests sometimes copied the forward-walk example.
  Screen inspection was offered, but never selected; no image was sent.
- The second segment used a direct-only diagnostic wrapper that removed task and
  continue choices. It was not unchanged 0022. That wrapper and the run-only
  25-minute CLI-limit edits are NOT included in these source branches.
- One HTTP 400 reported `bad allocation` under high system commit pressure;
  that does not establish a cache or earlier black-screen cause.
- Cleanup restored the original receiver and removed temporary activation hooks;
  owned game/voice/bridge/model processes were closed. Original builds are kept.

Remaining work includes receiver jump diagnosis, stop coverage for every route,
chat/backwards prompt coverage, receipt-grounded speech and another supervised
acceptance run. No 0023 or jump fix is included. No automatic deployment, launch,
new Discord outbound action, model swap or `main` merge is part of publication.

## Capture handling

`GREG_MODEL_CAPTURE` and `GREG_DECISION_CAPTURE` are opt-in diagnostics, not a
reason to commit runtime data. Model capture can contain full prompts, replies and
errors; keep resulting files private. Existing capture limitations include no
explicit truncation flag and no stable turn/call identity for repeated prompts.

## Source lineage

Recovery source base: `791f2add0879d7975b57cb68d1c644ff953a7368`.
Controller sequence: 0001, 0002, 0003, 0004, 0005, 0006, 0010, 0007, 0014,
0015, 0016, 0017, 0018; then lean sequence 0019, 0020, 0021, 0022.
Patch numbers reflect the reviewed/rebased history, not a missing linear series.
