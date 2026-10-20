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
local function buildState(lp)
	local eye = lp:GetEyeTrace()
	local nearby = {}
	for _, e in ipairs(ents.FindInSphere(eye.HitPos, 512)) do
		if e ~= lp then
			nearby[#nearby + 1] = {
				class = e:GetClass(),
				name = e:GetName(),
				model = e:GetModel(),
				dist = math.floor(lp:GetPos():Distance(e:GetPos())),
			}
			if #nearby >= 12 then break end
		end
	end
	local wep = lp:GetActiveWeapon()
	return {
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
			hitClass = eye.HitEntity and eye.HitEntity:GetClass() or "world",
			hitName  = eye.HitEntity and (eye.HitEntity:GetName() or "") or "",
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
	if keyHold then
		RunConsoleCommand("-" .. keyHold)
		keyHold = nil
	end
end

-- Generation-tagged release: an old timer can never release a NEWER hold.
local function scheduleRelease(hold, default)
	holdGen = holdGen + 1
	local gen = holdGen
	local dur = math.Clamp(tonumber(hold) or default, 0.05, 5)
	timer.Simple(dur, function()
		if gen == holdGen then releaseKey() end
	end)
end

local function runAction(a)
	if type(a) ~= "table" then return end
	local act = a.action
	local lp = LocalPlayer()

	if act == "wait" then
		return

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

local function pushState(state)
	lastSeq = lastSeq + 1
	state.seq = lastSeq
	state.t = SysTime and SysTime() or os.time()
	local ok, body = pcall(util.TableToJSON, state)
	if not ok or not body then return end
	net.Start("greg_state")
		net.WriteString(body)
	net.SendToServer()
end

local function tick()
	if CV_ON:GetInt() ~= 1 then releaseKey() return end
	local lp = LocalPlayer()
	if not IsValid(lp) then releaseKey() return end
	local state = buildState(lp)
	if not state then return end
	state.dead = not lp:Alive()
	if state.dead or state.menu then releaseKey() end
	pushState(state)
end

-- Commands come back over net from the server realm.
net.Receive("greg_cmd", function()
	local body = net.ReadString()
	if not body or body == "" then return end
	local ok, cmd = pcall(util.JSONToTable, body)
	if ok and type(cmd) == "table" then
		local lp = LocalPlayer()
		-- Never execute while dead or in a menu.
		if IsValid(lp) and lp:Alive() and not (gui.IsGameUIVisible() or gui.IsConsoleVisible()) then
			runAction(cmd)
		end
	end
end)

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
