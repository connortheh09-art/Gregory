# AIRI — events, perception and adapter state

Repository: [moeru-ai/airi](https://github.com/moeru-ai/airi). Pin: `1884f56565e79a85a07a869033d339964e8e2009`. Inspected 2026-10-27; source only, no Minecraft/server/model execution.

## Implemented paths worth studying

- [cognitive/index.ts](https://github.com/moeru-ai/airi/blob/1884f56565e79a85a07a869033d339964e8e2009/integrations/minecraft/src/cognitive/index.ts) wires perception pipeline, brain, reflex manager, task executor and AIRI bridge into the actual Mineflayer lifecycle. Chat becomes a signal and own messages are filtered.
- [event-bus.ts](https://github.com/moeru-ai/airi/blob/1884f56565e79a85a07a869033d339964e8e2009/integrations/minecraft/src/cognitive/event-bus.ts) defines immutable events with trace/parent IDs and inherited trace context; [perception/pipeline.ts](https://github.com/moeru-ai/airi/blob/1884f56565e79a85a07a869033d339964e8e2009/integrations/minecraft/src/cognitive/perception/pipeline.ts) emits perception events. [task-executor.ts](https://github.com/moeru-ai/airi/blob/1884f56565e79a85a07a869033d339964e8e2009/integrations/minecraft/src/cognitive/action/task-executor.ts) emits started/completed/failed action events around executor calls. An executor completion still needs interpretation, not automatic promotion to world proof.
- [minecraft-context-service.ts](https://github.com/moeru-ai/airi/blob/1884f56565e79a85a07a869033d339964e8e2009/integrations/minecraft/src/airi/minecraft-context-service.ts#L52) replaces a named status context with online/offline state, relay availability and observed position/health. [airi-bridge.ts](https://github.com/moeru-ai/airi/blob/1884f56565e79a85a07a869033d339964e8e2009/integrations/minecraft/src/airi/airi-bridge.ts) handles the command seam.
- [memory tools](https://github.com/moeru-ai/airi/blob/1884f56565e79a85a07a869033d339964e8e2009/packages/stage-ui/src/tools/memory.ts) expose read/write/forget; the [store](https://github.com/moeru-ai/airi/blob/1884f56565e79a85a07a869033d339964e8e2009/packages/stage-ui/src/stores/memory.ts) is persona-scoped local storage, not Recorder evidence.

## Trade-offs / Gregory already has

The pinned Minecraft README marks Mineflayer as moving toward a Fabric runtime and lists game long-term memory as future work. Do not infer shared persistent game experience from the existence of both game and memory modules. The memory/session ADR also records remaining live/privacy checks. Channel/scene scoping differs from Gregory's author+channel+guild isolation.

Gregory already has a Recorder event contract, correlation IDs, adapter session/freshness checks, a single Core writer and RAM dialogue scopes. It still needs compact turn-time capability facts that distinguish supported, connected and freshly observed state. Replacing its event system wholesale adds little.

## Small adaptation and acceptance

Use a Core-owned capability/status context view: stable supported capability separate from timestamped/session-bound availability; refresh or expire one keyed status block rather than accumulating stale prose.

Test: “Can you walk around in GMod?” acknowledges supported avatar control; disconnected/expired bridge blocks present-state/action claims; a new session supersedes old observations; Discord conversation still works. This is a Core self-knowledge slice, not approval for a new game integration.

## License / attribution

[Pinned LICENSE](https://github.com/moeru-ai/airi/blob/1884f56565e79a85a07a869033d339964e8e2009/LICENSE): MIT, Neko Ayaka. Preserve applicable copyright/license notices if code is copied; audit dependency, model and asset terms separately. No AIRI code or dependencies imported here.
