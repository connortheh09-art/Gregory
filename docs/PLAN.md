# GMod Bot — Model-Mesh Plan (written 2026-10-19)

> Standalone recap so this survives a session reset. Source: `memory/2026-10-18.md` + 2026-10-19 session.
> Bot in question = **Gregory** (the in-game GMod player), driven by `gmod_bridge.py` + `greg_bridge.lua`.

## Goal
Make the GMod bot smarter by (a) **splitting its brains across two machines** (model mesh) and
(b) **fattening its state feed** — the feed, not the model, is the main reason it feels dumb.

## Current state
- Brain: `qwen/qwen3-vl-8b` on the **5080** (LM Studio, ctx 8192, parallel 1).
- Bridge: `gmod_bridge.py` + `greg_bridge.lua` (HTTP → LM Studio over tailnet).
- Game has **always** run on the **old PC** (`KELLENWORKSPACE`), with Gregory's bridge and Lua. It was never
  on the 5080, and there is no "move the game" step. The **5080** is the model host.

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
- `qwen_2b_vlm_gguf` — **NOT a VLM.** Rejects images outright: "does not support image inputs". Name lies; dropped.
- `google/gemma-4-e4b` — poor: 13.7s, burned all 300 tokens thinking, empty `content`.
- `google/gemma-4-12b-qat` — **works**, see results below.

## Blockers / to-do
- Old PC's LM Studio **401s** (Require API key ON) → disable in Developer → Server.
- GMod **leaks ~16 GB RAM** after a few days → needs a periodic self-restart (every N hours).
- `gm_ollama` (Rust module) = Lua bindings to Ollama (in-engine, async only). We already do the same over HTTP via `gmod_bridge.py`.

## POV / vision take
**Crutch, not a spine** — text-first brain, VL as an on-demand second opinion.

## Today (2026-10-19)
- Memory search restored (OpenAI `text-embedding-3-small`); Gordon now walled to an embedding-only key.
- Next: start the recon — old-PC LM Studio reachability · Gemma mmproj check · stub the `events.jsonl` / `world.json` bridge.

## Vision A/B results (2026-10-19, warm)

Same 320x200 test image (red bg, blue rect left, yellow rect right), one-sentence answer.

| model | box | thinking on | thinking off | reasoning tokens | completion tokens |
|---|---|---|---|---|---|
| `google/gemma-4-12b-qat` | 5080 (7.15 GB, local) | 3.4s | **0.6s** | 249 → **0** | 277 → 24 |
| `qwen/qwen3-vl-8b` | old PC (6.19 GB, LM Link) | 12.3s cold / **0.9s warm** | n/a (never thinks) | 0 | 21 |

**Both answered correctly.** Latency is dominated by thinking, not by the model or the box.

### Toggling thinking — what actually works
- ✅ **`reasoning_effort: "none"`** — 0 reasoning tokens, no template surgery, survives model swaps.
- ❌ `chat_template_kwargs: {enable_thinking: false}` — silently ignored.
- ❌ `think: false` — silently ignored.
- ⚠️ `/no_think` prompt suffix — partial only (249 → 156 reasoning tokens).
- 🔧 Editing the Jinja prompt template (`{%- set enable_thinking = false %}`) works but is per-model manual
  surgery; keep as fallback for clients that cannot send `reasoning_effort`.

### Operational notes
- LM Studio **LM Link** pools models across both boxes: both `/v1/models` endpoints return the same 19 ids.
  The endpoint does **not** tell you which box ran inference — check the device badge in the LM Studio UI.
- **"Only keep last JIT loaded model" is ON** → switching models evicts the other; every swap pays a reload
  (gemma read 6.7s instead of 0.6s on a swap-retest). Pin one glance model.

### Open question
Both models passed a trivial synthetic image. The real test is actual GMod frames from the old PC —
only that answers whether 12B buys anything over the 8B already running there.
