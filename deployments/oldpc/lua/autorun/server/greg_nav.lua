-- greg_nav.lua — server-side navmesh dump (Greg, 2026-10-14)
-- Purpose: hand the engine's OWN nav graph to the Python brain, so routing uses the real city
-- instead of the 512-unit sonar grid. Writes:
--   garrysmod/data/greg/navdump.json        (areas: center, size, corners, adjacency, flags)
--   garrysmod/data/greg/navdump_info.txt    (map, area count, ms, bytes, any missing APIs)
-- Defensive by design: every accessor is pcall-guarded, so a renamed binding degrades to a
-- reported gap instead of a dead script. A dead script is worse than a partial dump.

if not SERVER then return end

local DIR = "greg/"
local OUT = DIR .. "navdump.json"
local INFO = DIR .. "navdump_info.txt"

local function safe(fn, ...)
    local ok, res = pcall(fn, ...)
    if ok then return res end
    return nil
end

local function r(v)
    local n = tonumber(v)
    if not n or n ~= n or n == math.huge or n == -math.huge then return nil end
    return math.Round(n)
end

local function vec(p)
    return safe(function()
        if not p then return nil end
        local x, y, z = r(p.x), r(p.y), r(p.z)
        if x == nil or y == nil or z == nil then return nil end
        return { x, y, z }
    end)
end

-- file.Write returns a boolean; pcall alone does NOT detect a false return.
local function writeChecked(path, text)
    local ok = safe(file.Write, path, text)
    local bytes = safe(file.Size, path, "DATA")
    if ok ~= true or bytes ~= #text then
        print("[greg_nav] write failed/short: data/" .. path)
        return false
    end
    return true
end

local function dumpnav(tag)
    local t0 = SysTime()
    local gaps = {}
    safe(file.CreateDir, "greg")
    -- IsLoaded reports map-load status, not whether generation has finished.
    local generating = safe(navmesh.IsGenerating)
    if generating == nil then gaps[#gaps + 1] = "navmesh.IsGenerating() unavailable" end
    if generating == true then
        writeChecked(INFO, "status=deferred\nmap=" .. game.GetMap() .. "\nnote=navmesh generation active; retry later\n")
        return
    end
    writeChecked(INFO, "status=writing\nmap=" .. game.GetMap() .. "\n")

    local areas = safe(navmesh.GetAllNavAreas)
    if type(areas) ~= "table" then
        gaps[#gaps + 1] = "navmesh.GetAllNavAreas() unavailable"
        areas = {}
    end

    local loaded = safe(navmesh.IsLoaded)
    if loaded == nil then gaps[#gaps + 1] = "navmesh.IsLoaded() unavailable" end
    local map = game.GetMap()
    local n = #areas

    -- Keep compact sequential i/adjacency, but map by the engine's stable ID.
    local idx, nativeIDs = {}, {}
    local missing = {}
    for i, a in ipairs(areas) do
        local id = safe(function() return a:GetID() end)
        if type(id) == "number" then
            nativeIDs[i], idx[id] = id, i
        else
            missing.id = true
        end
    end

    -- Renderer change: read payload.areas, not the root as an array.
    local out = { schema_version = 1, map = map, navmesh_loaded = loaded,
                  areas = {}, ladders = {} }
    local ladderByID = {}
    if n == 0 then gaps[#gaps + 1] = "no areas returned; check load status/accessor gaps" end

    for i, a in ipairs(areas) do
        local e = { i = i, id = nativeIDs[i] }

        local c = safe(function() return a:GetCenter() end)
        e.c = vec(c)
        if not e.c and not missing.center then missing.center = true end

        local sx = safe(function() return a:GetSizeX() end)
        local sy = safe(function() return a:GetSizeY() end)
        e.x, e.y = r(sx), r(sy)
        if e.x == nil or e.y == nil then missing.size = true end

        local corners = {}
        for k = 0, 3 do
            local p = safe(function() return a:GetCorner(k) end)
            if p then corners[#corners + 1] = vec(p) end
        end
        if #corners > 0 then e.k = corners end
        if #corners ~= 4 then missing.corner = true end

        local adj = safe(function() return a:GetAdjacentAreas() end)
        if type(adj) == "table" then
            local list = {}
            for _, o in ipairs(adj) do
                local id = safe(function() return o:GetID() end)
                local j = id and idx[id]
                if j then list[#list + 1] = j else missing.adjacent_id = true end
            end
            e.a = list
        elseif not missing.adjacent then
            missing.adjacent = true
        end

        local at = safe(function() return a:GetAttributes() end)
        if at ~= nil then e.t = at else missing.attributes = true end

        local blocked = safe(function() return a:IsBlocked() end)
        if blocked ~= nil then e.b = blocked and 1 or 0 else missing.blocked = true end

        -- Documented enumeration: area-connected ladders, deduplicated by ID.
        local connected = safe(function() return a:GetLadders() end)
        if type(connected) == "table" then
            e.l = {}
            for _, lad in ipairs(connected) do
                local id = safe(function() return lad:GetID() end)
                if type(id) == "number" then
                    e.l[#e.l + 1] = id
                    if not ladderByID[id] then
                        local top = vec(safe(function() return lad:GetTop() end))
                        local bottom = vec(safe(function() return lad:GetBottom() end))
                        if not top or not bottom then missing.ladder_endpoints = true end
                        ladderByID[id] = { id = id, top = top, bottom = bottom }
                        out.ladders[#out.ladders + 1] = ladderByID[id]
                    end
                else
                    missing.ladder_id = true
                end
            end
        else
            missing.ladders = true
        end
        out.areas[i] = e
    end

    -- UNVERIFIED: exact empty-table JSON representation/native CNav* behavior
    -- still need a GMod run. Treat empty areas/ladders as empty collections.
    local ladders = out.ladders
    local blob = safe(util.TableToJSON, out)
    local jbytes = 0
    if type(blob) == "string" then
        if writeChecked(OUT, blob) then
            jbytes = #blob
        else
            gaps[#gaps + 1] = "navdump write failed or byte count differs"
        end
    else
        gaps[#gaps + 1] = "util.TableToJSON returned nil"
    end

    local ms = math.Round((SysTime() - t0) * 1000)
    local gapnames = {}
    for k in pairs(missing) do gapnames[#gapnames + 1] = k end
    table.sort(gapnames)
    if #gapnames > 0 then gaps[#gaps + 1] = "missing accessors: " .. table.concat(gapnames, ",") end

    writeChecked(INFO, string.format(
        "status=%s\nmap=%s\nareas=%d\nladders=%d\nnavmesh_loaded=%s\ntag=%s\nms=%d\njson_bytes=%d\ngaps=%s\n",
        (jbytes > 0 and "ready" or "failed"), map, n, #ladders, tostring(loaded), tag, ms, jbytes,
        (#gaps == 0 and "none" or table.concat(gaps, "; "))))

    print(string.format("[greg_nav] %s: %d areas, %d ladders -> data/%s (%d bytes, %d ms)%s",
        map, n, ladders and #ladders or 0, OUT, jbytes, ms,
        (#gaps == 0 and "" or " | " .. table.concat(gaps, "; "))))
end

concommand.Add("greg_navdump", function()
    dumpnav("cmd")
end)

-- auto-dump shortly after the map settles, once a navmesh is actually loaded
hook.Add("InitPostEntity", "greg_nav_autodump", function()
    local tries = 0
    timer.Create("greg_nav_autodump_timer", 2, 0, function()
        tries = tries + 1
        local loaded = safe(navmesh.IsLoaded)
        local areas = safe(navmesh.GetAllNavAreas)
        local generating = safe(navmesh.IsGenerating)
        if generating ~= true and (loaded == true or (type(areas) == "table" and #areas > 0)) then
            timer.Remove("greg_nav_autodump_timer")
            timer.Simple(1, function() dumpnav("auto") end)
        elseif tries >= 20 then
            timer.Remove("greg_nav_autodump_timer")
            dumpnav("auto")   -- report empty/unavailable, or defer during generation
        end
    end)
end)
