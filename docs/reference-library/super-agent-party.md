# Super Agent Party — modular tools and platform transports

Repository: [heshengtao/super-agent-party](https://github.com/heshengtao/super-agent-party). Pin: `3aac964122415fe289a1b8af1000474b397c916b`. Inspected 2026-10-27; selected source only, no installations, MCP servers or platform connections.

## Implemented paths worth studying

- [mcp_clients.py](https://github.com/heshengtao/super-agent-party/blob/3aac964122415fe289a1b8af1000474b397c916b/py/mcp_clients.py#L24) builds stdio/WebSocket/SSE/streamable-HTTP transports, initializes sessions and discovers tools. A single monitor handles reconnect/ping and clears connection state. `get_openai_functions` maps descriptions/input schemas into function definitions; `call_tool` is a concrete dispatch path, not only an advertised plugin list.
- [discord_bot_manager.py](https://github.com/heshengtao/super-agent-party/blob/3aac964122415fe289a1b8af1000474b397c916b/py/discord_bot_manager.py) contains startup/ready/shutdown state and streaming/tool integration. [telegram_bot_manager.py](https://github.com/heshengtao/super-agent-party/blob/3aac964122415fe289a1b8af1000474b397c916b/py/telegram_bot_manager.py) is a separate platform lifecycle manager.
- [agent_tool.py](https://github.com/heshengtao/super-agent-party/blob/3aac964122415fe289a1b8af1000474b397c916b/py/agent_tool.py) exposes enabled configured agents through a tool schema and local-compatible endpoint. [extensions.py](https://github.com/heshengtao/super-agent-party/blob/3aac964122415fe289a1b8af1000474b397c916b/py/extensions.py) implements download/unpack/install management. These paths are present; platform correctness and installed extensions are not qualified here.

## Trade-offs / Gregory already has

Discord's inspected working history/tasks are keyed by channel ID, not Gregory's per-author privacy tuple. MCP failures can return None or an error string, which is weaker than a typed accepted/completed/unknown contract. Calls hold a connection lock; reconnect is not proof of idempotent execution. Installing extension archives can introduce dependency execution; discovery is not authorization.

Gregory already has serial triggered Discord delivery, allowlists, participant-isolated recent context, cancellation and ambiguous-send handling. Keep one character/memory authority; a cross-platform manager is not an argument for multiple competing agent brains or a Discord-only memory store.

## Small adaptation and acceptance

Later, define one narrow adapter/tool catalogue with names, schemas, availability and explicit typed outcomes, using Core's existing lifecycle and authorization. Do not implement an extension marketplace to solve today's grounding defect.

Test with a fake transport: disconnect withdraws tools, reconnect refreshes the catalogue, stale/duplicate requests cannot execute twice, errors never become success, and two users' dialogue never merges. No real third-party tool execution needed for that first test.

## License / attribution

[Pinned LICENSE](https://github.com/heshengtao/super-agent-party/blob/3aac964122415fe289a1b8af1000474b397c916b/LICENSE): GNU AGPL v3 text, **not MIT**. Any proposed code reuse needs a specific compatibility/source-distribution/network-interaction obligations review, retention of required notices and disclosure of modifications as applicable. Inspect `LICENSE-third-party/` and file headers too. Default here is architectural study, not copied implementation; no licensing adoption decision is implied.
