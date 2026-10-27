# YuriOS — goals, salience and bounded initiative

Repository: [yuri-os/YuriOS](https://github.com/yuri-os/YuriOS). Pin: `da6a973dc451ce97d6534f52bdddc253de491452`. Inspected 2026-10-27; source only, no autonomous loop executed.

## Implemented paths worth studying

- [mind/goals.py](https://github.com/yuri-os/YuriOS/blob/da6a973dc451ce97d6534f52bdddc253de491452/yurios/mind/goals.py#L56): goals have provenance, priority, due time, lifecycle state and dispatch/product metadata. `GoalStore` parses and persists `goals.md`, supports updates and retires stale goals according to commitment. [goalwork.py](https://github.com/yuri-os/YuriOS/blob/da6a973dc451ce97d6534f52bdddc253de491452/yurios/mind/goalwork.py) handles work/settlement; it is not merely a prompt about “having goals.”
- [mind/loop.py](https://github.com/yuri-os/YuriOS/blob/da6a973dc451ce97d6534f52bdddc253de491452/yurios/mind/loop.py#L554) wires signals, cheap appraisal, one selected intention/act per tick, then reflection journal/trace. Candidate tool availability is checked before dispatch.
- [muse.py](https://github.com/yuri-os/YuriOS/blob/da6a973dc451ce97d6534f52bdddc253de491452/yurios/mind/muse.py#L78) gates free-time work on configuration, activity, engagement, cooldown, budget pressure and existing open work. [budget.py](https://github.com/yuri-os/YuriOS/blob/da6a973dc451ce97d6534f52bdddc253de491452/yurios/mind/budget.py) persists a daily estimated-token ledger.
- [dream.py](https://github.com/yuri-os/YuriOS/blob/da6a973dc451ce97d6534f52bdddc253de491452/yurios/mind/dream.py#L145) consolidates daily journals, deduplicates fact strings, tracks progress and indexes distilled facts with increased salience. [memory/store.py](https://github.com/yuri-os/YuriOS/blob/da6a973dc451ce97d6534f52bdddc253de491452/yurios/app/memory/store.py#L413) ranks by similarity, salience and recency, with deduplication/MMR and forgetting tombstones.

## Trade-offs / Gregory already has

Token accounting is estimated, not a hard inference deadline; the first oversized consolidation day is deliberately allowed to progress. Summaries are model-derived; salience is not evidence strength. `remember()` journals/indexes exchanges and updates a partner model, a broader collection policy than Gregory's selective explicit-first direction. Markdown goals and automatic persona evolution must not become new authorities beside Core.

Gregory already has owner-authored goals in its profile, correlated decisions and bounded model calls, but not this persisted goal lifecycle or an approved autonomous reflection scheduler. Source tests in YuriOS are references, not evidence we have run or ported them.

## Small adaptation and acceptance

Deferred until earlier milestones pass: one Core-owned goal with provenance and pending/active/waiting/done/cancelled state, owner pause control and a bounded step budget. Reuse the lifecycle idea, not the entire mind loop.

Test: unfinished work survives restart; cancellation prevents the next step; repeated completion evidence does not duplicate completion or a message; unavailable adapters block dispatch; a spent background budget never silences direct conversation.

## License / attribution

[LICENSE](https://github.com/yuri-os/YuriOS/blob/da6a973dc451ce97d6534f52bdddc253de491452/LICENSE): Apache-2.0. Proposed code reuse must retain applicable license/notices, identify modifications and inspect any applicable NOTICE/file headers and patent conditions. [THIRD_PARTY_NOTICES.md](https://github.com/yuri-os/YuriOS/blob/da6a973dc451ce97d6534f52bdddc253de491452/THIRD_PARTY_NOTICES.md) and [PROVENANCE.md](https://github.com/yuri-os/YuriOS/blob/da6a973dc451ce97d6534f52bdddc253de491452/PROVENANCE.md) distinguish project history, models and separately licensed visual assets. No code or weights reused here.
