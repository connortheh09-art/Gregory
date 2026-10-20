# Old-PC memory deployment and model integration — 2026-10-20

## Owner decision and deployment

Connor authorized deployment of the memory branch and reaffirmed Gemma-4-12B-QAT
as the main thinker. Qwen3-VL 8B is an optional old-PC appearance sensor, not the
action policy. No Lua, gateway, model weights, or repository main-branch changes.

The connected KELLENWORKSPACE node was discovered and commands ran as `lesle`.
GMod was already running on `gm_bigcity_improved_rp`; no Python collector was
running. All eight installed source hashes matched the imported manifest before
the `beef941` bundle was installed. Backups beneath `openclaw/backups/`:

- `gordon-before-beef941`: original Python, launcher, chat/player memory.
- `gordon-before-pairing`: memory-patch source before model integration.
- `gordon-before-reasoning-off`: integration source and launcher before off/vision.

Archive/installed hashes, Python compilation, CLI, and 15 memory regressions
passed on the old PC. The later integration bundle passes **21** regressions
there, including request defaults, budget bounds, and reversible reasoning-off.
Original `SOURCE-MANIFEST.json` remains provenance, not the new deployment hash set.

## Integration fixes and explicit configuration

Gemma's private reasoning consumes `max_tokens`. The original 32-token goal
request returned HTTP 200 with empty final content and `finish_reason=length`.
With a 1024-token floor it returned a goal; actual action/agenda requests also
returned usable parsed results. Additions preserve defaults unless selected:

```text
--model google/gemma-4-12b-qat
--model-min-tokens 1024
--model-timeout 30
--model-reasoning off
--vision-helper C:\Users\lesle\openclaw\greg_vision_helper.py
```

`greg_model.py` applies settings to goal, action, agenda, and social requests.
`default` reasoning restores server behavior without sending a reasoning override.
For this LM Studio endpoint `off` maps to `reasoning_effort=none`, verified with
zero reported reasoning tokens. Ordinary state-dependent action replies retain
the 10-second age limit. Semantic agenda choices may use the configured request
timeout; existing context checks and `Agenda.accept` revalidate session/map/epoch
and live catalog IDs, with navigation planned from current state. Result logs
now include inference kind, latency, validity, and context match.

The appearance helper accepts the collector's one-shot JSON protocol, captures
only a foreground GMod client area, and requests a short local Qwen caption.
It does not fall back to capturing a generic desktop, issue actions, or change
the main thinker. Timestamp is capture time, not response time; timeout and
10-second freshness checks remain. Install optional `requirements-vision.txt`.
Windows helpers launch without a console so they do not steal game focus.

## Measured checks, not general intelligence claims

Same-state, two-case A/B (one sample per setting/case):

- Goal request: default 7.62 s; off 0.42 s. Both returned usable goal text.
- Stop/wait request: default 3.81 s; off 0.69 s. Both parsed as wait plus dialogue.
- Off reported zero reasoning tokens in both cases. This does not establish
  equivalent quality on complex tasks or a general benchmark win.

A bounded Gemma-only gameplay run produced a HOTEL landmark goal. The accepted
route retained one goal/route ID while telemetry positions changed from
`(-2834,-404,-11140)` to `(-732,1251,-11144)`, approximately 2675 units of net
displacement over 23 seconds, with advancing Lua waypoint cursors. The final
sample was `waiting_obstacle`, roughly 847 units from the target: **not arrival
or complete navigation acceptance**. Two 30-command tests intentionally ended;
they are not evidence of two hours of continuous movement.

Foreground game capture passed at 768x432. A real Qwen appearance caption reached
the collector helper in 6.16 s (capture age 5.76 s), inside the freshness bound.
No sustained vision reliability or spontaneous inspection frequency is claimed.
The complete one-shot game capture → Qwen caption → Gemma response also passed:
caption age entering Gemma 5.56 s, age at response 6.55 s, total 6.88 s. Gemma
described the caption's cracked pavement/asphalt and returned a parsed wait action.
This was a read-only model-pipeline test, not a claim of vision-driven navigation.

## Runtime operation and remaining acceptance

The existing `collector_pc_launch.py` was backed up and updated to explicitly
select remote Gemma, reasoning off, the budget flags, and on-demand local vision.
Its established actor/map/campaign are retained; output is now
`collector_gemma_live.log`. Use the single-writer handoff; do not run a second
collector beside it. Recheck processes and latest telemetry after reset.
One persistent collector was verified running with these flags after the bounded
tests; this deployment does not create an automatic Windows startup task.

Remaining: longer obstacle recovery and destination arrival, chat-driven vision
in actual play, map transitions, and controlled live memory recall after a
completed/failed goal and restart. Offline restart regressions are not substitutes
for those checks. Detailed traces stay on the node, not in spoken game chat.
