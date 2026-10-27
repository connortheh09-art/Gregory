# Kokoro Engine — memory extraction and consolidation

Repository: [chyinan/Kokoro-Engine](https://github.com/chyinan/Kokoro-Engine). Pin: `30b995c6ce8ce8f7f1841cb65e2f1176d655aaff`. Inspected 2026-10-27; source only, no runtime acceptance.

## Implemented paths worth studying

- [commands/chat.rs](https://github.com/chyinan/Kokoro-Engine/blob/30b995c6ce8ce8f7f1841cb65e2f1176d655aaff/src-tauri/src/commands/chat.rs#L3943) calls extraction periodically when memory is enabled; this is a wired chat path, not just a helper.
- [memory_extractor.rs](https://github.com/chyinan/Kokoro-Engine/blob/30b995c6ce8ce8f7f1841cb65e2f1176d655aaff/src-tauri/src/ai/memory_extractor.rs) extracts notable facts/importance, supplies existing memories to discourage duplicates, then calls storage. [memory_event_ingress.rs](https://github.com/chyinan/Kokoro-Engine/blob/30b995c6ce8ce8f7f1841cb65e2f1176d655aaff/src-tauri/src/ai/memory_event_ingress.rs) adds optional event/cooldown triggers; inspected event-trigger defaults are disabled.
- [memory.rs](https://github.com/chyinan/Kokoro-Engine/blob/30b995c6ce8ce8f7f1841cb65e2f1176d655aaff/src-tauri/src/ai/memory.rs#L2728) contains candidate admission, exact/entity-slot/semantic deduplication and character-scoped storage; retrieval combines keyword and semantic ranking with a floor.
- The same module implements `run_dream_pass`, `auto_merge_dream_group` and [approve_dream_proposal](https://github.com/chyinan/Kokoro-Engine/blob/30b995c6ce8ce8f7f1841cb65e2f1176d655aaff/src-tauri/src/ai/memory.rs#L4081). Approval captures source versions and checks ownership/current revisions in a write transaction. Tests for stale/deleted/foreign targets and rollback are present, not executed in this review. Do not reduce this to “an LLM rewrites everything nightly.”

## Trade-offs / Gregory already has

Extractor source references are empty in the inspected candidate insert, and confidence includes a fixed constant: neither is Gregory-grade message evidence or calibrated truth. Model-proposed facts and entity replacements require authority/correction policies. Background work also needs cancellation and model-slot budgets.

Gregory already has durable cited Recorder episodes, one writer, expiry/corrections and hybrid retrieval. It does **not** yet have verified conversational fact writes or a background consolidation job. Keep facts, reported statements and evolving traits distinct.

## Small adaptation and acceptance

After explicit remembering works: queue a bounded, opt-in fact candidate linked to exact Discord author/message/time. Validate/dedupe in Core; consolidation proposes version-checked changes rather than creating another store.

Test: explicit remember confirms only after commit and survives restart; later candidate extraction deduplicates repeated introductions, preserves correction/deletion, rejects a stale revision and leaves the real oil-drum episode unchanged. Automatic extraction remains a later step, not an excuse to bypass the owner's explicit-first order.

## License / attribution

[Pinned LICENSE](https://github.com/chyinan/Kokoro-Engine/blob/30b995c6ce8ce8f7f1841cb65e2f1176d655aaff/LICENSE): MIT, copyright chyinan. If copying substantial code, retain copyright/license notices and record source pin/modifications. External assets, Live2D runtimes and models need their own checks. No implementation code is copied by this library.
