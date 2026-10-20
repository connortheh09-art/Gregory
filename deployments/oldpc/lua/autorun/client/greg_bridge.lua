-- This autorun may be sent to ordinary joining players. Only the installed
-- agent client has the private controller modules; never register half a bridge.
if file.Read("greg/playercore_agent.txt", "DATA") ~= "installed-agent-20261015" then return end
-- greg_bridge.lua -- CLIENT realm (Garry's Mod)
-- REDESIGN 2026-10-14: no HTTP. Client-side http.* to 127.0.0.1 is blocked
-- (Facepunch docs: private-network requests blocked; -allowlocalhttp is
-- dedicated-server-only). Transport is now CLIENT --net--> SERVER --file--> collector,
-- and commands come back SERVER --net--> CLIENT.
-- HYBRID 2026-10-15: net relay when a local server heartbeat is fresh;
-- otherwise client DATA I/O. Requires permission to run client Lua on that server.

if _G.GREGORY_BRIDGE_LOADED then return end
local CV_RATE = CreateClientConVar("greg_rate", "0.5", true, false)
local CV_ON   = CreateClientConVar("greg_enable", "1", true, false)

local CV_CORE = CreateClientConVar("greg_playercore", "0", true, false)
local locomotion = include("greg_locomotion.lua")
local rescue = include("greg_rescue.lua")
local catalog = include("greg_catalog.lua")
if type(locomotion) ~= "table" or type(rescue) ~= "table" then
    print("[greg] helper modules unavailable; client bridge disabled")
    return
end
_G.GREGORY_BRIDGE_LOADED = true
local CV_RESCUE = CreateClientConVar("greg_stuck_noclip", "1", true, false)
-- One-shot deployment activation; subsequent reloads respect saved switches.
if file.Read("greg/playercore_enable_once.txt", "DATA") == "deploy-20261015-2255" then
    RunConsoleCommand("greg_playercore", "1")
    RunConsoleCommand("greg_stuck_noclip", "1")
    file.Rename("greg/playercore_enable_once.txt", "greg/playercore_enabled_20261015_2255.txt")
end
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

-- Lock once per map. Never switch transports mid-hold or on heartbeat expiry.
local ioMode = nil
local ioDeadline = nil
local nextIOCheck = 0
local localState = nil
local lastLocalCmdSeq = ""
local FILE_ALIVE = "greg/server_alive.txt"
local FILE_STATE = "greg/state.json"
local FILE_CMD = "greg/cmd.json"

local function chooseIOMode()
	if ioMode then return true end
	local now = SysTime()
	if not ioDeadline then ioDeadline = now + 3 end
	if now < nextIOCheck then return false end
	nextIOCheck = now + 1
	local stamp = tonumber(file.Read(FILE_ALIVE, "DATA"))
	local age = stamp and (os.time() - stamp)
	-- A leftover fresh heartbeat must not select a nonexistent foreign relay.
	local pooled = util.NetworkStringToID("greg_state") ~= 0
		and util.NetworkStringToID("greg_cmd") ~= 0
	if age and age >= 0 and age <= 3 and pooled then
		ioMode = "server"
	elseif now >= ioDeadline then
		ioMode = "local"
		file.CreateDir("greg")
	else
		return false -- allow a just-starting local server its first heartbeat
	end
	print("[greg] io=" .. ioMode .. " (locked for this map)")
	return true
end

hook.Add("InitPostEntity", "greg_io_map", function()
	locomotion.cancel("map_changed")
	ioMode, ioDeadline, nextIOCheck = nil, nil, 0
	localState, lastLocalCmdSeq = nil, ""
end)

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
	-- TraceHull returns nil before the player is fully spawned. Assuming "open"
	-- keeps free-roam moving; the alternative (0) would block every move.
	if not tr then return distance end
	return tr.StartSolid and 0 or tr.Fraction * distance
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
	["slot1"] = true,
	["slot2"] = true,
	["slot3"] = true,
	["slot4"] = true,
	["slot5"] = true,
	["slot6"] = true,
	["slot7"] = true,
	["slot8"] = true,
	["slot9"] = true,
	["invnext"] = true,
	["invprev"] = true,
	["lastinv"] = true,

}

-- VERIFY: these are the fields the collector expects; keep in sync with gmod_bridge.py.
-- Entity:GetName() is SERVERSIDE-ONLY. On the client it is nil, and calling it
-- throws "attempt to call method 'GetName' (a nil value)" on EVERY tick, which
-- kills greg_bridge_tick before any state is ever pushed. Guard both call sites.
local function entName(e)
	return isfunction(e.GetName) and (e:GetName() or "") or ""
end

-- Cheap sonar: one ring of hull traces so the brain can build an occupancy grid.
-- Absolute-yaw indexed (index i = yaw i * 22.5) so the planner can compare
-- against lp:EyeAngles().y directly. 16 traces per state push is nothing for Source.
local SCAN_RAYS, SCAN_DIST = 16, 512

local function scanAround(lp)
	local out = {}
	local origin = lp:GetShootPos()
	for i = 0, SCAN_RAYS - 1 do
		local yaw = i * (360 / SCAN_RAYS)
		local dir = Angle(0, yaw, 0):Forward()
		local tr = util.TraceHull({
			start = origin, endpos = origin + dir * SCAN_DIST,
			mins = Vector(-16, -16, -36), maxs = Vector(16, 16, 36),
			filter = lp, mask = MASK_PLAYERSOLID,
		})
		-- nil trace = not fully spawned; report "open" rather than a phantom wall.
		out[i + 1] = (tr and tr.Fraction) and math.floor(tr.Fraction * SCAN_DIST) or SCAN_DIST
	end
	return out
end

-- Independent budgets: players cannot consume the nearby-world-entity slots.
local PLAYER_RADIUS, PLAYER_LIMIT = 8192, 32
local PROP_RADIUS, PROP_LIMIT = 512, 12

local function buildState(lp)
	local eye = lp:GetEyeTrace()
	local eyePos = (eye and eye.HitPos) or lp:GetShootPos()
	local nearby = {}
	local function add(e)
		local p = e:GetPos()
		nearby[#nearby + 1] = {
			class = e:GetClass(),
			name = entName(e),
			model = e:GetModel(),
			dist = math.floor(lp:GetPos():Distance(p)),
			pos = { x = math.floor(p.x), y = math.floor(p.y), z = math.floor(p.z) },
		}
	end
	local players = {}
	for _, e in ipairs(player.GetAll()) do
		if IsValid(e) and e ~= lp then
			local d = lp:GetPos():Distance(e:GetPos())
			if d <= PLAYER_RADIUS then players[#players + 1] = { e = e, d = d } end
		end
	end
	table.sort(players, function(x, y) return x.d < y.d end)
	for i, c in ipairs(players) do
		if i > PLAYER_LIMIT then break end
		add(c.e)
	end
	-- Nearest-first, and NEVER include the player's own carried weapons: those sit at
	-- ~36u, filled all 12 slots, and crowded out every world entity (doors included).
	local cand = {}
	for _, e in ipairs(ents.FindInSphere(lp:GetPos(), PROP_RADIUS)) do
		if e ~= lp and not e:IsPlayer() and e:GetOwner() ~= lp then
			cand[#cand + 1] = { e = e, d = lp:GetPos():Distance(e:GetPos()) }
		end
	end
	table.sort(cand, function(x, y) return x.d < y.d end)
	for i, c in ipairs(cand) do
		if i > PROP_LIMIT then break end
		add(c.e)
	end
	local wep = lp:GetActiveWeapon()
	return {
		capabilities = { playercore = CV_CORE:GetInt() == 1 },
		locomotion = locomotion.status(),
		rescue = rescue.report(),
		waterLevel = lp:WaterLevel(),
		moveType = lp:GetMoveType(),
		players = (function()
			local entries = {}
			for _, p in ipairs(player.GetAll()) do
				if IsValid(p) and p ~= lp and lp:GetPos():Distance(p:GetPos()) <= PLAYER_RADIUS then
					local q, v = p:GetPos(), p:GetVelocity()
					entries[#entries + 1] = { steamid = p:SteamID(), name = p:Nick(),
						pos = { x = q.x, y = q.y, z = q.z }, velocity = { x = v.x, y = v.y, z = v.z },
						fresh = not p:IsDormant() }
				end
			end
			return entries
		end)(),
		io = ioMode,
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
        weaponClip = IsValid(wep) and wep:Clip1() or -1,
        weaponAmmo = IsValid(wep) and lp:GetAmmoCount(wep:GetPrimaryAmmoType()) or 0,
        inventory = (function()
            local out = {}
            for _,w in ipairs(lp:GetWeapons()) do
                if IsValid(w) then out[#out+1] = {class=w:GetClass(),slot=w:GetSlot()+1} end
            end
            return out
        end)(),
		eye = {
			hitPos  = { x = math.floor(eyePos.x), y = math.floor(eyePos.y), z = math.floor(eyePos.z) },
			hitClass = (eye and IsValid(eye.Entity)) and eye.Entity:GetClass() or "world",
			hitName  = (eye and IsValid(eye.Entity)) and entName(eye.Entity) or "",
			dist = math.floor(eyePos:Distance(lp:GetShootPos())),
		},
		nearby = nearby,
		scan = scanAround(lp),
		ver = "run3",
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

local lastSpeechID = ''
local undoEvents = {}
hook.Add('OnUndo','gregory_undo_observer',function(name)
    if not IsValid(LocalPlayer()) then return end
    file.CreateDir('greg')
    undoEvents[#undoEvents+1] = {name=tostring(name), time=os.time(), map=game.GetMap(),
        steamid=LocalPlayer():SteamID(), bridgeSession=bridgeSession}
    if #undoEvents > 32 then table.remove(undoEvents,1) end
    file.Write('greg/undo_events.json',util.TableToJSON(undoEvents))
end)
local function compoundSpeech(speech)
    if type(speech) ~= "table" or type(speech.id) ~= "string" or speech.id == lastSpeechID then return end
    if type(speech.text) ~= "string" or #speech.text == 0 or #speech.text > 240 then return end
    lastSpeechID = speech.id
    RunConsoleCommand("say", speech.text)
    file.CreateDir("greg")
    file.Write("greg/speech_ack.json", util.TableToJSON({id=speech.id, text=speech.text,
        bridgeSession=bridgeSession, time=os.time(), status="submitted"}))
end
local function runAction(a)
	if type(a) ~= "table" then return end
	local act = a.action
	local lp = LocalPlayer()
	if not active(lp) then releaseKey() return end
	compoundSpeech(a.speech)

	if act == "navigate" then
		if CV_CORE:GetInt() ~= 1 then return end
		releaseKey()
		if locomotion.start(a, SysTime(), lp) then rescue.arm(lp, SysTime()) end
		return
	elseif act == "gaze" then
		if CV_CORE:GetInt() == 1 then
            if a.stop then releaseKey() locomotion.cancel("stopped") rescue.abort(lp, SysTime()) end
            locomotion.gaze(a, SysTime())
        end
		return
	elseif act == "wait" then
		locomotion.cancel("stopped")
		if a.rescueEligible then rescue.preserve(SysTime(), lp) else rescue.abort(lp, SysTime()) end
		releaseKey()
		return

	elseif act == "move" then
		locomotion.cancel("legacy_move")
		rescue.arm(lp, SysTime())
		local dir = tostring(a.dir or "forward")
		local bind = DIR_BIND[dir]
		releaseKey()
		if not bind or lp:InVehicle() then return end
		-- CAMERA FUSION: snap the yaw BEFORE the clearance probe, so ONE verb both
		-- turns and walks. A turn no longer costs a whole separate tick.
		if a.turn ~= nil or a.yaw ~= nil then
			local cur = lp:EyeAngles()
			local yaw = tonumber(a.yaw)
			if not yaw then yaw = cur.y + (tonumber(a.turn) or 0) end
			if yaw == yaw then lp:SetEyeAngles(Angle(cur.p, yaw, 0)) end
		end
		if probe(lp, dir, 120) < 72 then return end
		moveDir = dir
		moveKeys[bind] = true
		RunConsoleCommand("+" .. bind)
	-- GMod: +walk is slow walk; +speed is sprint. Walk takes precedence.
	if a.walk == true then moveKeys.walk = true RunConsoleCommand("+walk")
	elseif a.sprint == true then moveKeys.speed = true RunConsoleCommand("+speed") end
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

	elseif act == "spawn_item" then
        if catalog then catalog.spawn(a) end

	elseif act == "spawn" then
		RunConsoleCommand("gm_spawn", tostring(a.model or "models/props_c17/oildrum001.mdl"))

	elseif act == "use" then
		if not IsValid(lp) or not lp:Alive() then return end
		releaseKey()
		-- Doors want a TAP, not a hold. A held +use reads as "picking up", and the
		-- model was filling hold with junk ("door", "1s"). Fire a short burst instead.
		local taps = math.Clamp(math.floor(tonumber(a.taps) or 2), 1, 4)
		local gen = holdGen
		local function tap(n)
			if gen ~= holdGen then return end
			RunConsoleCommand("+use")
			timer.Simple(0.08, function()
				if gen ~= holdGen then return end
				RunConsoleCommand("-use")
				if n > 1 then
					timer.Simple(0.15, function() tap(n - 1) end)
				end
			end)
		end
		tap(taps)

	elseif act == "select" then
        locomotion.cancel("weapon_select")
        releaseKey()
        if lp:InVehicle() then return end
        if type(a.weapon) == "string" then
            local w = lp:GetWeapon(a.weapon)
            if IsValid(w) then input.SelectWeapon(w) end
        else
            local command = tostring(a.cmd or "")
            if not (string.match(command,"^slot[1-9]$") or command=="invnext" or command=="invprev" or command=="lastinv") then return end
            RunConsoleCommand(command)
            local fast = GetConVar("hud_fastswitch")
            if command ~= "lastinv" and fast and fast:GetInt()==0 then
                local gen,epoch = holdGen,controlEpoch
                timer.Simple(.15,function()
                    if gen~=holdGen or epoch~=controlEpoch or not active(lp) or lp:InVehicle() then return end
                    keyHold="attack"
                    RunConsoleCommand("+attack")
                    scheduleRelease(.05,.05)
                end)
            end
        end

	elseif act == "key" then
		locomotion.cancel("legacy_key")
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

	elseif act == "flashlight" then
		if not IsValid(lp) or not lp:Alive() then return end
		-- HL2/GMod flashlight toggle (bound to F). The city gets very dark at street level.
		RunConsoleCommand("impulse", "100")
	end
end


-- The old server path still sends exactly the serialized state over net.
-- LOCAL alone owns the local state file; use the existing read/modify/write
-- workaround, preserving .json and the collector's serverTime freshness field.
local localArchived = {}
local function localAppend(path, body)
    file.CreateDir("greg")
    if file.Size(path,"DATA") > 2097152 then
        if not localArchived[path] then
            local archive = path:gsub("%.json$", "") .. "_history_" .. tostring(os.time()) .. ".txt"
            file.Rename(path,archive)
            if not file.Exists(archive,"DATA") then error("could not preserve local history") end
            localArchived[path] = true
        else
            file.Write(path,body .. "\n")
            return
        end
    end
    if file.Exists(path,"DATA") then file.Append(path,body .. "\n")
    else file.Write(path,body .. "\n") end
end
hook.Add("OnPlayerChat","greg_local_chat",function(ply,text,teamChat)
    if ioMode ~= "local" or not IsValid(ply) then return end
    local body=util.TableToJSON({steamid=ply:SteamID(),user=ply:Nick(),msg=text,
        team=teamChat==true,t=os.time(),map=game.GetMap(),bridgeSession=bridgeSession})
    if body then localAppend("greg/chat.json",body) end
end)
local remoteSpawns = {}
net.Receive("gregory_spawn_observation",function()
    if ioMode ~= "local" or not IsValid(LocalPlayer()) then return end
    local raw=net.ReadString()
    if #raw>4096 then return end
    local event=util.JSONToTable(raw)
    if type(event) ~= "table" or event.steamid ~= LocalPlayer():SteamID() or event.map ~= game.GetMap() then return end
    if not ({prop=true,NPC=true,SENT=true,Vehicle=true,SWEP=true})[event.kind] then return end
    if type(event.id) ~= "string" or #event.id>80 then return end
    if event.removedTime then
        for _,old in ipairs(remoteSpawns) do if old.id==event.id then old.removedTime=os.time() end end
    else
        event.serverTime=event.time;event.time=os.time();event.bridgeSession=bridgeSession
        remoteSpawns[#remoteSpawns+1]=event
        if #remoteSpawns>128 then table.remove(remoteSpawns,1) end
    end
    file.CreateDir("greg")
    file.Write("greg/spawn_events.json",util.TableToJSON(remoteSpawns))
end)
local function sendBody(body)
    if ioMode == "server" then
        net.Start("greg_state")
        net.WriteString(body)
        net.SendToServer()
    elseif ioMode == "local" then
        localAppend(FILE_STATE,body)
    end
end

local function reportClientError(err)
	print("[greg] client error: " .. tostring(err))
	local ok, failure = pcall(function()
		if ioMode == "local" then
			file.Write("greg/client_error.txt", os.date("%Y-%m-%d %H:%M:%S") .. " " .. tostring(err) .. "\n")
		elseif ioMode == "server" then
			local body = util.TableToJSON({ clientError = tostring(err), seq = -1 })
			if body then sendBody(body) end
		end
	end)
	if not ok then print("[greg] error reporting failed: " .. tostring(failure)) end
end

local function pollLocalCommands()
	if ioMode ~= "local" then return end -- SERVER never even reads the mailbox
	local raw = file.Read(FILE_CMD, "DATA")
	if not raw or raw == "" then return end
	local ok, cmd = pcall(util.JSONToTable, raw)
	if not ok or type(cmd) ~= "table" then return end
	local lp, st = LocalPlayer(), localState
	local expires = tonumber(cmd.expires)
	local now = os.time()
	if not active(lp) or not st or st.dead or st.menu or st.enabled ~= true
		or now - (st.serverTime or 0) > 3 or now < (st.serverTime or 0)
		or cmd.steamid ~= lp:SteamID() or cmd.steamid ~= st.steamid
		or not expires or expires ~= expires or expires == math.huge or expires == -math.huge
		or now >= expires or cmd.bridgeSession ~= bridgeSession
		or tonumber(cmd.controlEpoch) ~= controlEpoch then return end
	local seq = tostring(cmd.session or "") .. ":" .. tostring(cmd.seq or "")
	if seq == lastLocalCmdSeq then return end
	lastLocalCmdSeq = seq -- same dedup key/order as server pollCommands
	runAction(cmd.action) -- unchanged applicator and generation-tagged releases
end

local lastLocalErr = nil
timer.Create("greg_local_cmd_poll", 0.25, 0, function()
	local ok, err = pcall(pollLocalCommands)
	if not ok and err ~= lastLocalErr then
		lastLocalErr = err
		reportClientError(err)
	end
end)

local lastSerErr = nil

local function pushState(state)
    if catalog then pcall(catalog.export, bridgeSession) end
	lastSeq = lastSeq + 1
	state.seq = lastSeq
	state.t = SysTime and SysTime() or os.time()
	if ioMode == "local" then state.serverTime = os.time() end
	local ok, body = pcall(util.TableToJSON, state)
	if not ok or not body then
		-- util.TableToJSON returns nil+err rather than raising, so a serialization
		-- failure would otherwise drop the state SILENTLY every tick. Report once.
		if lastSerErr ~= tostring(body) then
			lastSerErr = tostring(body)
			local ok2, msg = pcall(util.TableToJSON, { clientError = "state serialize failed: " .. tostring(body) })
			if ok2 and msg then sendBody(msg) end
		end
		return
	end
	sendBody(body)
	if ioMode == "local" then localState = state end
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
	if not chooseIOMode() then releaseKey() return end
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
		reportClientError(err)
	end
end

-- Commands come back over net from the server realm.
net.Receive("greg_cmd", function()
	if ioMode ~= "server" then return end -- LOCAL never accepts relayed actions
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
hook.Add("ShutDown", "greg_release", function() locomotion.cancel("shutdown") releaseKey() end)
hook.Add("Think", "greg_rescue_cleanup", function()
    local lp = LocalPlayer()
    if not IsValid(lp) then return end
    if CV_CORE:GetInt() ~= 1 or CV_RESCUE:GetInt() ~= 1 or not active(lp) or lp:InVehicle() then rescue.abort(lp, SysTime()) end
    rescue.cleanup(lp, SysTime())
end)
hook.Add("CreateMove", "greg_continuous_control", function(cmd)
    local lp = LocalPlayer()
    if CV_CORE:GetInt() ~= 1 or not active(lp) or lp:InVehicle() then
        locomotion.cancel("interlock")
        if IsValid(lp) then rescue.abort(lp, SysTime()) rescue.cleanup(lp, SysTime()) end
        return
    end
    if rescue.tick(cmd, lp, SysTime(), CV_RESCUE:GetInt() == 1) then return end
    locomotion.step(cmd, lp, SysTime(), FrameTime())
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

print("[greg] client bridge loaded (hybrid I/O; awaiting map mode lock)")

-- Dead-only respawn input. No model call, server cheats, or live attack bind.
local respawnOn = CreateClientConVar("greg_autorespawn", "1", true, false)
local respawnDeadAt, respawnNext, respawnTries = nil, 0, 0
hook.Add("CreateMove", "greg_dead_respawn", function(cmd)
    local lp = LocalPlayer()
    if not IsValid(lp) or lp:Alive() then
        respawnDeadAt, respawnNext, respawnTries = nil, 0, 0
        return
    end
    if CV_ON:GetInt() ~= 1 or respawnOn:GetInt() ~= 1
        or gui.IsGameUIVisible() or gui.IsConsoleVisible() then
        respawnDeadAt, respawnNext = nil, 0
        return
    end
    cmd:ClearButtons()
    cmd:SetForwardMove(0); cmd:SetSideMove(0); cmd:SetUpMove(0)
    local now = SysTime()
    if not respawnDeadAt then respawnDeadAt = now end
    if now - respawnDeadAt < 2 or now < respawnNext or respawnTries >= 15 then return end
    cmd:AddKey(IN_JUMP)
    respawnTries = respawnTries + 1
    respawnNext = now + 2
    print("[greg] respawn input attempt " .. respawnTries)
end)
print("[greg] dead-only autorespawn installed")
