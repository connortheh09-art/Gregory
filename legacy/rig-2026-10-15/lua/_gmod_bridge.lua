--[[ greg_bridge.lua — clientside state/action bridge for Greg (Garry's Mod)

Drop into:  garrysmod/lua/autorun/client/greg_bridge.lua
Needs the server to allow clientside Lua:  sv_allowcslua 1  (your own / listen server).

It does two things every tick (default 0.5s):
  PUSH: POSTs a JSON snapshot of game state to  <greg_url>/gmod/state
  PULL: GETs  <greg_url>/gmod/cmd  and runs ONE action from the reply

Only the local view is touched. Useful cvars:
  greg_url      (default http://127.0.0.1:18091)   collector base
  greg_rate     (default 0.5)                      seconds between ticks
  greg_enable   (default 1)                        0 = pause the bridge

Debug:  greg_dump  prints one state snapshot to console.
]]

local CV_URL = CreateClientConVar("greg_url", "http://127.0.0.1:18091", true, false, "Greg bridge base URL")
local CV_RATE = CreateClientConVar("greg_rate", "0.5", true, false, "seconds between bridge ticks")
local CV_ON = CreateClientConVar("greg_enable", "1", true, false, "1 = bridge on")

-- Console passthrough is powerful; keep it to a known set unless you widen it.
local CONSOLE_ALLOW = {
	noclip = true, kill = true, jump = true, use = true,
	gm_spawn = true, give = true, drop = true, strip = true,
	sv_cheats = true, ent_remove = true, ent_remove_all = true,
}

local lastSeq = 0

local function round(n, d)
	d = d or 1
	local m = 10 ^ d
	return math.floor(n * m + 0.5) / m
end

local function vec(v, d)
	return { x = round(v.x, d), y = round(v.y, d), z = round(v.z, d) }
end

local function buildState(lp)
	local pos = lp:GetPos()
	local eyePos = lp:GetShootPos()
	local aim = lp:GetAimVector()
	local tr = util.TraceLine({
		start = eyePos,
		endpos = eyePos + aim * 250,
		filter = lp,
		mask = MASK_SHOT,
	})

	-- Nearby entity census: class -> count (helps the brain know what's around without eyes).
	local counts, list = {}, {}
	for _, e in ipairs(ents.FindInSphere(pos, 40)) do
		if e ~= lp then
			local c = e:GetClass()
			counts[c] = (counts[c] or 0) + 1
		end
	end
	for c, n in pairs(counts) do list[#list + 1] = { class = c, n = n } end

	local wep = lp:GetActiveWeapon()
	local ang = lp:EyeAngles()

	return {
		map = game.GetMap(),
		mode = engine.ActiveGamemode and engine.ActiveGamemode() or "?",
		name = lp:Nick(),
		steamid = lp:SteamID(),
		pos = vec(pos),
		ang = { p = round(ang.p, 1), y = round(ang.y, 1), r = round(ang.r, 1) },
		health = lp:Health(),
		armor = lp:Armor(),
		weapon = IsValid(wep) and wep:GetClass() or nil,
		eye = {
			hitPos = vec(tr.HitPos),
			hitClass = IsValid(tr.Entity) and tr.Entity:GetClass() or nil,
			hitName = IsValid(tr.Entity) and tr.Entity:GetModel() or nil,
			dist = round((tr.HitPos - eyePos):Length(), 1),
		},
		nearby = list,
		inVehicle = lp:InVehicle() and true or false,
		menu = (gui.IsGameUIVisible() or gui.IsConsoleVisible()) and true or false,
		seq = lastSeq,
	}
end

local keyHold = nil
local function releaseKey()
	if keyHold then
		RunConsoleCommand("-" .. keyHold)
		keyHold = nil
	end
end

local function runAction(a)
	if type(a) ~= "table" then return end
	local act = a.action

	if act == "say" then
		RunConsoleCommand("say", tostring(a.text or ""))

	elseif act == "look" then
		local lp = LocalPlayer()
		if IsValid(lp) and (a.yaw or a.pitch) then
			local cur = lp:EyeAngles()
			lp:SetEyeAngles(Angle(tonumber(a.pitch) or cur.p, tonumber(a.yaw) or cur.y, 0))
		end

	elseif act == "spawn" then
		RunConsoleCommand("gm_spawn", tostring(a.model or "models/props_c17/oildrum001.mdl"))

	elseif act == "use" then
		releaseKey()
		keyHold = "use"
		RunConsoleCommand("+use")
		timer.Simple(tonumber(a.hold) or 0.2, releaseKey)

	elseif act == "key" then
		local bind = tostring(a.bind or "")
		if bind ~= "" and not a.release then
			releaseKey()
			keyHold = bind
			RunConsoleCommand("+" .. bind)
			timer.Simple(tonumber(a.hold) or 0.3, releaseKey)
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
	-- unknown / "wait" -> nothing
end

local function pushState(state)
	local ok, body = pcall(util.TableToJSON, state)
	if not ok or not body then return end
	http.Post(CV_URL:GetString() .. "/gmod/state", { payload = body },
		function() end, function() end)
end

local function pullCommand()
	http.Fetch(CV_URL:GetString() .. "/gmod/cmd" .. "?seq=" .. lastSeq,
		function(body)
			if not body or body == "" or body == "none" then return end
			local ok, cmd = pcall(util.JSONToTable, body)
			if ok and type(cmd) == "table" then
				runAction(cmd)
			end
		end,
		function() end)
end

local function tick()
	if CV_ON:GetInt() ~= 1 then return end
	local lp = LocalPlayer()
	if not IsValid(lp) or not lp:Alive() then return end
	local state = buildState(lp)
	if not state then return end
	pushState(state)
	pullCommand()
end

timer.Create("greg_bridge_tick", CV_RATE:GetFloat(), 0, tick)

concommand.Add("greg_dump", function()
	local lp = LocalPlayer()
	if not IsValid(lp) then return end
	lastSeq = lastSeq + 1
	print("[greg] " .. util.TableToJSON(buildState(lp)))
end)

print("[greg] client bridge loaded -> " .. CV_URL:GetString())
