-- Continuous client controller. No file I/O or model calls in CreateMove.
-- Installed as garrysmod/lua/greg_locomotion.lua; loaded only by client bridge.
local M = {}
local VERSION = "curb-v1"
local S = { status = "idle", event = 0, cursor = 1 }
local gaze = nil
local function finite(x) return type(x) == "number" and x == x and math.abs(x) < math.huge end
local function vector(p)
    if type(p) ~= "table" or not finite(p.x) or not finite(p.y) or not finite(p.z) then return nil end
    return Vector(p.x,p.y,p.z)
end
local function transition(status)
    if S.status ~= status then S.event = S.event + 1 S.status = status end
end
function M.cancel(reason)
    gaze = nil
    S.points = nil
    transition(reason or "idle")
end
function M.status()
    return { version = VERSION, traversal = S.traversal, id = S.id, status = S.status, cursor = S.cursor, event = S.event,
             interaction = S.interaction, interactionTime = S.interactionTime }
end
function M.start(a, now, lp)
    if type(a.id) ~= "string" or #a.id > 64 or #a.id < 1 then return false end
    if type(a.points) ~= "table" or #a.points < 1 or #a.points > 256 then return false end
    local points, radii = {}, {}
    for i,p in ipairs(a.points) do
        points[i] = vector(p) if not points[i] then return false end
        radii[i] = math.Clamp(tonumber(p.radius) or 24,4,24)
    end
    if S.id ~= a.id then
        S = { id = a.id, points = points, radii = radii, cursor = 1, status = "moving", event = S.event + 1,
              started = now, sampleAt = now, samplePos = lp:GetPos(), failures = 0,
              anchor = lp:GetPos(), doorAttempts = 0, nextDoor = 0, speed = 0 }
    elseif not S.points then
        -- A renewal cannot resurrect a failed/arrived route. Planner must use a new id.
        return false
    end
    S.expires = now + math.Clamp(tonumber(a.lease) or 2, .2, 2.5)
    S.walk = a.walk == true
    S.gazeSteamID = type(a.gazeSteamID) == "string" and a.gazeSteamID or nil
    return true
end
function M.gaze(a, now)
    local target = vector(a.target)
    if not target then return false end
    gaze = { target = target, expires = now + math.Clamp(tonumber(a.duration) or 1, .1, 3) }
    return true
end
local function clean(cmd)
    cmd:ClearMovement()
    for _,k in ipairs({IN_FORWARD,IN_BACK,IN_MOVELEFT,IN_MOVERIGHT,IN_SPEED,IN_WALK,IN_JUMP,IN_USE}) do cmd:RemoveKey(k) end
end
local function planar(p,q) return math.sqrt((p.x-q.x)^2+(p.y-q.y)^2) end
local function corridorDistance(p,a,b)
    local dx,dy=b.x-a.x,b.y-a.y
    local d=dx*dx+dy*dy
    local t=d>0 and math.Clamp(((p.x-a.x)*dx+(p.y-a.y)*dy)/d,0,1) or 0
    return planar(p,Vector(a.x+t*dx,a.y+t*dy,p.z))
end
local function steer(cmd,lp,target,dt,travel)
    local wanted=(target-lp:GetShootPos()):Angle()
    if travel then wanted.p=math.Clamp(wanted.p,-25,15) end
    local old=cmd:GetViewAngles()
    local yaw=old.y+math.Clamp(math.AngleDifference(wanted.y,old.y),-180*dt,180*dt)
    local pitch=old.p+math.Clamp(math.AngleDifference(wanted.p,old.p),-120*dt,120*dt)
    local view=Angle(math.Clamp(pitch,travel and -25 or -89,travel and 15 or 89),yaw,0)
    cmd:SetViewAngles(view)
    lp:SetEyeAngles(view)
    return view
end
function M.step(cmd,lp,now,dt)
    dt=math.Clamp(dt or .015,.001,.1)
    if gaze and now>gaze.expires then gaze=nil end
    if S.points and now>S.expires then M.cancel("expired") clean(cmd) return end
    if not S.points then
        if gaze then steer(cmd,lp,gaze.target,dt) end
        return
    end
    clean(cmd)
    local pos=lp:GetPos()
    while S.points[S.cursor] and planar(pos,S.points[S.cursor])<S.radii[S.cursor] and math.abs(pos.z-S.points[S.cursor].z)<40 do
        S.anchor=S.points[S.cursor];S.cursor=S.cursor+1;S.sampleAt=now;S.samplePos=pos
    end
    local target=S.points[S.cursor]
    if not target then M.cancel("arrived") return end
    if corridorDistance(pos,S.anchor,target)>128 or math.abs(pos.z-target.z)>512 then M.cancel("route_diverged") return end
    local delta=target-pos
    local len=math.sqrt(delta.x*delta.x+delta.y*delta.y)
    if len<1 then M.cancel("blocked") return end
    local dir=Vector(delta.x/len,delta.y/len,0)
    local speed=S.walk and 100 or math.max(200,lp:GetRunSpeed())
    speed=math.min(speed,math.max(40,len*2))
    S.speed=math.min(speed,(S.speed or 0)+600*dt)
    local lookAhead=math.min(len,math.max(24,S.speed*.2))
    local ahead=pos+dir*lookAhead
    local mins,maxs=lp:GetHull()
    local function sweep(a,b)
        return util.TraceHull({start=a,endpos=b,mins=mins,maxs=maxs,filter=lp,mask=MASK_PLAYERSOLID})
    end
    local function clear(t) return t and not t.Hit and not t.StartSolid and not t.AllSolid end
    local function support(at,rise)
        local drop=not lp:OnGround() and S.jumpUntil and now<S.jumpUntil and 72 or 48
        local t=util.TraceHull({start=at+Vector(0,0,rise+2),endpos=at-Vector(0,0,drop),
            mins=Vector(-8,-8,0),maxs=Vector(8,8,2),filter=lp,mask=MASK_PLAYERSOLID})
        return t and t.Hit and not t.StartSolid and not t.AllSolid
            and t.HitNormal and t.HitNormal.z>=.65 and t.HitPos.z>=pos.z-drop
    end
    local hull=sweep(pos+Vector(0,0,2),ahead+Vector(0,0,2))
    if not hull or hull.StartSolid or hull.AllSolid then M.cancel("blocked") return end
    S.traversal="walk"
    local jumping=false
    local obstacle=hull.Entity
    local isDoor=IsValid(obstacle) and string.find(obstacle:GetClass(),"door",1,true)
    -- Source already steps over short curbs; do not stop before it can do so.
    -- Require head clearance, an unobstructed raised hull AND supported landing.
    local function raised(rise,landing)
        local up=Vector(0,0,rise+2)
        return clear(sweep(pos+Vector(0,0,2),pos+up))
            and clear(sweep(pos+up,landing+up)) and support(landing,rise)
    end
    if hull.Hit and not isDoor and lp:OnGround() then
        local step=math.Clamp(lp:GetStepSize(),0,18)
        if step>0 and raised(step,ahead) then
            hull.Hit=false;S.traversal="step"
        elseif not S.walk and len>64 and now>=(S.nextJump or 0)
            and (not IsValid(obstacle) or obstacle:IsWorld()) then
            local landing=pos+dir*math.min(len,64)
            if raised(40,landing) then
                hull.Hit=false;jumping=true;S.nextJump=now+1.5;S.traversal="jump"
                S.jumpUntil=now+.8
            end
        end
    end
    -- During a validated jump, use a raised ground probe, never disable support checks.
    local airborne=not lp:OnGround() and S.jumpUntil and now<S.jumpUntil
    if not support(ahead,(jumping or airborne) and 42 or 20) then M.cancel("no_ground") return end
    if hull.Hit then
        steer(cmd,lp,ahead+Vector(0,0,64),dt,true)
        local e=hull.Entity
        local isDoor=IsValid(e) and string.find(e:GetClass(),"door",1,true)
        S.blockedAt=S.blockedAt or now
        if isDoor and S.doorAttempts<3 and now>=S.nextDoor then
            S.doorAttempts=S.doorAttempts+1;S.nextDoor=now+.6;S.useUntil=now+.08
            S.interaction="door_use";S.interactionTime=now
        end
        if S.useUntil and now<S.useUntil then cmd:AddKey(IN_USE) end
        if now-S.blockedAt>2 then M.cancel("blocked") end
        transition(S.points and "waiting_obstacle" or "blocked")
    else
        S.blockedAt=nil
        -- Camera horizon is independent of the short collision-probe distance.
        local aim=target
        local distance=math.Clamp(S.speed*1.5,200,600)
        for i=S.cursor+1,#S.points do
            local p=S.points[i]
            local d=Vector(p.x-pos.x,p.y-pos.y,0)
            if d:Length()>distance or d:GetNormalized():Dot(dir)<.8 then break end
            aim=p
        end
        local aimdelta=Vector(aim.x-pos.x,aim.y-pos.y,0)
        local look=pos+aimdelta:GetNormalized()*math.max(distance,aimdelta:Length())+Vector(0,0,64)
        local deliberate=gaze~=nil
        if gaze then look=gaze.target end
        if not gaze and S.gazeSteamID then
            for _,p in ipairs(player.GetAll()) do
                if IsValid(p) and p:SteamID()==S.gazeSteamID and not p:IsDormant() then look=p:GetShootPos() deliberate=true break end
            end
        end
        local view=steer(cmd,lp,look,dt,not deliberate)
        -- Sprint only on a clear supported corridor, away from waypoint turns.
        if not S.walk and not jumping and not airborne and S.traversal=="walk" and len>160 then
            local runway=pos+dir*math.min(len,96)
            if clear(sweep(pos+Vector(0,0,2),runway+Vector(0,0,2))) and support(runway,20) then
                S.speed=math.min(lp:GetRunSpeed(),len*2,S.speed+600*dt)
                cmd:AddKey(IN_SPEED);S.traversal="run"
            end
        end
        if jumping then cmd:AddKey(IN_JUMP) end
        if S.traversal~="run" then S.speed=math.min(S.speed,S.walk and 100 or 200) end
        -- Project world-space travel onto the CURRENT camera basis. Looking left
        -- therefore produces a strafe, not a new world-space destination.
        local basis=Angle(0,view.y,0)
        cmd:SetForwardMove(dir:Dot(basis:Forward())*S.speed)
        cmd:SetSideMove(dir:Dot(basis:Right())*S.speed)
        if S.walk then cmd:AddKey(IN_WALK) end
        transition("moving")
    end
    -- Containment/progress check only while actually requesting movement.
    if now-S.sampleAt>=3 then
        if planar(pos,S.samplePos)<24 then M.cancel("stuck") clean(cmd) return end
        S.sampleAt=now;S.samplePos=pos
    end
end
return M
