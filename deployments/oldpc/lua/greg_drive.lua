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
local atan2 = math.atan2 or math.atan -- LuaJIT/5.1 and 5.3+

local function finite(x) return type(x) == "number" and x == x and math.abs(x) < math.huge end
local function isGen(v) return finite(v) and v >= 1 and v < 2 ^ 53 and math.floor(v) == v end
local function clamp(x, a, b) return math.max(a, math.min(b, x)) end
local function num(v, lo, hi, default) if finite(v) then return clamp(v, lo, hi) end return default end

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
    if dist and p.look.near > 0 and dist <= p.look.near and fwd > 0 then fwd = 0 end -- stand-off
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
            if lp:OnGround() then
                cmd:AddKey(IN_JUMP) out[#out + 1] = "jump"
                H.tapDue, H.jump = nil, "done"
            elseif now > H.tapDue then
                H.tapDue, H.jump = nil, "missed"
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
             reject = reject, lastEnd = lastEnd }
end

M.VERSION = VERSION
return M
