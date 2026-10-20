--[[ greg_chat_sv.lua — SERVER autorun: mirror player chat to a data file.

Drop into:  garrysmod/lua/autorun/server/greg_chat_sv.lua
(Needs a listen/own server — this is how Greg reads what people type in GMod chat.)

Why a file: OnPlayerChat is a SERVER hook, and server-side http.Post is URL-whitelisted.
Writing to garrysmod/data/greg_chat.jsonl sidesteps that entirely — the local collector
just tails the file. One JSON object per line, append-only.

Read it with:  the gmod_bridge.py collector (--chat-file <...garrysmod/data/greg_chat.jsonl>)
]]

local FILE = "greg_chat.jsonl"

local function write(ply, text, kind)
	local rec = {
		t = os.time(),
		user = IsValid(ply) and ply:Nick() or "server",
		steamid = IsValid(ply) and ply:SteamID() or "",
		msg = tostring(text or ""),
		kind = kind or "chat",
	}
	local ok, json = pcall(util.TableToJSON, rec)
	if ok and json then
		file.Append(FILE, json .. "\n")
	end
end

-- The main chat hook. Return false so the normal chat still shows.
hook.Add("OnPlayerChat", "greg_chat", function(ply, text, teamChat, isDead)
	write(ply, text, teamChat and "team" or "chat")
	return false
end)

-- /me emotes and any other text routed through PlayerSay.
hook.Add("PlayerSay", "greg_chat_say", function(ply, text)
	write(ply, text, "say")
	return text
end)

local function say(s)
	print("[greg_chat] " .. s)
end
say("chat mirror -> garrysmod/data/" .. FILE)
