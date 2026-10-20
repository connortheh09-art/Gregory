-- greg_bridge.lua -- CLIENT realm (Garry's Mod)
-- REDESIGN 2026-10-14: no HTTP. Client-side http.* to 127.0.0.1 is blocked
-- (Facepunch docs: private-network requests blocked; -allowlocalhttp is
-- dedicated-server-only). Transport is now CLIENT --net--> SERVER --file--> collector,
-- and commands come back SERVER --net--> CLIENT.
-- REQUIRES: sv_allowcslua 1 on the listen server.

local CV_RATE = CreateClientConVar("greg_rate", "0.5", true, false)
local CV_ON   = CreateClientConVar("greg_enable", "1", true, false)

local lastSeq = 0
local keyHold = nil
local holdGen = 0
local moveKeys = {}
local moveDir = nil
local jumpWanted, nextJump = false, 0
local controlEpoch = 0
local wasActive = false
local bridgeSession = tostring(os.time()) .. ":" .. tostring(SysTime())
local DIR_BIND = { forward = "forward", back = "back", left = "moveleft", right = "moveright" }

local function active(lp)
	return CV_ON:GetInt() == 1 and IsValid(lp) and lp:Alive()
		and not (gui.IsGameUIVisible() or gui.IsConsoleVisible())
end

-- VERIFY: client hull traces are approximate; live-test props/slopes/vehicles.
local function probe(lp, dir, distance)
	local yaw = Angle(0, lp:EyeAngles().y, 0)
	local v = yaw:Forward()
	if dir == "back" then v = -v
	elseif dir == "left" then v = -yaw:Right()
	elseif dir == "right" then v = yaw:Right() end
	local start = lp:GetPos() + Vector(0, 0, 4)
	local tr = util.TraceHull({ start = start, endpos = start + v * distance,
		mins = Vector(-16, -16, 0), maxs = Vector(16, 16, 48),
		filter = lp, mask = MASK_PLAYERSOLID })
	return tr.StartSolid and 0 or math.floor(tr.Fraction * distance)
end

-- Only these console commands may ever be issued by the brain (first token matched).
local CONSOLE_ALLOW = {
	["noclip"] = true,
	["kill"] = true,
	["god"] = true,
	["give"] = true,
	["ent_create"] = true,
	["physgun_freeze"] = true,
	["sv_gravity"] = true,
	["r_drawviewmodel"] = true,
}

-- VERIFY: these are the fields the collector expects; keep in sync with gmod_bridge.py.
-- Entity:GetName() is SERVERSIDE-ONLY. On the client it is nil, and calling it
-- throws "attempt to call method 'GetName' (a nil value)" on EVERY tick, which
-- kills greg_bridge_tick before any state is ever pushed. Guard both call sites.
local function entName(e)
	return isfunction(e.GetName) and (e:GetName() or "") or ""
end

local function buildState(lp)
	local eye = lp:GetEyeTrace()
	local nearby = {}
	for _, e in ipairs(ents.FindInSphere(lp:GetPos(), 512)) do
		if e ~= lp then
			nearby[#nearby + 1] = {
				class = e:GetClass(),
				name = entName(e),
				model = e:GetModel(),
				dist = math.floor(lp:GetPos():Distance(e:GetPos())),
			}
			if #nearby >= 12 then break end
		end
	end
	local wep = lp:GetActiveWeapon()
	return {
		bridgeSession = bridgeSession,
		controlEpoch = controlEpoch,
		enabled = CV_ON:GetInt() == 1,
		grounded = lp:OnGround(),
		clearance = { forward = probe(lp, "forward", 120), back = probe(lp, "back", 120),
			left = probe(lp, "left", 120), right = probe(lp, "right", 120) },
		name = lp:Nick(),
		steamid = lp:SteamID(),
		map = game.GetMap(),
		mode = GAMEMODE and GAMEMODE.Name or "unknown",
		pos = { x = math.floor(lp:GetPos().x), y = math.floor(lp:GetPos().y), z = math.floor(lp:GetPos().z) },
		ang = { p = math.floor(lp:EyeAngles().p), y = math.floor(lp:EyeAngles().y) },
		health = lp:Health(),
		armor = lp:Armor(),
		weapon = IsValid(wep) and wep:GetClass() or "none",
		eye = {
			hitPos  = { x = math.floor(eye.HitPos.x), y = math.floor(eye.HitPos.y), z = math.floor(eye.HitPos.z) },
			hitClass = IsValid(eye.Entity) and eye.Entity:GetClass() or "world",
			hitName  = IsValid(eye.Entity) and entName(eye.Entity) or "",
			dist = math.floor(eye.HitPos:Distance(lp:GetShootPos())),
		},
		nearby = nearby,
		inVehicle = lp:InVehicle() and true or false,
		menu = (gui.IsGameUIVisible() or gui.IsConsoleVisible()) and true or false,
		seq = lastSeq,
	}
end

local function releaseKey()
	holdGen = holdGen + 1           -- invalidate any pending release
	for bind in pairs(moveKeys) do RunConsoleCommand("-" .. bind) end
	moveKeys = {}
	moveDir = nil
	jumpWanted = false
	if keyHold then
		RunConsoleCommand("-" .. keyHold)
		keyHold = nil
	end
end

-- Generation-tagged release: an old timer can never release a NEWER hold.
local function scheduleRelease(hold, default)
	holdGen = holdGen + 1
	local gen = holdGen
	local dur = tonumber(hold) or default
	if dur ~= dur or dur == math.huge or dur == -math.huge then dur = default end
	dur = math.Clamp(dur, 0.05, 3)
	timer.Simple(dur, function()
		if gen == holdGen then releaseKey() end
	end)
end

local function runAction(a)
	if type(a) ~= "table" then return end
	local act = a.action
	local lp = LocalPlayer()
	if not active(lp) then releaseKey() return end

	if act == "wait" then
		releaseKey()
		return

	elseif act == "move" then
		local dir = tostring(a.dir or "forward")
		local bind = DIR_BIND[dir]
		releaseKey()
		if not bind or lp:InVehicle() or probe(lp, dir, 120) < 72 then return end
		moveDir = dir
		moveKeys[bind] = true
		RunConsoleCommand("+" .. bind)
		if a.sprint == true then moveKeys.speed = true RunConsoleCommand("+speed") end
		jumpWanted = a.jump == true
		nextJump = 0
		scheduleRelease(a.duration, 1.25)

	elseif act == "say" then
		RunConsoleCommand("say", tostring(a.text or ""))

	elseif act == "look" then
		if IsValid(lp) and (a.yaw or a.pitch) and lp:Alive() then
			local cur = lp:EyeAngles()
			lp:SetEyeAngles(Angle(tonumber(a.pitch) or cur.p, tonumber(a.yaw) or cur.y, 0))
		end

	elseif act == "spawn" then
		RunConsoleCommand("gm_spawn", tostring(a.model or "models/props_c17/oildrum001.mdl"))

	elseif act == "use" then
		if not IsValid(lp) or not lp:Alive() then return end
		releaseKey()
		keyHold = "use"
		RunConsoleCommand("+use")
		scheduleRelease(a.hold, 0.2)

	elseif act == "key" then
		if not IsValid(lp) or not lp:Alive() then return end
		local bind = tostring(a.bind or "")
		if bind ~= "" and not a.release then
			releaseKey()
			keyHold = bind
			RunConsoleCommand("+" .. bind)
			scheduleRelease(a.hold, 0.3)
		elseif a.release then
			releaseKey()
		end

	elseif act == "console" then
		local parts = {}
		for w in string.gmatch(tostring(a.cmd or ""), "%S+") do parts[#parts + 1] = w end
		if #parts > 0 and CONSOLE_ALLOW[string.lower(parts[1])] then
			RunConsoleCommand(unpack(parts))
		end
	end
end

local lastSerErr = nil

local function pushState(state)
	lastSeq = lastSeq + 1
	state.seq = lastSeq
	state.t = SysTime and SysTime() or os.time()
	local ok, body = pcall(util.TableToJSON, state)
	if not ok or not body then
		-- util.TableToJSON returns nil+err rather than raising, so a serialization
		-- failure would otherwise drop the state SILENTLY every tick. Report once.
		if lastSerErr ~= tostring(body) then
			lastSerErr = tostring(body)
			local ok2, msg = pcall(util.TableToJSON, { clientError = "state serialize failed: " .. tostring(body) })
			if ok2 and msg then
				net.Start("greg_state")
					net.WriteString(msg)
				net.SendToServer()
			end
		end
		return
	end
	net.Start("greg_state")
		net.WriteString(body)
	net.SendToServer()
end

local lastErr = nil

local function tickInner()
	if CV_ON:GetInt() ~= 1 then
		if wasActive then controlEpoch = controlEpoch + 1 wasActive = false end
		releaseKey()
		-- Still publish enabled=false so the collector stops planning.
	end
	local lp = LocalPlayer()
	if not IsValid(lp) then releaseKey() return end
	local state = buildState(lp)
	if not state then return end
	state.dead = not lp:Alive()
	local enabled = active(lp)
	if enabled ~= wasActive then controlEpoch = controlEpoch + 1 wasActive = enabled end
	state.controlEpoch = controlEpoch
	if not enabled then releaseKey() end
	pushState(state)
end

-- A Lua error inside the tick silently kills the timer and the bridge goes dark
-- with no trace (exactly how a whole evening was lost on 2026-10-14). Catch it
-- and report the FIRST error of each kind over net, so the server can write it
-- to disk for inspection without needing a console.
local function tick()
	local ok, err = pcall(tickInner)
	if not ok and err ~= lastErr then
		lastErr = err
		local ok2, body = pcall(util.TableToJSON, { clientError = tostring(err), seq = -1 })
		if ok2 and body then
			net.Start("greg_state")
				net.WriteString(body)
			net.SendToServer()
		end
	end
end

-- Commands come back over net from the server realm.
net.Receive("greg_cmd", function()
	local body = net.ReadString()
	if not body or body == "" then return end
	local ok, cmd = pcall(util.JSONToTable, body)
	if ok and type(cmd) == "table" then
		local lp = LocalPlayer()
		-- Never execute while dead or in a menu.
		if active(lp) and cmd.bridgeSession == bridgeSession
			and tonumber(cmd.controlEpoch) == controlEpoch then
			runAction(cmd.action)	-- envelope preserved by the server
		else
			releaseKey()
		end
	end
end)

-- VERIFY: Source +speed/+jump behavior and Think cadence need a live run.
hook.Add("Think", "greg_move_reflex", function()
	local lp = LocalPlayer()
	if not active(lp) then
		if wasActive then controlEpoch = controlEpoch + 1 wasActive = false end
		releaseKey()
		return
	end
	if not moveDir then return end
	local ahead = math.max(72, lp:GetVelocity():Length2D() * 0.25)
	if lp:InVehicle() or probe(lp, moveDir, ahead) < ahead then releaseKey() return end
	if jumpWanted and lp:OnGround() and CurTime() >= nextJump then
		nextJump = CurTime() + 0.8
		local gen = holdGen
		moveKeys.jump = true
		RunConsoleCommand("+jump")
		timer.Simple(0.1, function()
			if gen == holdGen then
				RunConsoleCommand("-jump")
				moveKeys.jump = nil
			end
		end)
	end
end)
cvars.AddChangeCallback("greg_enable", function()
	controlEpoch = controlEpoch + 1
	wasActive = false
	releaseKey()
end, "greg_bridge_enable")
hook.Add("ShutDown", "greg_release", releaseKey)

local function resetTick()
	timer.Create("greg_bridge_tick", math.max(CV_RATE:GetFloat(), 0.1), 0, tick)
end
resetTick()
cvars.AddChangeCallback("greg_rate", resetTick, "greg_bridge_rate")

concommand.Add("greg_dump", function()
	local lp = LocalPlayer()
	if not IsValid(lp) then return end
	print("[greg] " .. util.TableToJSON(buildState(lp)))
end)

print("[greg] client bridge loaded (net transport)")
