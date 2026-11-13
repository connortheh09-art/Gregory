-- Direct control: the fenced `drive` hold and its release (docs/GMOD_CONTROLLER.md).
-- Installed as garrysmod/lua/greg_drive.lua; loaded only by the client bridge.
-- No file I/O or model calls. DRAFT (Grady, Slice 2): never run in GMod yet; values and
-- engine behaviour marked VERIFY need a live check.
local M = {}
local VERSION = 1
local RX = { ctl = 0, floor = 0, stopGen = 0, gen = 0, shot = 0 } -- fence of the owning run
local H = nil                     -- the applied hold, nil when released
local held, lastEnd, reject = {}, "none", nil
local noclip = { state = "idle", gen = 0 }
local motion, prevMotion = nil, nil -- per-generation motion log (Slice 3), in game units
local atan2 = math.atan2 or math.atan -- LuaJIT/5.1 and 5.3+

local function finite(x) return type(x) == "number" and x == x and math.abs(x) < math.huge end
local function isGen(v) return finite(v) and v >= 1 and v < 2 ^ 53 and math.floor(v) == v end
local function clamp(x, a, b) return math.max(a, math.min(b, x)) end
local function num(v, lo, hi, default) if finite(v) then return clamp(v, lo, hi) end return default end
local function planar(p, q) return math.sqrt((p.x - q.x) ^ 2 + (p.y - q.y) ^ 2) end
local function r1(x) return math.floor(x * 10 + .5) / 10 end

-- One record per accepted generation. A jump still in the air carries over to the next one,
-- so its landing is not lost to a mid-move change.
local function beginMotion(g, now, lp)
    if not (lp and IsValid(lp)) then return end
    local carry = nil
    if motion then
        motion.open, carry, motion.takeoff = false, motion.takeoff, nil
        prevMotion = motion
    end
    local pos = lp:GetPos()
    motion = { gen = g, ctl = RX.ctl, t0 = now, t = 0, start = pos, last = pos, path = 0, peak = 0, low = 0,
               ground = lp:OnGround(), air = {}, phases = 0, drop = 0, open = true, takeoff = carry }
end

local function parse(a)
    local m = type(a.move) == "table" and a.move or {}
    local p = { forward = num(m.forward, -1, 1, 0), right = num(m.right, -1, 1, 0), up = num(m.up, -1, 1, 0),
                speed = num(m.speed, 0, 1, .5), crouch = a.crouch == true, use = a.use == true,
                jump = (a.jump == "tap" or a.jump == "hold") and a.jump or "none",
                mode = (a.mode == "walk" or a.mode == "noclip") and a.mode or nil }
    local n = math.sqrt(p.forward ^ 2 + p.right ^ 2)
    if n > 1 then p.forward, p.right = p.forward / n, p.right / n end
    local l = a.look
    if type(l) == "table" then
        local look = { rate = num(l.rate, 30, 720, 180), near = num(l.near, 0, 512, 0) }
        local pt = l.point
        if type(l.steamid) == "string" and #l.steamid <= 32 then
            look.steamid = l.steamid
        elseif type(pt) == "table" and finite(pt[1]) and finite(pt[2]) and finite(pt[3]) then
            look.point = Vector(pt[1], pt[2], pt[3])
        else
            look.yaw = finite(l.yaw) and l.yaw % 360 or nil
            look.pitch = finite(l.pitch) and clamp(l.pitch, -89, 89) or nil
        end
        if look.steamid or look.point or look.yaw or look.pitch then p.look = look end
    end
    return p
end

function M.release(reason)
    if H then lastEnd = reason or "stop" end
    H, held = nil, {}
end

-- A newer controller run releases the old hold and starts a fresh fence.
local function newRun(ctl)
    if ctl > RX.ctl then
        M.release("superseded")
        RX = { ctl = ctl, floor = 0, stopGen = 0, gen = 0, shot = 0 }
    end
end

-- The receiver rule (normative; tests/gmod_drive_receiver_cases.json). Returns the outcome
-- and, for "applied", whether this is a new generation (the caller then cancels routes).
local function receive(a, now, lp)
    if type(a) ~= "table" then return "ignored" end
    local name, ctl = a.action, a.ctl
    if name == "wait" and ctl == nil then M.release("stop") return "released" end -- legacy: no fence
    if name ~= "wait" and name ~= "drive" then return "ignored" end
    if not isGen(ctl) then return "invalid_controller" end
    if ctl < RX.ctl then return "retired_controller" end -- a dead run's hold *and* stop
    if name == "wait" then
        newRun(ctl)
        M.release(type(a.reason) == "string" and a.reason:sub(1, 32) or "stop")
        if isGen(a.driveGen) then RX.stopGen = math.max(RX.stopGen, a.driveGen) end
        return "released"
    end
    local g, lease = a.gen, a.lease
    if not isGen(g) then return "invalid_generation" end
    if not finite(lease) or not (lease > 0) then return "invalid_lease" end
    newRun(ctl)
    if g <= RX.stopGen then return "released_generation" end
    if g < RX.floor then return "stale_generation" end
    RX.floor, RX.gen = g, g
    local fresh = g ~= RX.shot -- one-shots (tap, use, noclip toggle) fire once per generation
    local p = parse(a)
    local carry = H or {}
    H = { gen = g, p = p, speed = carry.speed or 0, dir = carry.dir, expires = now + clamp(lease, .1, 2),
          jump = carry.jump or "none", tapDue = carry.tapDue, useDue = carry.useDue,
          blockedSince = carry.blockedSince, blocked = carry.blocked or false, missing = carry.missing,
          pressed = carry.pressed }
    if fresh then
        RX.shot = g
        H.useDue = p.use or nil
        H.tapDue = p.jump == "tap" and now + .5 or nil
        H.jump = p.jump == "tap" and "pending" or "none"
        H.missing = nil
        beginMotion(g, now, lp)
        if p.mode and lp and IsValid(lp) then
            local current = lp:GetMoveType() == MOVETYPE_NOCLIP and "noclip" or "walk"
            if p.mode ~= current then
                -- One toggle per generation, never on renewal; the game may refuse it (VERIFY).
                noclip = { want = p.mode, state = "pending", gen = g, since = now, from = lp:GetMoveType() }
                RunConsoleCommand("noclip")
            end
        end
    end
    return "applied", fresh
end

function M.receive(a, now, lp)
    local outcome, fresh = receive(a, now, lp)
    if type(a) == "table" and a.action == "drive" and outcome ~= "applied" then
        reject = { gen = isGen(a.gen) and a.gen or 0, ctl = isGen(a.ctl) and a.ctl or 0, reason = outcome }
    end
    return outcome, fresh
end

function M.expire(now)
    if H and now >= H.expires then M.release("lease_expired") end
end

function M.active() return H ~= nil end

local function findPlayer(steamid)
    for _, q in ipairs(player.GetAll()) do
        if IsValid(q) and q:SteamID() == steamid and not q:IsDormant() then return q end
    end
end

-- Rate-limited look. Returns the horizontal distance to a tracked target, if any.
local function aim(cmd, lp, look, dt, moving)
    local view = cmd:GetViewAngles()
    local wantYaw, wantPitch, dist = look.yaw, look.pitch, nil
    if look.steamid or look.point then
        local at = look.point
        if look.steamid then
            local q = findPlayer(look.steamid)
            if not q then
                if not H.missing then H.missing = true reject = { gen = H.gen, reason = "look_target_missing" } end
                return nil
            end
            at = q:GetShootPos()
        end
        local d = at - lp:GetShootPos()
        dist = math.sqrt(d.x * d.x + d.y * d.y)
        local ang = d:Angle()
        wantYaw = dist >= 16 and ang.y or nil -- right on top of it: don't spin in place
        wantPitch = moving and clamp(math.AngleDifference(ang.p, 0), -25, 15) or ang.p
    end
    local step = look.rate * dt
    local yaw, pitch = view.y, view.p
    if wantYaw then yaw = yaw + clamp(math.AngleDifference(wantYaw, yaw), -step, step) end
    if wantPitch then pitch = pitch + clamp(math.AngleDifference(wantPitch, pitch), -step, step) end
    local new = Angle(clamp(pitch, -89, 89), yaw, 0)
    cmd:SetViewAngles(new)
    lp:SetEyeAngles(new)
    return dist
end

local OWNED = { IN_FORWARD, IN_BACK, IN_MOVELEFT, IN_MOVERIGHT, IN_SPEED, IN_WALK, IN_JUMP, IN_DUCK, IN_USE }

-- CreateMove application. Returns true while drive owns this command.
function M.step(cmd, lp, now, dt)
    M.expire(now)
    if not H then held = {} return false end
    dt = clamp(dt or .015, .001, .1)
    local p, out = H.p, {}
    for _, k in ipairs(OWNED) do cmd:RemoveKey(k) end
    cmd:ClearMovement()
    local flying = lp:GetMoveType() == MOVETYPE_NOCLIP
    local fwd, side = p.forward, p.right
    local dist = p.look and aim(cmd, lp, p.look, dt, fwd ~= 0 or side ~= 0) or nil
    local standoff = dist and p.look.near > 0 and dist <= p.look.near
    if standoff and fwd > 0 then fwd = 0 end
    local wish = math.sqrt(fwd * fwd + side * side)
    local target = wish > 0 and p.speed * lp:GetRunSpeed() or 0
    -- Ramp speed (+600/-900 u/s^2) and swing the wish direction at <=360 deg/s: changes curve.
    if H.speed < target then H.speed = math.min(target, H.speed + 600 * dt)
    else H.speed = math.max(target, H.speed - 900 * dt) end
    if wish > 0 then
        local want = math.deg(atan2(side, fwd))
        H.dir = H.dir and H.dir + clamp(math.AngleDifference(want, H.dir), -360 * dt, 360 * dt) or want
    end
    if H.speed > 0 and H.dir then
        local f, s = math.cos(math.rad(H.dir)) * H.speed, math.sin(math.rad(H.dir)) * H.speed
        if standoff and f > 0 then f = 0 end -- stand-off holds on the output too: no carried forward ramp
        cmd:SetForwardMove(f)
        cmd:SetSideMove(s)
        if f > 1 then out[#out + 1] = "forward" elseif f < -1 then out[#out + 1] = "back" end
        if s > 1 then out[#out + 1] = "right" elseif s < -1 then out[#out + 1] = "left" end
    end
    if target > lp:GetWalkSpeed() then cmd:AddKey(IN_SPEED) out[#out + 1] = "speed" end
    if flying then
        if p.up ~= 0 then -- VERIFY: upmove in GMod noclip, and how IN_SPEED scales it
            cmd:SetUpMove(p.up * math.max(H.speed, p.speed * lp:GetRunSpeed()))
            out[#out + 1] = p.up > 0 and "up" or "down"
        end
    else
        if p.crouch then cmd:AddKey(IN_DUCK) out[#out + 1] = "duck" end
        if H.tapDue then
            if now > H.tapDue then -- deadline first: a late grounded command must not jump
                H.tapDue, H.jump = nil, "missed"
            elseif lp:OnGround() then
                cmd:AddKey(IN_JUMP) out[#out + 1] = "jump"
                H.tapDue, H.jump = nil, "done"
            end
        elseif p.jump == "hold" then
            -- Source ignores a jump held from the last command (no pogo), so re-press on each
            -- landing to keep jumping. VERIFY live.
            if lp:OnGround() and not H.pressed then cmd:AddKey(IN_JUMP) out[#out + 1] = "jump" end
            H.pressed = lp:OnGround() and not H.pressed
        end
    end
    if H.useDue then cmd:AddKey(IN_USE) out[#out + 1] = "use" H.useDue = nil end
    -- blocked: wishing to move but slower than 20% of the target for over 0.5s.
    local actual = lp:GetVelocity():Length2D()
    if target > 0 and actual < .2 * target then
        H.blockedSince = H.blockedSince or now
        H.blocked = now - H.blockedSince > .5
    else
        H.blockedSince, H.blocked = nil, false
    end
    held = out
    return true
end

-- Motion log: call every CreateMove. Air phases are judged from the ground state; logging
-- continues after a release until he is settled (grounded, flying, or 3s), then the record is final.
function M.sample(lp, now)
    local m = motion
    if not m or not m.open or not IsValid(lp) then return end
    local pos, ground = lp:GetPos(), lp:OnGround()
    local flying = lp:GetMoveType() == MOVETYPE_NOCLIP
    local before = m.last
    m.path, m.last, m.t = m.path + planar(pos, before), pos, now - m.t0
    local dz = pos.z - m.start.z
    m.peak, m.low = math.max(m.peak, dz), math.min(m.low, dz)
    local k = m.takeoff
    if flying then
        m.takeoff = nil
    elseif not ground then
        if not k then m.takeoff = { pos = before, t = now, top = math.max(pos.z, before.z) } -- last point on ground or in flight
        else k.top = math.max(k.top, pos.z) end
    elseif k then -- landed: up = peak above takeoff, land = landing height vs takeoff (+ = higher)
        local j = { up = k.top - k.pos.z, land = pos.z - k.pos.z, dist = planar(pos, k.pos), time = now - k.t }
        m.phases, m.drop, m.takeoff = m.phases + 1, math.max(m.drop, -j.land), nil
        if #m.air >= 3 then table.remove(m.air, 1) end
        m.air[#m.air + 1] = j
    end
    m.ground = ground
    if not H or H.gen ~= m.gen then
        m.ended = m.ended or now
        if ((ground or flying) and not m.takeoff) or now - m.ended > 3 then m.open = false end
    end
end

local function motionBlock(m)
    if not m then return nil end
    local air = {}
    for i, j in ipairs(m.air) do air[i] = { up = r1(j.up), land = r1(j.land), dist = r1(j.dist), time = r1(j.time) } end
    return { gen = m.gen, ctl = m.ctl, t = r1(m.t), moved = r1(planar(m.last, m.start)), path = r1(m.path),
             dz = r1(m.last.z - m.start.z), peak = r1(m.peak), low = r1(m.low), air = air, phases = m.phases,
             drop = r1(m.drop), airborne = m.takeoff ~= nil, open = m.open }
end

-- Noclip outcome: the observed move type is the truth (the game may deny the toggle).
function M.watch(lp, now)
    if noclip.state ~= "pending" or not IsValid(lp) then return end
    local mt = lp:GetMoveType()
    if mt ~= noclip.from then
        noclip.state = mt == MOVETYPE_NOCLIP and "active" or "off"
    elseif now - noclip.since > 1 then
        noclip.state = "refused"
    end
end

local function mode(lp)
    local mt = lp:GetMoveType()
    if mt == MOVETYPE_NOCLIP then return "noclip" elseif mt == MOVETYPE_WALK then return "walk" end
    return "other"
end

-- The state.drive block. Python requires v, ctl, active, gen, stopGen and held.
function M.telemetry(lp, now)
    local vel = lp:GetVelocity()
    return { v = VERSION, ctl = RX.ctl, active = H ~= nil, gen = RX.gen, stopGen = RX.stopGen, held = held,
             lease = H and math.max(0, H.expires - now) or 0, speed = vel:Length2D(), vspeed = vel.z,
             mode = mode(lp), blocked = H and H.blocked or false, jump = H and H.jump or "none",
             noclip = { want = noclip.want, state = noclip.state, gen = noclip.gen },
             reject = reject, lastEnd = lastEnd, motion = motionBlock(motion), prevMotion = motionBlock(prevMotion) }
end

M.VERSION = VERSION
return M
