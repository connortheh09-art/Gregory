# Official Neuro Game SDK — integration protocol, not the brain

Repository: [VedalAI/neuro-sdk](https://github.com/VedalAI/neuro-sdk). Pin: `0cad33ac692f6cc90d36747fea9bbc53ca34b97a`. Inspected 2026-10-27: full 225-file snapshot, source trace plus eight isolated original-Randy handler probes and one WebGameRunner handler probe with synthetic dependency/environment doubles. **No Unity/Godot runtime or real game compatibility pass.**

## Implemented paths worth studying

- [API/SPECIFICATION.md](https://github.com/VedalAI/neuro-sdk/blob/0cad33ac692f6cc90d36747fea9bbc53ca34b97a/API/SPECIFICATION.md) and [BEST_PRACTICES.md](https://github.com/VedalAI/neuro-sdk/blob/0cad33ac692f6cc90d36747fea9bbc53ca34b97a/API/BEST_PRACTICES.md): capability registration, named actions/descriptions/parameter schemas, context updates and forced choices. These are wire contracts, not a supplied character/model/memory system.
- [ActionWindow.cs](https://github.com/VedalAI/neuro-sdk/blob/0cad33ac692f6cc90d36747fea9bbc53ca34b97a/Unity/Assets/Actions/ActionWindow.cs): temporary choices, optional decision request and withdrawal of disposable choices on acceptance.
- [CommandHandler.cs](https://github.com/VedalAI/neuro-sdk/blob/0cad33ac692f6cc90d36747fea9bbc53ca34b97a/Unity/Assets/Websocket/CommandHandler.cs#L63): queues a successful validation result **before** executing the action. An acknowledgment does not prove world completion.
- [Randy/index.ts](https://github.com/VedalAI/neuro-sdk/blob/0cad33ac692f6cc90d36747fea9bbc53ca34b97a/Randy/index.ts) is the random-choice test server, not Neuro's brain. Its isolated handler probes exposed startup/reset, registration, multi-client/force and timeout limitations. Do not treat Randy passing as SDK conformance or engine qualification.

## Trade-offs / Gregory already has

Unity/C# and Godot/GDScript game clients still need game-specific actions and Gregory's server endpoint; the SDK is not a GMod/Lua drop-in. Reconnect/queue replay requires generation/idempotency handling, and capabilities must be rebuilt after reconnection. The action-result timeout is an acknowledgment boundary, not an LLM inference budget.

Gregory already distinguishes commands/acceptance from evidenced outcomes and has correlation, source/session/epoch/freshness guards. Its Core identity, memory and Recorder remain authoritative. The public SDK does not replace them.

## Small adaptation and acceptance

When game work is authorized again: a thin local compatibility seam around Core, with temporary capability windows and explicit accepted/completed/unknown outcomes. First use a fake game, not a new engine migration.

Test: malformed/withdrawn/duplicate/stale actions reject; reconnect cannot replay old execution; an action accepted then failing execution remains failed/unknown, never “completed”; capability discovery accurately reports availability. Real-engine acceptance remains a separate later gate.

## License / attribution

[Pinned LICENSE.md](https://github.com/VedalAI/neuro-sdk/blob/0cad33ac692f6cc90d36747fea9bbc53ca34b97a/LICENSE.md): MIT, Vedal AI. Retain applicable license/copyright notices for reused code and record source pin/modifications. SDK licensing does not grant rights to Neuro's private software, identity assets or unrelated third-party SDKs. No implementation vendored here.
