-- Client-side discovery and normal Sandbox spawn requests; no server privilege bypass.
local M = {}
local registry = {}
local nextExport, nextSpawn = 0, 0
local session = ''
local function label(value)
    value=tostring(value or '')
    return language and language.GetPhrase and language.GetPhrase((value:gsub("^#", ""))) or value
end
local function rebuild()
    registry = {}
    local function add(kind, key, value, category)
        key = tostring(key or '')
        if key == '' or #key > 240 or key:find('[\r\n;]') then return end
        local id = kind .. ':' .. key
        registry[id] = {id=id, kind=kind, key=key,
            name=label(value or key), category=label(category)}
    end
    for _, source in ipairs({spawnmenu.GetPropTable(), spawnmenu.GetCustomPropTable()}) do
        for _, group in pairs(source or {}) do
            for _, item in pairs(group.contents or {}) do
                if item.type == 'model' and item.model then add('prop',item.model,item.model,group.name) end
            end
        end
    end
    for key, item in pairs(list.Get('NPC') or {}) do
        if not item.AdminOnly or LocalPlayer():IsAdmin() then add('npc',key,item.Name,item.Category) end
    end
    for key, item in pairs(list.Get('Vehicles') or {}) do
        if not item.AdminOnly or LocalPlayer():IsAdmin() then add('vehicle',key,item.Name,item.Category) end
    end
    for key, item in pairs(list.Get('SpawnableEntities') or {}) do
        if not item.AdminOnly or LocalPlayer():IsAdmin() then add('entity',key,item.PrintName,item.Category) end
    end
    for _, item in ipairs(weapons.GetList() or {}) do
        if item.Spawnable and (not item.AdminOnly or LocalPlayer():IsAdmin()) then
            add('weapon',item.ClassName,item.PrintName,item.Category)
        end
    end
end
function M.export(bridgeSession)
    if not IsValid(LocalPlayer()) or SysTime() < nextExport then return end
    nextExport = SysTime() + 30
    session = bridgeSession
    rebuild()
    local entries, addons = {}, {}
    -- A large prop list must not use the entire export budget before vehicles/weapons.
    local kinds = {'prop','npc','entity','vehicle','weapon'}
    local groups = {}
    for _, kind in ipairs(kinds) do groups[kind] = {} end
    for _, entry in SortedPairs(registry) do
        local group = groups[entry.kind]
        group[#group+1] = entry
    end
    local index = 1
    while #entries < 50000 do
        local added = false
        for _, kind in ipairs(kinds) do
            local entry = groups[kind][index]
            if entry and #entries < 50000 then
                entries[#entries+1] = entry
                added = true
            end
        end
        if not added then break end
        index = index + 1
    end
    for _, addon in ipairs(engine.GetAddons() or {}) do
        if addon.mounted then addons[#addons+1] = {id=addon.wsid, name=addon.title} end
    end
    file.CreateDir('greg')
    file.Write('greg/catalog.json', util.TableToJSON({version=1,map=game.GetMap(),
        bridgeSession=session, generated=os.time(), entries=entries, addons=addons,
        total=table.Count(registry), truncated=#entries<table.Count(registry)}))
end
local commands = {prop='gm_spawn', npc='gmod_spawnnpc', entity='gm_spawnsent',
                  vehicle='gm_spawnvehicle', weapon='gm_spawnswep'}
function M.spawn(action)
    local function report(status)
        file.CreateDir('greg')
        file.Write('greg/spawn_request.json',util.TableToJSON({id=tostring(action.id or ''),
            status=status,map=game.GetMap(),bridgeSession=session,time=os.time()}))
    end
    if SysTime() < nextSpawn then report('cooldown') return false end
    -- Rebuild to reject items removed since the exported catalog.
    rebuild()
    local item = registry[tostring(action.id or '')]
    if not item or not commands[item.kind] then report('unknown_item') return false end
    -- IsValidModel returns false clientside for valid but not-yet-server-precached
    -- models. Check mounted bytes here; normal gm_spawn validates server-side.
    if item.kind == 'prop' and not file.Exists(item.key,'GAME') then report('missing_model') return false end
    nextSpawn = SysTime() + 10
    RunConsoleCommand(commands[item.kind], item.key)
    report('submitted')
    -- Submission only: a server may refuse this request under its own rules.
    return true
end
hook.Add('PopulateSpawnMenu','gregory_catalog',function() nextExport=0 end)
return M
