-- Run from the repo root with a stock Lua 5.1+/LuaJIT (or lupa): lua tests/test_drive.lua
-- Exercises the actual greg_drive.lua against the shared receiver vectors and a few
-- application rules. GMod is stubbed; this is not evidence of in-game behaviour.
local atan2 = math.atan2 or math.atan
local vmt = {}; vmt.__index = vmt
function Vector(x, y, z) return setmetatable({ x = x, y = y, z = z }, vmt) end
function vmt.__add(a, b) return Vector(a.x + b.x, a.y + b.y, a.z + b.z) end
function vmt.__sub(a, b) return Vector(a.x - b.x, a.y - b.y, a.z - b.z) end
function vmt:Length2D() return math.sqrt(self.x ^ 2 + self.y ^ 2) end
function vmt:Angle()
    return Angle(-math.deg(atan2(self.z, math.sqrt(self.x ^ 2 + self.y ^ 2))), math.deg(atan2(self.y, self.x)), 0)
end
function Angle(p, y, r) return { p = p, y = y, r = r } end
function math.AngleDifference(a, b) return (a - b + 180) % 360 - 180 end
for n, k in ipairs({ 'IN_FORWARD', 'IN_BACK', 'IN_MOVELEFT', 'IN_MOVERIGHT', 'IN_SPEED', 'IN_WALK', 'IN_JUMP', 'IN_DUCK', 'IN_USE' }) do
    _G[k] = n
end
MOVETYPE_WALK, MOVETYPE_NOCLIP = 2, 8
function IsValid(e) return type(e) == 'table' and e.valid end
local others = {}
player = { GetAll = function() return others end }
local console = {}
function RunConsoleCommand(...) console[#console + 1] = table.concat({ ... }, ' ') end

-- Minimal JSON reader for the shared vectors (objects, arrays, strings, numbers, literals).
local function decode(s)
    local i = 1
    local function ws() i = s:find('[^ \t\r\n]', i) or #s + 1 end
    local function str()
        local out, j = {}, i + 1
        while true do
            local c = s:sub(j, j)
            if c == '"' then i = j + 1 return table.concat(out) end
            if c == '\\' then
                local e = s:sub(j + 1, j + 1)
                if e == 'u' then out[#out + 1] = '?' j = j + 6
                else out[#out + 1] = ({ n = '\n', t = '\t', r = '\r', b = '\b', f = '\f' })[e] or e j = j + 2 end
            else out[#out + 1] = c j = j + 1 end
        end
    end
    local value
    function value()
        ws()
        local c = s:sub(i, i)
        if c == '{' or c == '[' then
            local t, n, close = {}, 0, c == '{' and '}' or ']'
            i = i + 1 ws()
            if s:sub(i, i) == close then i = i + 1 return t end
            while true do
                if c == '{' then
                    ws() local k = str() ws() assert(s:sub(i, i) == ':') i = i + 1
                    t[k] = value()
                else
                    n = n + 1 t[n] = value()
                end
                ws()
                local d = s:sub(i, i) i = i + 1
                if d == close then return t end
                assert(d == ',', 'bad JSON at ' .. i)
            end
        elseif c == '"' then return str()
        elseif s:sub(i, i + 3) == 'true' then i = i + 4 return true
        elseif s:sub(i, i + 4) == 'false' then i = i + 5 return false
        elseif s:sub(i, i + 3) == 'null' then i = i + 4 return nil
        end
        local num = s:match('^-?%d+%.?%d*[eE]?[-+]?%d*', i)
        i = i + #num
        return tonumber(num)
    end
    return value()
end

local function load()
    package.loaded.greg_drive = nil
    return dofile('deployments/oldpc/lua/greg_drive.lua')
end

local lp = { valid = true, ground = true, mt = MOVETYPE_WALK, vel = Vector(0, 0, 0), pos = Vector(0, 0, 0) }
function lp:GetMoveType() return self.mt end
function lp:OnGround() return self.ground end
function lp:GetRunSpeed() return 400 end
function lp:GetWalkSpeed() return 200 end
function lp:GetVelocity() return self.vel end
function lp:GetShootPos() return self.pos + Vector(0, 0, 64) end
function lp:SetEyeAngles(a) self.eye = a end

local function cmd()
    local c = { keys = {}, fwd = 0, side = 0, up = 0, view = Angle(0, 0, 0) }
    function c:RemoveKey(k) self.keys[k] = nil end
    function c:AddKey(k) self.keys[k] = true end
    function c:ClearMovement() self.fwd, self.side, self.up = 0, 0, 0 end
    function c:SetForwardMove(v) self.fwd = v end
    function c:SetSideMove(v) self.side = v end
    function c:SetUpMove(v) self.up = v end
    function c:GetViewAngles() return self.view end
    function c:SetViewAngles(a) self.view = a end
    return c
end

local failures, checks = 0, 0
local function check(ok, name)
    checks = checks + 1
    if not ok then failures = failures + 1 print('FAIL: ' .. name) end
end

-- 1. Shared receiver vectors (the same file the Python receiver model runs).
local f = assert(io.open('tests/gmod_drive_receiver_cases.json', 'r'))
local cases = decode(f:read('*a')).cases
f:close()
for _, case in ipairs(cases) do
    local drive, now = load(), 0
    for _, step in ipairs(case.steps) do
        if step.advance then
            now = now + step.advance
            drive.expire(now)
        else
            local got = drive.receive(step.action, now, nil)
            check(got == step.expect, case.name .. ': expected ' .. step.expect .. ', got ' .. tostring(got))
        end
    end
    local t = drive.telemetry(lp, now)
    for _, k in ipairs({ 'active', 'ctl', 'gen', 'stopGen' }) do
        check(t[k] == case.final[k], case.name .. ': final ' .. k .. ' ' .. tostring(t[k]) .. ' ~= ' .. tostring(case.final[k]))
    end
end

local function hold(gen, fields)
    local a = { action = 'drive', v = 1, ctl = 7, gen = gen, lease = 1.5,
                move = { forward = 1, right = 0, up = 0, speed = .5 }, jump = 'none', crouch = false }
    for k, v in pairs(fields or {}) do a[k] = v end
    return a
end
local function run(drive, now, n)
    local last
    for k = 1, n do last = cmd() drive.step(last, lp, now + k * .015, .015) end
    return last
end

-- 2. One-shots fire once per generation; renewals never repeat them.
do
    local drive = load()
    drive.receive(hold(1, { jump = 'tap', use = true }), 0, lp)
    local c = cmd() drive.step(c, lp, .01, .015)
    check(c.keys[IN_JUMP] and c.keys[IN_USE], 'tap and use press on the first command')
    c = cmd() drive.step(c, lp, .02, .015)
    check(not c.keys[IN_JUMP] and not c.keys[IN_USE], 'tap and use press once')
    local _, fresh = drive.receive(hold(1, { jump = 'tap', use = true }), .5, lp)
    c = cmd() drive.step(c, lp, .51, .015)
    check(fresh == false and not c.keys[IN_JUMP] and not c.keys[IN_USE], 'a renewal never re-presses')
    check(drive.telemetry(lp, .51).jump == 'done', 'tap reported done')
    drive.receive(hold(2, { jump = 'tap' }), 1, lp)
    c = cmd() drive.step(c, lp, 1.01, .015)
    check(c.keys[IN_JUMP], 'a new generation taps again')
end

-- 3. A tap that cannot happen within 0.5s is reported missed, not pressed later.
do
    local drive = load()
    lp.ground = false
    drive.receive(hold(1, { jump = 'tap' }), 0, lp)
    run(drive, 0, 40)
    lp.ground = true
    local c = cmd() drive.step(c, lp, .7, .015)
    check(not c.keys[IN_JUMP] and drive.telemetry(lp, .7).jump == 'missed', 'late tap is missed')
end

-- 4. Analog speed ramps; IN_SPEED only above walk speed.
do
    local drive = load()
    drive.receive(hold(1), 0, lp)
    local c = run(drive, 0, 40)
    check(math.abs(c.fwd - 200) < 1e-6 and not c.keys[IN_SPEED], 'walk pace ramps to 200 without IN_SPEED')
    drive.receive(hold(2, { move = { forward = 1, right = 0, up = 0, speed = .75 } }), .7, lp)
    c = run(drive, .7, 40)
    check(math.abs(c.fwd - 300) < 1e-6 and c.keys[IN_SPEED], 'jog keeps the ramped speed and adds IN_SPEED')
end

-- 5. Stand-off: no forward motion within `near` of a tracked player; strafing still applies.
do
    local drive = load()
    others = { { valid = true, SteamID = function() return 'STEAM_0:1:1000' end, IsDormant = function() return false end,
                 GetShootPos = function() return Vector(50, 0, 64) end } }
    drive.receive(hold(1, { move = { forward = 1, right = 1, up = 0, speed = 1 },
                            look = { steamid = 'STEAM_0:1:1000', rate = 180, near = 80 } }), 0, lp)
    local c = run(drive, 0, 60)
    check(math.abs(c.fwd) < 1 and c.side > 1, 'stand-off drops forward, keeps strafe')
    others = {}
    drive.receive(hold(2, { look = { steamid = 'STEAM_0:1:1000', rate = 180, near = 80 } }), 1, lp)
    run(drive, 1, 2)
    check(drive.telemetry(lp, 1.1).reject.reason == 'look_target_missing', 'a missing look target is reported')
end

-- 6. Lease expiry releases on the next command and clears held inputs.
do
    local drive = load()
    drive.receive(hold(1), 0, lp)
    run(drive, 0, 5)
    check(#drive.telemetry(lp, .1).held > 0, 'held inputs reported while driving')
    local c = cmd()
    local owned = drive.step(c, lp, 1.6, .015)
    local t = drive.telemetry(lp, 1.6)
    check(not owned and not t.active and #t.held == 0 and t.lastEnd == 'lease_expired', 'lease expiry releases')
end

-- 7. A retired run's stop is ignored; the owning run's stop releases.
do
    local drive = load()
    drive.receive(hold(1, { ctl = 11 }), 0, lp)
    check(drive.receive({ action = 'wait', ctl = 10, driveGen = 9 }, .1, lp) == 'retired_controller', 'retired stop refused')
    check(drive.active(), 'hold survives a retired stop')
    check(drive.receive({ action = 'wait', ctl = 11, driveGen = 2, reason = 'model_stop' }, .2, lp) == 'released', 'own stop')
    check(not drive.active() and drive.telemetry(lp, .2).lastEnd == 'model_stop', 'released with its reason')
end

-- 8. A noclip toggle is sent once per generation and judged by the observed move type.
do
    local drive = load()
    console = {}
    drive.receive(hold(1, { mode = 'noclip' }), 0, lp)
    drive.receive(hold(1, { mode = 'noclip' }), .5, lp)
    check(#console == 1 and console[1] == 'noclip', 'one toggle per generation')
    drive.watch(lp, 1.2)
    check(drive.telemetry(lp, 1.2).noclip.state == 'refused', 'unchanged move type means refused')
end

print(string.format('%d checks, %d failures', checks, failures))
if failures > 0 then os.exit(1) end
