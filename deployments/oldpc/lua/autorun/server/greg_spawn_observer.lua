-- Observe normal Sandbox spawn hooks; grants no permissions and issues no commands.
local events = {}
local tracked = {}
file.CreateDir('greg')
file.Write('greg/spawn_observer_boot.txt',tostring(os.time()))
local function record(kind, ply, ent)
    if not IsValid(ply) or not IsValid(ent) then return end
    local p = ent:GetPos()
    events[#events+1] = {kind=kind, steamid=ply:SteamID(), entity=ent:EntIndex(),
        class=ent:GetClass(), model=ent:GetModel(), pos={x=p.x,y=p.y,z=p.z},
        map=game.GetMap(), time=os.time()}
    tracked[ent] = events[#events]
    if #events > 128 then
        local old = table.remove(events,1)
        for entity,event in pairs(tracked) do if event == old then tracked[entity] = nil end end
    end
    file.CreateDir('greg')
    file.Write('greg/spawn_events.json',util.TableToJSON(events))
end
hook.Add('EntityRemoved','gregory_spawn_observer',function(ent)
    local event = tracked[ent]
    if not event then return end
    tracked[ent] = nil
    event.removedTime = os.time()
    file.Write('greg/spawn_events.json',util.TableToJSON(events))
end)
hook.Add('PlayerSpawnedProp','gregory_spawn_observer',function(ply,model,ent) record('prop',ply,ent) end)
for _, kind in ipairs({'NPC','SENT','Vehicle','SWEP'}) do
    local eventKind = kind
    hook.Add('PlayerSpawned'..kind,'gregory_spawn_observer',function(ply,ent) record(eventKind,ply,ent) end)
end
