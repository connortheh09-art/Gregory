-- greg_sv.lua -- SERVER realm (Garry's Mod listen/dedicated server)
-- REDESIGN 2026-10-14: the server is the only realm that can touch disk, so it is
-- the bridge's I/O half. Replaces greg_chat_sv.lua.
--   chat:   hook -> data/greg/chat.jsonl   (append)
--   state:  client net "greg_state" -> data/greg/state.jsonl (append)
--   cmd:    data/greg/cmd.json (written by collector) -> net "greg_cmd" -> client
-- Place in garrysmod/lua/autorun/server/greg_sv.lua
-- Delete the old greg_chat_sv.lua when deploying this.
--
-- SELF-TEST MARKERS (so the bridge can be verified without a console):
--   data/greg/boot.txt       <- written once when THIS file loads (server Lua alive)
--   data/greg/state_count.txt<- keeps counting client net messages (client Lua alive)

-- GMod's file.Write REJECTS the .jsonl extension: verified live 2026-10-14 by
-- writing t1.txt / t2.json / t3.jsonl to data/greg -- the first two appeared,
-- t3.jsonl did NOT, with no error anywhere. .json writes fine, so the files are
-- named .json even though the content is one JSON object per line (JSONL).
local DIR_STATE = "greg/state.json"
local DIR_CHAT  = "greg/chat.json"
local FILE_CMD  = "greg/cmd.json"
local FILE_BOOT = "greg/boot.txt"
local FILE_COUNT= "greg/state_count.txt"
local FILE_CBOOT= "greg/client_boot.txt"

file.CreateDir("greg")
util.AddNetworkString("greg_state")
util.AddNetworkString("greg_cmd")
local lastCmdSeq = ""
local latestState = {}
local stateCount = 0

-- ---------- self-test marker: did server Lua load? ----------
local ok, err = pcall(file.Write, FILE_BOOT,
	"server bridge loaded\nallowed_cslua=" .. tostring(GetConVar("sv_allowcslua") and GetConVar("sv_allowcslua"):GetInt()))
if not ok then
	print("[greg] boot marker write failed: " .. tostring(err))
end

-- file.Append silently no-ops on a MISSING file, and file.Write(path, "") will
-- not create one either (both verified live 2026-10-14: a client state
-- incremented stateCount but left no state.jsonl on disk). So do read-modify-write:
-- it always creates the file with real content and surfaces errors instead of
-- failing silently.
local function appendJsonl(path, tbl)
	local ok2, body = pcall(util.TableToJSON, tbl)
	if not ok2 or not body then return end
	local ok3, err3 = pcall(function()
		local cur = file.Read(path, "DATA") or ""
		file.Write(path, cur .. body .. "\n")
	end)
	if not ok3 then print("[greg] write failed " .. path .. ": " .. tostring(err3)) end
end

hook.Add("PlayerSay", "greg_chat_mirror", function(ply, text, teamChat)
	if not IsValid(ply) then return end
	appendJsonl(DIR_CHAT, {
		t = os.time(),
		user = ply:Nick(),
		steamid = ply:SteamID(),
		msg = tostring(text or ""),
		team = teamChat and true or false,
	})
	-- do NOT return anything: let the message flow normally
end)

-- ---------- state in ----------
net.Receive("greg_state", function(len, ply)
	local body = net.ReadString()
	if not body or body == "" then return end
	local ok2, state = pcall(util.JSONToTable, body)
	if not IsValid(ply) or not ok2 or type(state) ~= "table" then return end
	-- Client-side self-report: an error in the client tick would otherwise kill
	-- the timer silently and take the whole bridge dark with no trace.
	if state.clientError then
		file.Write("greg/client_error.txt", os.date("%Y-%m-%d %H:%M:%S") .. " " .. tostring(state.clientError) .. "\n")
		print("[greg] client error: " .. tostring(state.clientError))
		return
	end
	-- Attribute snapshots to the actual net sender, not client-supplied identity.
	state.steamid, state.name = ply:SteamID(), ply:Nick()
	state.serverTime = os.time()
	latestState[state.steamid] = state
	appendJsonl(DIR_STATE, state)
	stateCount = stateCount + 1
	if stateCount == 1 then
		-- first proof that CLIENT Lua is running and net works
		file.Write(FILE_CBOOT, "first client state at " .. os.date("%Y-%m-%d %H:%M:%S") ..
			" from " .. (IsValid(ply) and ply:Nick() or "?") .. "\n")
	end
	-- per-state, so progress is visible without a console
	file.Write(FILE_COUNT, tostring(stateCount) .. "\n")
end)

-- ---------- commands out ----------
local function pollCommands()
	local raw = file.Read(FILE_CMD, "DATA")
	if not raw or raw == "" then return end
	local ok2, cmd = pcall(util.JSONToTable, raw)
	if not ok2 or type(cmd) ~= "table" then return end
	local seq = tostring(cmd.session or "") .. ":" .. tostring(cmd.seq or "")
	local st = latestState[cmd.steamid]
	local expires = tonumber(cmd.expires)
	if not st or st.dead or st.menu or st.enabled ~= true
		or os.time() - (st.serverTime or 0) > 3
		or not expires or os.time() >= expires
		or cmd.bridgeSession ~= st.bridgeSession
		or tonumber(cmd.controlEpoch) ~= tonumber(st.controlEpoch) then return end
	if seq == lastCmdSeq then return end
	lastCmdSeq = seq
	local payload = util.TableToJSON(cmd)
	if not payload then return end
	for _, p in ipairs(player.GetAll()) do
		if p:SteamID() == cmd.steamid then
			net.Start("greg_cmd")
				net.WriteString(payload)
			net.Send(p)
		end
	end
end

-- ---------- server command channel ----------
-- Lets the operator drive the SERVER console with no keyboard: write a line into
-- greg/server_cmd.txt and the next poll runs it (first token allowlisted). This is
-- what makes map changes self-service instead of needing a human at the console.
local FILE_SCMD = "greg/server_cmd.txt"
local SERVER_ALLOW = {
	["map"] = true, ["changelevel"] = true, ["sv_cheats"] = true,
	["sv_gravity"] = true, ["noclip"] = true, ["say"] = true, ["kick"] = true,
}
local function pollServerCmd()
	local raw = file.Read(FILE_SCMD, "DATA")
	if not raw or raw == "" then return end
	file.Write(FILE_SCMD, "\n")   -- empty-write is unreliable; newline is safe
	for line in string.gmatch(raw, "[^\r\n]+") do
		local first = string.match(line, "^%s*(%S+)")
		if first and SERVER_ALLOW[string.lower(first)] then
			print("[greg] server cmd: " .. line)
			game.ConsoleCommand(line .. "\n")
		else
			print("[greg] server cmd REJECTED: " .. line)
		end
	end
end
timer.Create("greg_server_cmd_poll", 1, 0, pollServerCmd)

-- VERIFY: command expiry/target/session checks need a multiplayer live test.
timer.Create("greg_cmd_poll", 0.25, 0, pollCommands)

print("[greg] server bridge loaded -> " .. DIR_STATE .. " / " .. FILE_CMD)
