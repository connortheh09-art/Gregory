-- Five-minute last-resort escape. Normal noclip permission only; never SetMoveType.
local R = {}
local W = {status="idle", cooldown=0, event=0}
local function status(s) if W.status~=s then W.status=s W.event=W.event+1 print("[greg rescue] "..s) end end
local function noclip(lp) return lp:GetMoveType()==MOVETYPE_NOCLIP end
local function distance(a,b) return (a-b):Length() end
local function clientBounds(p)
    -- util.IsInWorld is server-only on this build. Conservative Source coordinate
    -- bounds + solid contents + the existing hull/floor tests work clientside.
    if math.abs(p.x)>16320 or math.abs(p.y)>16320 or math.abs(p.z)>16320 then return false end
    return bit.band(util.PointContents(p),CONTENTS_SOLID)==0
end
local function dry(lp,p)
    if not clientBounds(p) or not clientBounds(p+Vector(0,0,72)) then return false end
    if bit.band(util.PointContents(p+Vector(0,0,8)), CONTENTS_WATER+CONTENTS_SLIME)~=0 then return false end
    local clear=util.TraceHull({start=p,endpos=p,mins=Vector(-16,-16,0),maxs=Vector(16,16,72),filter=lp,mask=MASK_PLAYERSOLID})
    if not clear or clear.StartSolid or clear.AllSolid then return false end
    local ground=util.TraceLine({start=p+Vector(0,0,4),endpos=p-Vector(0,0,12),filter=lp,mask=MASK_PLAYERSOLID})
    return ground and ground.Hit and ground.HitNormal.z>=.7 and ground.HitPos and ground.HitPos.z<=p.z+1
end
local function safeOff(lp)
    local p=lp:GetPos()
    if dry(lp,p) then return true end
    local clear=util.TraceHull({start=p,endpos=p,mins=Vector(-16,-16,0),maxs=Vector(16,16,72),filter=lp,mask=MASK_PLAYERSOLID})
    if not clear or clear.StartSolid or clear.AllSolid then return false end
    if lp:WaterLevel()>0 then return true end
    local tr=util.TraceLine({start=p,endpos=p-Vector(0,0,192),filter=lp,mask=MASK_PLAYERSOLID})
    return tr and tr.Hit and not tr.StartSolid and dry(lp,tr.HitPos+Vector(0,0,4))
end
local function clean(cmd)
    cmd:ClearMovement()
    for _,k in ipairs({IN_FORWARD,IN_BACK,IN_MOVELEFT,IN_MOVERIGHT,IN_SPEED,IN_WALK,IN_JUMP,IN_USE}) do cmd:RemoveKey(k) end
end
local function exitPoint(lp)
    local pos=lp:GetPos()
    if W.safe and distance(pos,W.safe)<=768 and dry(lp,W.safe) then return W.safe end
    for _,radius in ipairs({64,128,256}) do
        for i=0,15 do
            local a=math.rad(i*22.5)
            local q=pos+Vector(math.cos(a)*radius,math.sin(a)*radius,192)
            local tr=util.TraceLine({start=q,endpos=q-Vector(0,0,384),filter=lp,mask=MASK_PLAYERSOLID})
            if tr and tr.Hit and not tr.StartSolid and tr.HitNormal.z>=.7 then
                local target=tr.HitPos+Vector(0,0,4)
                if dry(lp,target) then return target end
            end
        end
    end
end
local function toggle(now)
    RunConsoleCommand("noclip") W.lastToggle=now W.toggles=(W.toggles or 0)+1
end
local function finish(s,now)
    W.phase=nil W.owned=false W.armed=false W.cooldown=now+300 status(s)
end
function R.report()
    return {status=W.status,event=W.event,phase=W.phase,owned=W.owned or false,
            stationarySince=W.since,threshold=300,cooldownUntil=W.cooldown}
end
function R.arm(lp,now)
    if not W.armed then W.anchor=lp:GetPos() W.since=now W.armed=true end
    W.lease=now+2.5
end
function R.preserve(now,lp)
    if not W.armed and lp then R.arm(lp,now) end
    if W.armed then W.lease=now+2.5 end
end
function R.abort(lp,now)
    W.armed=false
    if W.phase=="entering" and not noclip(lp) then W.cancelled=true return end
    if W.owned and noclip(lp) then
        if W.phase~="off" then
            if safeOff(lp) then W.phase="off" W.toggles=0 toggle(now) status("turning_off")
            else W.phase="help" status("off_waiting_clearance") end
        end
    else W.phase=nil end
end
function R.cleanup(lp,now)
    if W.phase=="entering" and W.cancelled then
        if noclip(lp) then W.owned=true W.phase="off" W.toggles=0 toggle(now) status("turning_off")
        elseif now-W.lastToggle>2 then finish("cancelled",now) end
        return
    end
    if W.phase=="help" then
        if not noclip(lp) then finish("off_confirmed",now)
        elseif safeOff(lp) then W.phase="off" W.toggles=0 toggle(now) status("turning_off") end
        return
    end
    if W.phase~="off" then return end
    if not noclip(lp) then finish("off_confirmed",now) return end
    if now-W.lastToggle>=3 then status("off_failed") end -- never spam a toggle that might arrive late
end
function R.tick(cmd,lp,now,enabled)
    R.cleanup(lp,now)
    if W.phase=="off" or W.phase=="help" then clean(cmd) return true end
    if not enabled then R.abort(lp,now) return false end
    if not W.armed then return false end
    if now>(W.lease or 0) then R.abort(lp,now) status("command_lease_expired") return false end
    local pos=lp:GetPos()
    if W.phase=="entering" then
        clean(cmd)
        if noclip(lp) then W.owned=true W.phase="flying" W.flyUntil=now+6 status("escaping")
        elseif now-W.lastToggle>1.5 then finish("noclip_denied",now) end
        return true
    elseif W.phase=="flying" then
        clean(cmd)
        if not noclip(lp) then finish("noclip_lost",now) return true end
        if (distance(pos,W.target)<8 and dry(lp,pos)) or now>W.flyUntil or not dry(lp,W.target) then
            -- Never turn collision back on inside solid geometry. If the target
            -- vanished, stop flying and report; don't pretend an unsafe off succeeded.
            if safeOff(lp) then W.phase="off" W.toggles=0 toggle(now) status("turning_off")
            else W.phase="help" status("off_waiting_clearance") end
            return true
        end
        local d=(W.target-pos):GetNormalized()
        local basis=Angle(0,cmd:GetViewAngles().y,0)
        cmd:SetForwardMove(d:Dot(basis:Forward())*200)
        cmd:SetSideMove(d:Dot(basis:Right())*200)
        cmd:SetUpMove(d.z*200)
        return true
    end
    if noclip(lp) then W.armed=false status("manual_noclip") return false end
    if lp:WaterLevel()==0 and lp:OnGround() and dry(lp,pos) then W.safe=pos end
    if distance(pos,W.anchor)>96 then W.anchor=pos W.since=now status("progress") end
    if now-W.since>=300 and now>=W.cooldown then
        W.target=exitPoint(lp)
        if not W.target then W.cooldown=now+300 status("no_safe_exit") return false end
        W.phase="entering" W.cancelled=false W.toggles=0 toggle(now) status("requesting_noclip")
        clean(cmd) return true
    end
    -- Normal swimming is the first response, not a reason to wait five minutes.
    if lp:WaterLevel()>=2 then
        clean(cmd) cmd:AddKey(IN_JUMP) cmd:SetUpMove(200) status("swimming_up") return true
    end
    return false
end
return R
