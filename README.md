# Gregory — Garry's Mod bot

An LLM-driven player that actually plays Garry's Mod: a Python bridge talks to a Lua addon inside
the game, and a local model decides what to do. No cheats, no engine hacks — just the same inputs a
human has (movement, view angles, +use, tool gun) plus the state the game exposes.

## Architecture

```
┌──────────────┐   HTTP/JSON    ┌──────────────┐   model calls   ┌───────────────┐
│  gmod_bridge │ ─────────────► │ greg_bridge  │ ──────────────► │  LM Studio    │
│  (Python)    │ ◄───────────── │   (.lua)     │ ◄────────────── │  (local LLM)  │
└──────────────┘   state/acts   └──────────────┘                 └───────────────┘
```

- **`gmod_bridge.py`** — the body. Owns the control loop, talks to the game, talks to the model.
- **`greg_bridge.lua`** — the hands. Runs inside GMod, exposes state and executes actions.
- **Model** — runs on the 5080 via LM Studio over the tailnet. Swap-friendly.

Design rule: **one boss.** The text brain drives the body. Vision is an on-demand second opinion,
never the spine.

## Status

Early / experimental. Working: movement, look-at, prop spawning, weapons, respawn, map loading.
Next: fatten the state feed, real goal memory, reflex/brain split. See [`docs/PLAN.md`](docs/PLAN.md).

## Layout (planned)

```
bridge/      gmod_bridge.py, controllers
lua/         greg_bridge.lua and addon files
docs/        plan, architecture notes
tools/       helper scripts (start/stop, QA)
```

## Notes

- Nothing in here should contain tokens, keys, or machine-specific credentials. `.gitignore` covers
  the usual suspects; scrub before committing.
- GMod leaks RAM over long sessions — the bridge is expected to run with a periodic restart.
