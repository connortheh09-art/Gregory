# gmod_controller: Slice 1 (stop/release core), Slice 2 (Core's control decision) and the Lua drive/noclip spec

Status: revised candidate (R3) after Gordon's reviews. Those reviews found that fences and
evidence were not scoped to a controller run or actor (R1–R3), and that run ids from the wall
clock could not order a restart against a dead run's in-transit traffic (R4). Python only. It is not wired into `gmod_bridge.py`,
there is no Lua change, and no game behaviour is claimed. The fixtures model the game; they pin
semantics for the Lua work and the later live checks.

Slice 2 adds the typed `control` decision Gregory uses to move his own body. It is wired into
`gmod_bridge.py` only through the `DIRECT_CONTROL` seam, which stays `None` until the
one-writer integration builds the controller, so nothing is offered to the model or sent to
the game yet. A Lua draft accompanies it (`lua/greg_drive.lua`, its hooks in
`greg_bridge.lua`, and `tests/test_drive.lua`). It has **never been run**: the reviewer
container has no Lua runtime. `greg_direct` defaults to `0` in the draft, so nothing changes
until it is switched on.

## Controller runs

Every controller instance (one per bridge run) has an ordered id `ctl`, and both `drive` and
`wait` carry it.

- **Allocation.** The id is reserved by `gmod_controller.reserve_run()` from a durable counter
  (`greg/controller_run.json`, beside `cmd.writer.lock`), while holding that writer lock and
  before the controller is built. The counter only grows and never repeats, and it is written
  durably (fsync, atomic replace, directory fsync on POSIX) before the id is used. A successor
  therefore outranks every envelope a dead run created, including ones still in transit, no
  matter what the clocks did. Wall time plays no part.
- **Fail closed.** A missing counter is an error unless `initialize=True` (fresh install, or
  after the game's bridge Lua reloaded and its fence reset). A corrupt counter or a failed
  write is also an error. Failures before the replace leave the file untouched; a failure
  after it (directory fsync) leaves the counter advanced, which only skips an id. Never roll
  it back. These fixtures are Linux only: Windows crash and power-loss durability of the
  replace must be verified on the target before relying on it. Without a run id the controller
  refuses holds (`no_controller_run`). Stops still go out, but as plain releases that stop
  inputs and fence nothing. If the game reports our id before we sent anything
  (`controller_run_reused`), or a higher id (`controller_superseded`), the run retires and
  refuses every write. "Before we sent anything" is judged with publication state: each
  attempt carrying our id is counted outstanding *before* it reaches the publisher. Telemetry
  showing our id while an attempt is outstanding is held for judgment. If that attempt
  definitely never left (deferred/refused/failed) and nothing else was sent, it is reuse;
  if it may have left (published/accepted/ambiguous), it is our own envelope (review R5).
  Until then, evidence carrying our id is *staged*, not committed: no receipt shows
  `applied`/`acknowledged` while ownership is unresolved. Only the first sample proving each receipt is kept
  (bounded, never evicted by later samples); it is committed once an attempt may have left,
  or discarded when the run retires as reused (review R6, C1). Observed
  input clearance (`released`) is a direct world fact and is recorded as it is seen.
- **Fence.** The game's generation fence belongs to one run, and traffic from a retired (lower)
  run is ignored, delayed holds *and* delayed stops. A dead run can neither restart motion nor
  reset a newer run's fence. Generations are only compared within a run. The envelope `session`
  stays in the existing dedup key but takes no part in the fence, because uuids cannot be
  ordered.
- **Hosts.** The counter must live with the authoritative writer lock. Moving the bridge to
  another host means moving the counter file, or initializing after a Lua bridge reload.
  Otherwise the reuse check fails closed.

## Layers

- `deployments/oldpc/greg_controller_core.py`: game-agnostic. Intent, short lease renewal,
  generation fence, single writer, task/direct arbitration, receipts. No GMod knowledge, so a
  future `minecraft_controller` reuses it unchanged.
- `deployments/oldpc/gmod_controller.py`: the GMod adapter (the API Core sees). Validates drive
  decisions, encodes `drive`/`wait` envelopes, reads the Lua `drive` telemetry block, and
  adapts `write_cmd` publication results.
- `gregory_core/decision_contract.py`: the game-neutral control vocabulary
  (`CONTROL_MOVES/PACES/TURNS`, `control_intents`, `CONTROL_HINT`) offered to the model. A
  future adapter maps the same decision to its own inputs.
- Lua `drive` module (Gordon): applies holds in CreateMove, enforces the receiver rule, reports
  telemetry. Specified below.

## Slice 1 guarantees (Python, fixture-backed)

1. **The deadline is fixed.** Each model decision is a new generation with a deadline
   (default 10s, cap 30s). Renewals and telemetry never move it. Each lease sent is
   `min(lease, deadline - now)`, so a hold cannot outlive its intent by more than transit time.
2. **Latency is bridged.** Renewals every 0.5s with a 1.5s game lease keep motion continuous
   across ~5s model gaps and across about a second of writer back-pressure. A new decision
   retargets in place: no release, no stop-start.
3. **Stop always wins.** stop / disconnect / expiry / identity change / not actionable /
   stale telemetry all bump the generation *before* the release is built, clear the intent,
   and block route helpers. Every fixture, including a 4-thread hammer, asserts the fence:
   *no hold of generation ≤ S is published after a release of S.*
4. **In-flight work is ordered.** Holds are built only from the current intent, under the
   writer lock. A renewal already being written when stop arrives is linearized before the
   release, which is published right after it. A stop called from inside a publication (an
   observer callback) is published by the outer pass, with no deadlock or self-wait.
5. **Transport reordering is fenced game-side.** A publish-time check cannot retract an
   envelope already in transit, so Lua enforces the receiver rule below. The existing intake
   dedups by `session:seq` *equality*, not order (`greg_bridge.lua:534`, `greg_sv.lua:136`).
   The relay does reject older seqs (`greg_remote_game.py:107`), but the server-realm path and
   future transports need the fence regardless.
6. **One writer.** All mailbox writes go through one lock: holds/releases, `publish_task`
   (refused while a direct intent holds control, and after a stop until Core calls
   `allow_tasks()`), and `publish_other` (refuses movement verbs: drive/move/navigate/key/
   look/gaze/wait and `console noclip`). A direct intent preempts a task via
   `on_task_preempted`.
7. **Evidence is bound.** A hold receipt records the actor/world identity
   (steamid, bridgeSession, controlEpoch, map) it was decided for, and a release records the
   identity it was requested in. `applied` and `acknowledged` need telemetry with that exact
   identity *and* `drive.ctl` equal to this run. `released` needs that identity and a newer
   sample. A different actor, epoch or map can invalidate control (the intent is released), but
   it is never evidence for the old receipt. If the world changes while a release is still being
   retried, that receipt is marked `unconfirmed`, and a fresh release (new generation) fences
   the new world.
8. **Receipts stay honest.** Publication outcomes are `published` (file replaced, or relay ACK
   `file_published`+SHA, which the relay returns only after replacing cmd.json,
   `greg_remote_game.py:116`), `accepted`, `ambiguous`, `deferred`, `refused` and `failed`.
   Only telemetry sets `applied` (hold generation active), `acknowledged` (game `stopGen ≥ S`)
   or `released` (newer sample, nothing held). Releases are retried every 0.5s until both are
   true, or marked `unconfirmed` after 3s. They are reopened if the game later reports an old
   generation still held. A missing or malformed drive block is never evidence.

All numbers are proposals to validate live, not locked settings (`LeasePolicy`). If Python
dies mid-hold, Gregory keeps moving at most one lease (≤1.5s, plus one 0.25s mailbox poll).

## Slice 2: Core's control decision

Gregory moves by choosing a typed `control` intent in the same constrained decision that
carries his reply. No task is needed.

```json
{"action": "control", "command": "drive", "move": "forward", "pace": "walk", "look": "P1",
 "jump": "none", "crouch": false, "use": false, "fly": "on", "vertical": "up", "seconds": 5}
{"action": "control", "command": "stop"}
```
- **Contract** (`decision_contract.control_intents`). Required: `action`, `command`, `move`,
  `seconds`. Optional: `pace` (default walk), `look` (absent keeps the view), `jump`,
  `crouch`, `use`, and `fly`/`vertical`, which exist only when the offer includes flight.
  `move` is none/forward/back/left/right or a diagonal (`forward_left`, ...), relative to the
  view. `pace` is sneak/walk/jog/run. `look` is one of this turn's `P#`/`D#` labels (only rows
  shown in the prompt) or turn_left/turn_right/turn_around/slight_left/slight_right/up/down/level.
  `seconds` is 1..the offer's `max_seconds` (at most 30). `decode` maps `P#` to
  `{"player": alias}` and `D#` to `{"destination": token}`, with no fuzzy match or raw ids.
- **When it is offered.** On owner turns only, and only when the adapter's offer is in the
  rendered turn context. `CONTROL_HINT` renders exactly when the schema offers control. Under
  prompt-budget pressure the offer is evicted last, just before the turn would fail, and the
  schema then stops offering control. A screen follow-up keeps a control proposal in trusted
  game scope, as it does tasks.
- **Offer** (`GModControl.offer(state)` → `CoreGameAuthority.offer(..., control=)` →
  `activity_options.control`): `{mode, active, seconds_left, max_seconds, fly?}`. It is absent
  whenever the controller would refuse a decision: no run id, retired, stale or non-actionable
  telemetry, or no `drive` capability (old Lua). `fly: ["on", "off"]` is offered in walk or
  noclip mode unless this world refused noclip (`drive.noclip.state == "refused"`).
- **Mapping** (`gmod_controller.translate`, at publication). pace → `speed` .25/.5/.75/1.0 of
  run speed. move → `forward`/`right` ±1, diagonals normalized. turn_* → absolute `yaw` =
  heading at publication +90/−90/180/+30/−30; up/down/level → `pitch` −45/45/0. `P#` →
  `look_steamid` (the player must be offered *and* present now, via `GameTasks.people`) with an
  80 u stand-off. `D#` → `look_point`, the offered destination's position, with a 40 u
  stand-off. fly on/off → `mode` noclip/walk. vertical → `up` ±1 only if flying after this
  decision; otherwise it is listed in `ignored`. jump/crouch/use pass through.
- **Publication** (`gmod_bridge.apply_control`, once per decision). It needs a current voice
  delivery stamp (as tasks do), an owner turn, `DIRECT_CONTROL`, and for a drive the offer in
  the decision's options and a view binding that matches the live world. A stop is never
  refused for staleness.
  - *Accepted* drive: the current game task is invalidated and PlayerCore's goal ends
    (`core_direct_control`). An accepted stop ends direct control only and lets route helpers
    write again; a task keeps going. Ending a task is the deliberate task `cancel`. The authority notes `control` with
    `qualification: requested_not_confirmed`. Game evidence still comes only from telemetry.
  - *Refused*: nothing changes, the spoken line is replaced, and the authority notes
    `control_refused`. It is not a task refusal, so it starts no recovery turns.
  - *The latest decision wins.* An accepted new task, or a tour/explore/rest activity, calls
    `yield_to_task()`: a held drive is stopped (`task_selected`) and route helpers may write
    again (`allow_tasks`). Continuing a task does not.

## Wire contract

Hold, envelope `mode: "direct"`:
```json
{"action": "drive", "v": 1, "ctl": 1762919400123, "gen": 12, "lease": 1.5,
 "move": {"forward": 1.0, "right": 0.0, "up": 0.0, "speed": 1.0},
 "look": {"yaw": 90.0, "pitch": 0.0, "rate": 180.0},
 "jump": "tap", "crouch": false, "mode": "walk"}
```
- `move.forward/right` are -1..1 relative to the view, with diagonals normalized. `up` is -1..1
  and only acts in noclip. `speed` is 0..1 of `lp:GetRunSpeed()`; the default is 0.5 (normal
  walk at stock speeds).
- `look` is optional. It gives an absolute yaw (0..360) and/or pitch (-89..89) target, with
  `rate` 30..720 °/s. If it's absent, drive does not touch the view.
- Instead of yaw/pitch, `look` may track a target (Slice 2):
  `{"steamid": "STEAM_0:1:1000", "rate": 180.0, "near": 80.0}` or
  `{"point": [x, y, z], "rate": 180.0, "near": 40.0}`. `near` is optional (0..512 u).
- `jump`: `none`/`tap`/`hold`. `crouch` is a bool. `mode` is optional: `walk`/`noclip`.
  `use: true` appears only when set. Slice 1 envelopes are unchanged byte for byte.
- Every renewal re-sends the complete intent, so any single envelope fully describes the hold.

Release, envelope `mode: "stop"` (TickWriter lets it preempt cadence):
```json
{"action": "wait", "ctl": 1762919400123, "driveGen": 13, "reason": "stop"}
```
Old Lua ignores `ctl`/`driveGen` and still releases everything. New Lua also raises the fence of
that run (and ignores the stop entirely if the run is retired).

## Receiver rule (normative)

This runs after the existing intake checks (identity, epoch, expiry, `session:seq` dedup). The
Python model in `tests/test_gmod_controller.py` is an executable copy. The Lua fixture should
run the same vectors in `tests/gmod_drive_receiver_cases.json`.
```lua
-- D = {ctl=0, floor=0, stopGen=0, gen=0, active=false}   (reset only when the Lua bridge reloads)
-- isId(x): type(x)=="number" and x==math.floor(x) and x>=1 and x<2^53
-- newRun(c): if c > D.ctl then release("new_run") D.ctl, D.floor, D.stopGen, D.gen = c, 0, 0, 0 end
if a.action == "wait" and a.ctl == nil then release("legacy_stop")   -- existing wait: no fence
elseif a.action == "wait" or a.action == "drive" then
    if not isId(a.ctl) then reject("invalid_controller")
    elseif a.ctl < D.ctl then reject("retired_controller")             -- no effect at all
    elseif a.action == "wait" then                                       -- existing wait behaviour, plus:
        newRun(a.ctl) release("stop")
        if isId(a.driveGen) then D.stopGen = math.max(D.stopGen, a.driveGen) end
    elseif not isId(a.gen) then reject("invalid_generation")
    elseif not (positive finite a.lease) then reject("invalid_lease")
    else
        newRun(a.ctl)                                                    -- only after full validation
        if a.gen <= D.stopGen then reject("released_generation")
        elseif a.gen < D.floor then reject("stale_generation")
        else
            D.floor, D.gen = a.gen, a.gen
            D.expires = SysTime() + math.Clamp(a.lease, .1, 2)
            apply(a)   -- same gen: refresh in place; newer gen: retarget smoothly, never release between
        end
    end
end
```
A legacy `wait` without `ctl` releases but does not fence (pinned by a vector). Once integrated,
every stop goes through the controller, so this only covers stray legacy writes. Vectors cover
the review case (old-run hold → newer-run stop → delayed old-run hold = `retired_controller`),
a legitimate restart, a retired run's stop, and malformed ids.

## Lua application (CreateMove)

- **Module and gating.** Put drive in its own module (`greg_drive.lua`) with its own step. Gate
  it on `active(lp)`, not in a vehicle, and a client convar `greg_direct` (kill switch; Connor
  picks the default). Do **not** gate it on `greg_playercore`, which is the route helper.
  Order inside CreateMove: interlocks → `drive.step` while active → otherwise rescue →
  locomotion. Accepting a new generation calls `locomotion.cancel("direct")` and
  `rescue.abort`.
- **Analog speed.** `target = speed * lp:GetRunSpeed()`. Add `IN_SPEED` only when
  `target > lp:GetWalkSpeed()`. Never use `IN_WALK`, because it caps speed and analog
  forwardmove already gives slow speeds. Ramp toward the target (proposed +600 u/s², matching
  `greg_locomotion.lua:95`, and −900 u/s²). Rotate the wish direction at ≤360 °/s so changes
  curve instead of snapping. Set `cmd:SetForwardMove/SetSideMove` from the ramped vector, as
  `greg_locomotion.lua:185`. Clear only the buttons drive owns.
- **Look.** Rate-limited toward the target, the same technique as `steer`
  (`greg_locomotion.lua:62`): `cmd:SetViewAngles` plus `lp:SetEyeAngles`.
- **Tracked look.** `steamid`: find the player every command and aim at `EyePos()`, rate-limited
  like a yaw/pitch target. If the player is missing or invalid, keep the view and report
  `reject={gen, reason="look_target_missing"}` once. `point`: aim at the point. Within 16 u
  horizontally of the target, stop updating yaw so he doesn't spin in place.
- **Stand-off.** With a tracked look and `near > 0`, while the horizontal distance to the
  target is at most `near`, drop positive forward motion. Strafing and backing away still apply,
  so `forward_left` around a player circles them. `held` then omits `forward`.
- **Use.** `use: true` presses `IN_USE` for exactly one command after a new generation is
  accepted, like a jump tap. Renewals never press again.
- **Jump.** `tap` presses `IN_JUMP` for exactly one command on the first grounded CreateMove
  after a *new* generation is accepted. Renewals never re-tap. If he isn't grounded within
  0.5s, report `missed`. `hold` keeps him jumping. The draft re-presses `IN_JUMP` on each landing, because Source's
  movement ignores a jump button still held from the previous command (VERIFY live).
  `crouch` holds `IN_DUCK`.
- **Clearance.** Unlike legacy `move`, drive neither refuses on short clearance nor releases on
  a probe. It reports `blocked` (wishing to move, actual speed < 20% of target for >0.5s) and
  leaves the decision to the decision layer.
- **Releases.** All of these clear drive buttons on the next command and set `active=false`:
  lease expiry, `wait`, session change, `navigate`/`move`/`key`, `greg_direct=0`, and every
  existing interlock (inactive/dead/menu/vehicle, `greg_enable` change, `controlEpoch` or map
  change, ShutDown). Simplest: make `releaseKey()` (`greg_bridge.lua:271`) also release drive.

## Noclip (typed)

- **Request.** Request it through the hold's `mode`. It's fenced like any drive field. When a
  new generation's mode differs from the current move type: `rescue.abort`, then exactly one
  `RunConsoleCommand("noclip")` for that generation (never on renewal). Watch `GetMoveType()`
  for 1.0s and report `active`/`off`, or `refused` if unchanged (the server or gamemode
  denied it). No `SetMoveType` and no permission changes, the same rule as
  `greg_rescue.lua:1`. The `sbox_noclip` convar may be reported as a hint; the truth is the
  observed move type.
- **Flight.** forward/right follow the full view including pitch (engine behaviour). `up` maps
  to `cmd:SetUpMove`. jump/crouch are ignored in flight and reported as ignored. Verify live:
  that upmove acts in GMod noclip, and how `IN_SPEED` scales noclip speed.
- **Rescue.** Rescue must not toggle noclip while drive owns it.
- **Stop.** Stop releases inputs but does **not** exit noclip, so a stop mid-air doesn't drop
  him. Exiting is an explicit `mode: "walk"`. This is open decision 3.

## Telemetry

Advertise `capabilities.drive = 1` and add `state.drive`:
```lua
drive = { v=1, ctl=int, active=bool, gen=int, stopGen=int, held={"forward","speed",...},
          lease=<s left>, speed=<GetVelocity():Length2D()>, vspeed=<z velocity>,
          mode="walk"|"noclip"|"other", blocked=bool, jump="none"|"pending"|"done"|"missed",
          noclip={want=..., state="idle"|"pending"|"active"|"off"|"refused", gen=int},
          reject={gen=..., reason=...}, lastEnd="lease_expired"|"stop"|"interlock"|... }
```
Python requires `v, ctl, active, gen, stopGen, held` (an empty `held` may arrive as `{}`).
`ctl/gen/stopGen` describe the fence of the run that currently owns it. `held`
is the set of buttons drive asserted on the last command. The rest feeds Slice 3. Python
refuses drive intents (`drive_unsupported`) until the capability appears, so old Lua is never
sent a verb it would silently ignore.

## Integration seam (next, not done here)

- **Run id.** Inside the existing `with command_writer_lock(...)` block (`gmod_bridge.py`
  main), call `reserve_run(directory/'controller_run.json')` once. On any exception, log it and
  pass `run_id=None` (fail closed). Initialization is an explicit operator choice, never
  automatic.
- **Construction.** Build one `DirectController` per bridge run, after TickWriter:
  `bridge_publisher(write_cmd, cmd_path, next_seq, lambda: latest, session, chain=lambda: _COMMAND_OBSERVER)`.
  `next_seq` must share the bridge's `seq` counter. `write_cmd`'s `observer=` *replaces* the
  recorder observer (`gmod_bridge.py:1048`), which is why `chain` exists.
- **Main loop.** Call `observe(latest)` after each state read. Call `tick()` at ≥4 Hz; check
  the main-loop rate, or run tick on its own thread (the controller is thread-safe).
- **One writer.** Every `write_cmd` call site must go through the controller: stops →
  `stop(reason)`, routes → `publish_task`, speech and the rest → `publish_other`, and
  `shutdown_bridge`'s stop → `disconnect('bridge_shutdown')`. Until then there are two
  writers, and the fence protects drive holds only.
- **Duplicate stops.** TickWriter replays a deferred stop on the next tick
  (`greg_supervised.py:110`), so `bridge_publisher` reports a held-back stop as `ambiguous`,
  not `deferred`. The controller also retries. Duplicate stops are harmless; the relay may
  reject the older replayed seq.

- **Control seam (Slice 2).** With the controller built, set the module global
  `DIRECT_CONTROL = GModControl(controller, people=game_tasks.people)` (declare it `global`
  in `_run_bridge`). Only do this together with the one-writer routing above. Until every
  write site goes through the controller, autonomous and route writes overwrite holds, and a
  legacy `wait` releases a hold until the next renewal. Control needs Core game tasks
  (`game_tasks`), because its labels and world binding ride the task view.

## Open decisions

1. Values: renew 0.5s, lease 1.5s, default intent 10s / max 30s, stop retry 0.5s, release
   timeout 3s, telemetry timeout 3s, ramps ±600/900 u/s².
2. `greg_direct` default.
3. Stop keeps noclip, or exits it.
4. After a stop, tasks stay blocked until Core calls `allow_tasks()` (Slice 4 decides
   resumption).
5. Default `speed` 0.5 when a decision gives none. Slice 2 names gaits: sneak/walk/jog/run
   = .25/.5/.75/1.0.
6. Control on internal (game-attention) turns: off for now.
7. Slice 2 values: stand-off 80 u (player) / 40 u (place), pitch ±45°, slight turn 30°.
8. Prompt budget. Core caps a turn prompt at 6000 chars. The control hint plus offer cost
   about 615 chars, which comes out of recent dialogue first. On the worst-case fixture view
   (8 destinations) very little dialogue is left. Options: trim `GameTasks.instruction`, or
   show fewer destinations when control is offered.
9. Decided (Connor): a control stop does not end the current task; "cancel your task" is the
   task `cancel`.

## Running the fixtures

`python -m unittest discover -s tests -p "test_gmod_contro*.py"` from the repo root runs both
`test_gmod_controller.py` (Slice 1) and `test_gmod_control_contract.py` (Slice 2). The tests
add the repo root and `deployments/oldpc` to the path, like `test_player_game_tasks.py`.
