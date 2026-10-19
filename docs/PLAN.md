# GMod Bot — Model-Mesh Plan (written 2026-10-19)

> Standalone recap so this survives a session reset. Source: `memory/2026-10-18.md` + 2026-10-19 session.
> Bot in question = **Gregory** (the in-game GMod player), driven by `gmod_bridge.py` + `greg_bridge.lua`.

## Goal
Make the GMod bot smarter by (a) **splitting its brains across two machines** (model mesh) and
(b) **fattening its state feed** — the feed, not the model, is the main reason it feels dumb.

## Current state
- Brain: `qwen/qwen3-vl-8b` on the **5080** (LM Studio, ctx 8192, parallel 1).
- Bridge: `gmod_bridge.py` + `greg_bridge.lua` (HTTP → LM Studio over tailnet).
- Game currently lives on the **5080** (main rig `CONNORSCOMPUTER`); the **old PC** (`KELLENWORKSPACE`) is its eventual home.

## The split (the actual idea)
- **Old PC** = runs the game + a small **VISION** model (glance only — ships back ONE sentence).
- **5080** = the real **TEXT** brain (fast ticks, full 16 GB).
- Why: **data locality**. Frames are heavy → vision sits next to the game. Text snapshots are tiny → the control loop hops to the 5080.
- **One boss:** the text brain drives the body; the vision brain only answers "what am I looking at?".

## Agreed order of operations
1. **Fatten the state feed** (bridge sees too little).
2. **Real goal memory.**
3. **Then** shop models. (A bigger brain on a thin feed = fancier wrong answers.)

## Memory-bridge design (Greg's rec)
- Append-only `events.jsonl` + periodically rebuilt `world.json` snapshot.
- **Only the bridge writes** (concurrency is the real risk, not the file).
- Snapshot tiny/dumb: where am I · current goal · what's nearby · last N events.
- Build it INTO the existing `gmod_bridge.py`, **not** a new script.

## Candidate glance models (already on the 5080's disk)
- `qwen_2b_vlm_gguf`, `google/gemma-4-e4b`, `gemma-4-12B-it-QAT` (12B, tops game-control leaderboards per Connor).
- **A/B test first:** confirm Gemma's GGUF ships an **mmproj** (vision), compare tok/s + decisions.

## Blockers / to-do
- Old PC's LM Studio **401s** (Require API key ON) → disable in Developer → Server.
- **Step zero of the split:** move the game from the 5080 → old PC.
- GMod **leaks ~16 GB RAM** after a few days → needs a periodic self-restart (every N hours).
- `gm_ollama` (Rust module) = Lua bindings to Ollama (in-engine, async only). We already do the same over HTTP via `gmod_bridge.py`.

## POV / vision take
**Crutch, not a spine** — text-first brain, VL as an on-demand second opinion.

## Today (2026-10-19)
- Memory search restored (OpenAI `text-embedding-3-small`); Gordon now walled to an embedding-only key.
- Next: start the recon — old-PC LM Studio reachability · Gemma mmproj check · stub the `events.jsonl` / `world.json` bridge.
