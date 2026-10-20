-- Run with a stock Lua runtime (or lupa); exercises the actual client module.
local vmt={};vmt.__index=vmt
function Vector(x,y,z)return setmetatable({x=x,y=y,z=z},vmt)end
function vmt.__add(a,b)return Vector(a.x+b.x,a.y+b.y,a.z+b.z)end
function vmt.__sub(a,b)return Vector(a.x-b.x,a.y-b.y,a.z-b.z)end
function vmt.__mul(a,b)return Vector(a.x*b,a.y*b,a.z*b)end
function vmt:Length()return math.sqrt(self.x^2+self.y^2+self.z^2)end
function vmt:GetNormalized()local n=self:Length();return n>0 and self*(1/n) or Vector(0,0,0)end
function vmt:Dot(b)return self.x*b.x+self.y*b.y+self.z*b.z end
local amt={};amt.__index=amt
function Angle(p,y,r)return setmetatable({p=p,y=y,r=r},amt)end
function vmt:Angle()return Angle(-math.deg(math.atan(self.z,math.sqrt(self.x^2+self.y^2))),math.deg(math.atan(self.y,self.x)),0)end
function amt:Forward()return Vector(math.cos(math.rad(self.y)),math.sin(math.rad(self.y)),0)end
function amt:Right()return Vector(math.sin(math.rad(self.y)),-math.cos(math.rad(self.y)),0)end
function math.Clamp(x,a,b)return math.max(a,math.min(b,x))end
function math.AngleDifference(a,b)return (a-b+180)%360-180 end
for n,k in ipairs({'IN_FORWARD','IN_BACK','IN_MOVELEFT','IN_MOVERIGHT','IN_SPEED','IN_WALK','IN_JUMP','IN_USE'})do _G[k]=n end
MASK_PLAYERSOLID=1
function IsValid(e)return type(e)=='table' and e.valid end
player={GetAll=function()return {}end}
local scenarios={
 {name='curb',obstacle=12,expect='step',moving=true},
 {name='low hurdle',obstacle=30,expect='jump',moving=true,jump=true},
 {name='wall',obstacle=100,expect='waiting_obstacle',moving=false},
 {name='ceiling over hurdle',obstacle=30,ceiling=true,expect='waiting_obstacle',moving=false},
 {name='unsupported hurdle landing',obstacle=30,gap=true,expect='no_ground',moving=false},
 {name='open road sprint',expect='run',moving=true,run=true},
 {name='walk mode',walk=true,expect='walk',moving=true},
 {name='walk refuses hurdle jump',obstacle=30,walk=true,expect='waiting_obstacle',moving=false},
 {name='drop',gap=true,expect='no_ground',moving=false},
}
for _,c in ipairs(scenarios)do
 local lp={pos=Vector(0,0,0)}
 function lp:GetPos()return self.pos end
 function lp:GetShootPos()return self.pos+Vector(0,0,64)end
 function lp:SetEyeAngles(a)self.eye=a end
 function lp:GetHull()return Vector(-16,-16,0),Vector(16,16,72)end
 function lp:GetStepSize()return 18 end
 function lp:GetRunSpeed()return 400 end
 function lp:OnGround()return true end
 util={TraceHull=function(t)
  local down=t.endpos.z<t.start.z and t.mins.x==-8
  if down then return {Hit=not c.gap,HitPos=Vector(t.endpos.x,0,c.obstacle and c.obstacle<40 and c.obstacle or 0),HitNormal=Vector(0,0,1)}end
  local blocked=c.obstacle and t.endpos.x>0 and t.start.z<c.obstacle
  if c.ceiling and t.endpos.z>18 then blocked=true end
  return {Hit=not not blocked,HitPos=Vector(16,0,0)}
 end}
 local cmd={f=0,s=0,keys={},view=Angle(0,0,0)}
 function cmd:ClearMovement()self.f=0;self.s=0 end
 function cmd:RemoveKey(k)self.keys[k]=nil end
 function cmd:AddKey(k)self.keys[k]=true end
 function cmd:GetViewAngles()return self.view end
 function cmd:SetViewAngles(a)self.view=a end
 function cmd:SetForwardMove(n)self.f=n end
 function cmd:SetSideMove(n)self.s=n end
 local m=assert(loadfile('deployments/oldpc/lua/greg_locomotion.lua'))()
 assert(m.start({id='test',points={{x=500,y=0,z=0}},walk=c.walk},0,lp))
 m.step(cmd,lp,.1,.1)
 local st=m.status();local observed=st.status=='moving' and st.traversal or st.status
 assert(observed==c.expect,c.name..': '..tostring(observed))
 assert((math.abs(cmd.f)+math.abs(cmd.s)>0)==c.moving,c.name..' movement')
 assert(not not cmd.keys[IN_JUMP]==not not c.jump,c.name..' jump')
 assert(not not cmd.keys[IN_SPEED]==not not c.run,c.name..' run')
 assert(cmd.view.p<=15 and cmd.view.p>=-25,c.name..' horizon')
 if not c.moving then m.cancel('blocked');assert(not m.start({id='test',points={{x=500,y=0,z=0}}},.2,lp))end
 print('PASS '..c.name)
end
