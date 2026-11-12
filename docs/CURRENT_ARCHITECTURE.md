# Current architecture and PR 1 boundary

Baseline: `194ed3d2841a72ed1c2915f32d470f09d7f352a9` on
`gordon/memory-goal-improvements`, **not main**. Original canonical Python/Lua
hashes are in `RECORDER-BASELINE.json`. The original checkout contains a separate
uncommitted Jeep prototype; it is not included in this branch.

## Existing controller (preserved)

`greg_bridge.lua.buildState/pushState` emits client observations through a local
server net relay or local DATA files, selected per map. The Python collector
tails `data/greg/state.json` and `chat.json` (JSON Lines despite extension).
It schedules policy/agenda and social inference separately, keeps intent and
context fences, and alone writes `cmd.json`. Lua validates actor/session/epoch
and expiry, then executes bounded verbs and renewable deterministic navigation
at tick rate. Controller telemetry returns route/status/cursor/event/version.

`greg_playercore.Runtime` owns navigation/goal commitment; `StateGate` filters
fresh monotonic samples. Existing goal lifecycle, event/world/chat memory,
anti-repeat behavior, curb handling and rescue remain authoritative.
`greg_model.post_chat` preserves configured provider/model/settings. The optional
vision helper remains foreground-game-only and unchanged.

## Recorder addition (development only, not deployed)

The collector optionally instantiates `Recorder` + `ExperienceTracker`. The
tracker observes accepted samples, scoped model results, goal/route callbacks
and actual final command-write outcomes. Worker ContextVars carry immutable
decision identity, not live Runtime ownership. Only the recorder thread writes
the local SQLite DB; producer callbacks only admit bounded sanitized events.

Independent evaluation distinguishes file dispatch, controller reports, world
outcomes and recording closure. Telemetry loss closes the recording attempt as
unknown; it never cancels or resumes gameplay. SQLite is additional history,
not replacement working memory. Existing private diagnostic logs remain separate.

The CLI imports only recorder contracts/storage, not the collector or OpenClaw.
It queries local history or a consistent snapshot. No dashboard, server, mirror,
voice adapter, credential, port or service change is included.

## Evidence / limits

The earlier audit hash-verified old-PC deployment and saw current curb-v1
telemetry, arrivals and route failure at approximately 2026-10-20 19:22 UTC.
These are prior observations, not fresh deployment acceptance of PR 1. PR 1
testing uses synthetic game/model fixtures only. Current voice hooks, Windows
SQLite/filesystem behavior and a real enabled recorder session remain unverified.
No live service, model endpoint or Windows node was contacted for implementation.

Future deployment must rediscover mutable state, verify a coherent bundle,
preserve a single collector, and obtain separate owner authorization. Optional
recorder imports are guarded; absent/broken recorder modules cannot prevent the
existing collector from starting. No Lua protocol changes were necessary.
