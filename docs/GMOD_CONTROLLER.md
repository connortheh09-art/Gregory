# gmod_controller: Slice 1 (stop/release core) and the Lua drive/noclip spec

Status: revised candidate (R3) after Gordon's reviews. Those reviews found that fences and
evidence were not scoped to a controller run or actor (R1–R3), and that run ids from the wall
clock could not order a restart against a dead run's in-transit traffic (R4). Python only. It is not wired into `gmod_bridge.py`,
there is no Lua change, and no game behaviour is claimed. The fixtures model the game; they pin
semantics for the Lua work and the later live checks.

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
  `applied`/`acknowledged` while ownership is unresolved. It is committed in order once an
  attempt may have left, or discarded when the run retires as reused (review R6). Observed
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
- `jump`: `none`/`tap`/`hold`. `crouch` is a bool. `mode` is optional: `walk`/`noclip`.
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
- **Jump.** `tap` presses `IN_JUMP` for exactly one command on the first grounded CreateMove
  after a *new* generation is accepted. Renewals never re-tap. If he isn't grounded within
  0.5s, report `missed`. `hold` keeps `IN_JUMP` down while active (the game decides re-jumps).
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

## Open decisions

1. Values: renew 0.5s, lease 1.5s, default intent 10s / max 30s, stop retry 0.5s, release
   timeout 3s, telemetry timeout 3s, ramps ±600/900 u/s².
2. `greg_direct` default.
3. Stop keeps noclip, or exits it.
4. After a stop, tasks stay blocked until Core calls `allow_tasks()` (Slice 4 decides
   resumption).
5. Default `speed` 0.5 when a decision gives none (Slice 2 will name gaits for the model).

## Running the fixtures

`python -m unittest discover -s tests -p test_gmod_controller.py` from the repo root. The tests
add the repo root and `deployments/oldpc` to the path, like `test_player_game_tasks.py`.
