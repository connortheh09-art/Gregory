"""Bounded per-map/per-SteamID conversation threads + grounded status replies.
No game commands or model/network calls here.
"""
from __future__ import annotations
import json,math,os,re,time
from pathlib import Path


def phrase(text):
    t=' '.join(str(text).casefold().replace('’',"'").split()).strip().rstrip('.!?')
    t=re.sub(r'^(?:hey[, ]+)?greg[, :]+','',t)
    t=re.sub(r'^(?:can|could|would) you (?:tell me |give me )?','',t)
    return t.strip()


def coords(value):
    try:
        p=tuple(float(value[k]) for k in ('x','y','z'))
        return p if all(math.isfinite(x) for x in p) else None
    except (KeyError,TypeError,ValueError):return None


class ChatMemory:
    def __init__(self,path):
        self.path=Path(path);self.threads={}
        try:
            if self.path.stat().st_size<=1_000_000:
                raw=json.loads(self.path.read_text(encoding='utf8'))
                if raw.get('version')==1 and isinstance(raw.get('threads'),dict):
                    self.threads={k:v for k,v in raw['threads'].items() if isinstance(v,dict) and isinstance(v.get('turns'),list)}
        except (OSError,ValueError,AttributeError):pass
    def thread(self,map_name,sid):
        # SteamID, NOT nickname; same names do not merge people's conversations.
        key=str(map_name)+'|'+str(sid)
        if key not in self.threads:self.threads[key]={'turns':[],'last_used':0}
        return self.threads[key]
    def save(self):
        if len(self.threads)>32:
            keep=sorted(self.threads,key=lambda k:self.threads[k].get('last_used',0),reverse=True)[:32]
            self.threads={k:self.threads[k] for k in keep}
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            tmp=self.path.with_suffix(self.path.suffix+'.tmp')
            tmp.write_text(json.dumps({'version':1,'threads':self.threads},ensure_ascii=True),encoding='utf8');os.replace(tmp,self.path)
        except OSError:pass
    def add(self,map_name,sid,role,text,wall,session=''):
        if not sid or role not in {'user','assistant'}:return
        t=self.thread(map_name,sid)
        t['turns'].append({'role':role,'content':str(text)[:600],'time':wall,'session':session})
        t['turns']=t['turns'][-24:];t['last_used']=wall;self.save()
    def history(self,map_name,sid,session='',exclude_current_user=True):
        turns=list(self.thread(map_name,sid)['turns'])
        if exclude_current_user and turns and turns[-1].get('role')=='user':turns.pop()
        out=[]
        for turn in turns[-8:]:
            if turn.get('role') not in {'user','assistant'}:continue
            content=str(turn.get('content',''))[:600]
            if turn.get('session')!=session:content='[Older session; not current position data] '+content
            out.append({'role':turn['role'],'content':content})
        return out
    def kind(self,text,map_name,sid,wall,session):
        t=phrase(text)
        if re.fullmatch(r"(?:how far(?: away)? are you(?: from me)?|how far (?:apart|away) are we|what(?:'s| is) (?:the|our) distance|(?:tell me )?(?:your|our) distance(?: from me)?)",t):return 'distance'
        if re.fullmatch(r"(?:am i|are you|are we) (?:any )?closer(?: (?:now|yet))?|(?:am i|are you|are we) farther(?: (?:now|yet))?|closer now",t):return 'compare'
        if re.fullmatch(r"where are you(?: (?:now|at))?|what(?:'s| is) your (?:current )?(?:position|location)|(?:give me )?(?:an? )?update on your (?:position|location)",t):return 'position'
        if re.fullmatch(r"what are you doing(?: now)?|(?:give me )?(?:a )?status update|what(?:'s| is) your status",t):return 'status'
        if re.fullmatch(r'(?:what|how) about now|and now|now',t):
            thread=self.thread(map_name,sid)
            if thread.get('topic_session')==session and 0<=wall-thread.get('topic_time',0)<=120:
                topic=thread.get('topic')
                return 'compare' if topic in {'distance','compare'} else topic if topic in {'position','status'} else None
        return None
    def answer(self,text,state,sid,wall):
        map_name=str(state.get('map',''));session=str(state.get('bridgeSession',''))
        kind=self.kind(text,map_name,sid,wall,session)
        if kind is None:return None
        thread=self.thread(map_name,sid)
        thread.update(topic=kind,topic_time=wall,topic_session=session,last_used=wall)
        try:fresh=0<=wall-float(state['serverTime'])<=3
        except (TypeError,ValueError,KeyError):fresh=False
        own=coords(state.get('pos'))
        if not fresh or own is None:
            self.save();return "My position data is stale. I can't give a reliable update."
        if kind in {'distance','compare'}:
            players=[p for p in state.get('players',[]) if isinstance(p,dict) and p.get('steamid')==sid and p.get('fresh') is True and coords(p.get('pos'))]
            if len(players)!=1:
                self.save();return "I don't have your fresh position. I won't guess the distance."
            measured=math.dist(own,coords(players[0]['pos']));old=thread.get('measurement') or {}
            previous=old.get('distance')
            usable=isinstance(previous,(int,float)) and math.isfinite(previous) and old.get('session')==session and 0<=wall-old.get('time',0)<=120
            reply=f'About {round(measured):,} units away.'
            if kind=='compare':
                if not usable:reply+=' No earlier fresh measurement to compare yet.'
                elif abs(previous-measured)<16:reply+=' Roughly unchanged since your last check.'
                else:reply+=f" {'Closer' if measured<previous else 'Farther'} by {round(abs(previous-measured)):,} since your last check."
            thread['measurement']={'distance':measured,'time':wall,'session':session}
        else:
            movement=state.get('locomotion') or {};status=str(movement.get('status','unknown'))
            position='('+', '.join(str(round(x)) for x in own)+')'
            if kind=='position':reply=f'Position {position}. {status.replace("_"," ").capitalize()}.'
            else:
                labels={'moving':'Moving along my route.','blocked':'Stopped: route blocked.','stuck':'Stopped: not making progress.','no_ground':'Stopped: no safe ground ahead.','waiting_obstacle':'Waiting for an obstacle to clear.','stopped':'Standing still.','expired':'Stopped: movement command expired.'}
                reply=labels.get(status,'Controller status: '+status.replace('_',' ')+'.')
                if status=='moving':reply+=f" Waypoint {movement.get('cursor','?')}."
        self.save();return ' '.join(reply.split()[:12])
