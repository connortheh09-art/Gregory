# Gregory engineering reference library

**Research existing solutions before reinventing them.** Owner direction: Connor/Anthony, 2026-10-27, Discord message 1564752694864777289. This is a growing library of engineering evidence, not a framework migration plan or a collection of cloned characters.

## Starting points

- [Kokoro Engine](kokoro-engine.md): conversational fact extraction, deduplication and revision-checked consolidation proposals.
- [YuriOS](yurios.md): persisted goal lifecycle, budgeted reflection/consolidation, salience and bounded initiative.
- [AIRI](airi.md): traced events, perception/action wiring and replaceable live capability/status context.
- [Super Agent Party](super-agent-party.md): transport lifecycle, tool discovery and platform managers; different privacy/licensing assumptions.
- [Official Neuro Game SDK](neuro-sdk.md): capability schemas, temporary action windows and game integration protocol, not Neuro's private brain.

All five cards cite immutable commits and actual inspected code. [catalog.json](catalog.json) records pins and hashes of the cited inspection set. No third-party implementation is vendored here. Snapshot date is **2026-10-27**; these are not claims about a repository's latest version forever.

## Use this without creating a research treadmill

1. Read the closest card and its key implementation. Reuse existing inspected evidence if still applicable.
2. Identify a specific pattern worth adapting, or state why Gregory's existing implementation is sufficient.
3. Write a small decision using [the template](TEMPLATE.md): source pin, differences, minimal change, acceptance test and licensing if copying code.
4. Implement only the authorized slice. Record the actual result and update the card when new evidence changes it.

One relevant source and a concrete test can be enough. Expand research only to close an identified gap. A library entry does not authorize installing dependencies, changing permission boundaries, importing arbitrary tools or enabling autonomous behavior.

## Gregory comparison baseline and immediate priority

The comparisons use the **accepted 302 Core dialogue packet** plus the **321-test memory-consistency candidate**, not this older GMod checkout's HEAD as if it contained those newer Core files. At this snapshot the Core artifacts were reviewed/tested independently by Greg; deployment and live behavior require separate receipts. This documentation does not migrate those source trees into the checkout.

- Dialogue packet: `GREGORY_CORE_WORKING_DIALOGUE_FIX.zip`, SHA256 `646b54d5cd3c95f82f11a2e3157a3a26e1d62c9f42fbd07e427de2eb16b520fa`.
- Grounding candidate: `GREGORY_MEMORY_CONSISTENCY_FIX.zip`, SHA256 `d311adf7e41d0ef5ab2c0e4b8806c6a02da7a920cff77dbdd310ba5c96781c60`.
- Existing: single authoritative Core root/writer, cited Recorder episodes, keyword/semantic retrieval with an abstention floor, scoped chronological RAM dialogue, bounded turn/drain behavior, and historical-versus-current-state safeguards. Candidate adds owner-scoped bounded overview and validated citation declarations. Tests do not prove natural model behavior.
- **Immediate engineering priority remains the memory-grounding regression and its live acceptance.** Do not delay it for library work. Then follow owner milestones: continuity, separate context experiment, compact self-knowledge, explicit persisted remember/write/restart recall before opt-in automatic candidates. Goals/initiative implementation waits for earlier demonstrations.
- No automatic promotion of transcripts or generated personality statements. Supported capability, connected adapter and fresh world observation remain different facts.

## Evidence and licensing discipline

Cards distinguish code inspected from docs advertised, tests present from tests actually run, and any runtime gaps. The SDK has isolated handler probes from the earlier study; no Unity/Godot game runtime was qualified. Other projects here were source-inspected only; no third-party installer, model or service was executed.

For a proposed copied component, inspect the pinned license, file headers, notices, dependencies and assets. Record provenance and modifications with the change. MIT entries require retaining applicable notices; Apache-2.0 and AGPL-3.0 entries have different conditions detailed in their cards. A repository license does not automatically cover external models, Live2D assets or services. Studying a pattern is not approval to redistribute its code.
