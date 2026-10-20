# Curb traversal repair — 2026-10-20

Connor's 28.45-second clip shows repeated stalls at a low road/sidewalk boundary, head pointed down, followed by retracing. Live pre-change telemetry independently reported `waiting_obstacle` and pitch 73 degrees. The controller stopped on every low horizontal hull hit, including stepable curbs, and explicitly aimed below eye height at the hit point. Python treats a subsequent blocked route as a failed edge and replans, explaining a mechanism for detours (not proof every observed turn was a replan).

## Changes

- Use the actual player hull. Before rejecting a short obstacle, test vertical headroom, raised forward clearance and supported ground within the player's step height (capped at 18 units). Let Source's normal movement perform the step; no teleport/noclip.
- At an impassable obstacle, preserve the travel camera pitch limits instead of staring at the collision point.
- Sprint on clear, supported stretches sufficiently far from the next waypoint; preserve explicit walk requests.
- Attempt a jump only for a short world obstacle with a clear raised corridor and supported landing, with a cooldown; never jump doors, players, missing ground or blocked headroom. This does not introduce navmesh jump links, canal crossing or arbitrary gap jumps.
- Expose controller version and traversal mode in existing telemetry.

## Offline verification

`tests/test_locomotion.lua` runs the actual module with stubbed player/input/traces. Nine scenarios exercise curbs, hurdles, walls, ceilings, unsupported landings, running, walk mode and drops. Run with a stock Lua runtime from repository root, or Python `lupa` (isolated dependency, not a game requirement). Existing 21 Python regressions also pass. These controlled traces are not a substitute for live physics acceptance.

## Deployment

Original live Lua SHA256 matched repository baseline. Backup on KELLENWORKSPACE: `C:\Users\lesle\openclaw\backups\gordon-before-curb-v1\greg_locomotion.lua`. Only the locomotion module is replaced. Gemma/Qwen configuration, main branch, navmesh and gateway remain unchanged. Client reload and live outcome must be independently verified via `locomotion.version`, not inferred from file installation or console input delivery.

At this checkpoint the file is installed but the old client session is still running (no `curb-v1` telemetry). Automated UI input did not establish a reload; its temporary workers were stopped. Connor was asked to enter `exec greg_nav_reload` on the agent client's console and close it. No restart/reconnect or gateway/config changes were made. Live after-fix obstacle, sprint and jump behavior remains **unverified**.
