"""Existing Discord audio/STT/TTS supplied as callbacks; no model/game bypass."""
import asyncio
import http.client
import io
from greg_voice_protocol import stop_text
import json
import math
import re
from difflib import SequenceMatcher
import time
import threading
import uuid
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError


class VoiceHTTP:
    def __init__(self, receipt):
        value=urlsplit(receipt['url'])
        if (value.scheme!='http' or value.hostname!='127.0.0.1' or not value.port or
                value.path or value.username or value.password or value.query or value.fragment):
            raise ValueError('loopback voice receipt required')
        self.url,self.capability=receipt['url'],receipt['capability']
        self.port=value.port
        self.lock=threading.Lock()
        self.connection=None
    def __call__(self,operation,data):
        if not self.lock.acquire(timeout=2):
            raise TimeoutError('voice transport busy')
        try:
            if self.connection is None:
                self.connection=http.client.HTTPConnection('127.0.0.1',self.port,timeout=2)
            self.connection.request('POST','/'+operation,body=json.dumps(data).encode(),headers={
                'Authorization':'Bearer '+self.capability,'Content-Type':'application/json'})
            response=self.connection.getresponse()
            result=response.read(16385)
            if len(result)>16384: raise ValueError('voice response too large')
            if response.status!=200:
                raise HTTPError(self.url+'/'+operation,response.status,response.reason,response.headers,io.BytesIO(result))
            return json.loads(result)
        except Exception:
            if self.connection is not None:self.connection.close()
            self.connection=None
            # Never automatically replay a possibly accepted turn/receipt.
            raise
        finally:
            self.lock.release()

    def close(self):
        with self.lock:
            if self.connection is not None:self.connection.close()
            self.connection=None


class TurnAssembly:
    """Bounded ephemeral turn text; never a history or memory authority."""
    def __init__(self,quiet=1.1,clock=time.monotonic,max_seconds=10):
        if not .25<=quiet<=3 or not 1<=max_seconds<=10:raise ValueError('bounded turn timing required')
        self.quiet,self.clock,self.max_seconds=quiet,clock,max_seconds
        self.clear()
    def clear(self):
        self.pending=None;self.updated=0;self.started=0
    def _release(self,now,reason,activity=0):
        row=self.pending
        row.update(boundary=reason,quiet_seconds=max(0,now-max(self.updated,activity)),
                   assembly_seconds=max(0,now-self.started))
        self.clear();return row
    def add(self,text,scope,captured_at,capture_monotonic):
        if self.pending and self.pending['scope']!=scope:self.clear()
        flushed=[];now=self.clock()
        if self.pending and len(self.pending['text'])+1+len(text)>1000:
            flushed.append(self._release(now,'text_budget'))
        # A single unusually long STT chunk is split, never discarded/truncated.
        for offset in range(0,len(text),1000):
            part=text[offset:offset+1000]
            if not self.pending:self.started=now
            previous=self.pending['text']+' ' if self.pending else ''
            fragments=(self.pending or {}).get('fragment_count',0)+1
            self.pending=dict(text=previous+part,fragment_count=fragments,scope=dict(scope),captured_at=captured_at,
                              capture_monotonic=capture_monotonic)
            self.updated=now
            if offset+1000<len(text):flushed.append(self._release(now,'text_budget'))
        return flushed
    def take(self,now,activity=0):
        if not self.pending:return None
        if now-self.started>=self.max_seconds:return self._release(now,'time_budget',activity)
        if now-max(self.updated,activity)<self.quiet:return None
        return self._release(now,'quiet',activity)

_BACKCHANNELS={'yeah','yes','yep','okay','ok','right','mhm','mm','uh huh','nice','thanks'}


class CoreVoiceAdapter:
    """Capture→bounded STT intake, independent poll and TTS/playback workers.

    channel() reads authenticated Discord receive context. transcribe/synthesize
    are existing local functions. play(pcm, callback) is the existing VC player.
    No raw audio/text is persisted by this adapter.
    """
    def __init__(self,transport,*,owner_id,channel,transcribe,synthesize,play,stop,
                 log=lambda s:None,playback_timeout=30,turn_taking=False):
        self.transport,self.owner_id,self.channel=transport,str(owner_id),channel
        self.transcribe,self.synthesize,self.play,self.stop=transcribe,synthesize,play,stop
        if type(playback_timeout) not in (int,float) or not 0<playback_timeout<=30:
            raise ValueError('bounded playback timeout required')
        self.playback_timeout=playback_timeout
        self.log=log;self.scope=None;self.binding=None;self.running=False
        self.audio_queue=asyncio.Queue(maxsize=2);self.reply_queue=asyncio.Queue(maxsize=2)
        self.tasks=[];self.current=None;self.cancelled=False
        self.recent_speech=None
        self.clock_anchor=None
        self.turn_taking=turn_taking is True
        self.turn_buffer=TurnAssembly()
        self.last_activity=0
        self.stt_busy=False

    def speech_activity(self,user):
        # Called from the receive thread: no I/O, coroutine or model work.
        if (not self.turn_taking or self.scope is None or getattr(user,'bot',True) is not False
                or str(getattr(user,'id',''))!=self.owner_id):return False
        self.last_activity=time.monotonic()
        return True

    def _cancel_local(self):
        self.cancelled=True
        try:self.stop()
        except Exception as exc:self.log('VOICE_STOP_UNAVAILABLE '+type(exc).__name__)
        while not self.reply_queue.empty(): self.reply_queue.get_nowait()

    def _adopt(self,result):
        scope=dict(connection=result['connection'],generation=result['generation'])
        if (self.scope and scope['connection']==self.scope['connection'] and
                scope['generation']<self.scope['generation']):return
        if self.scope is None or scope['connection']!=self.scope['connection']:
            self.clock_anchor=None
        stamp=result.get('server_time')
        if type(stamp) in (int,float) and math.isfinite(stamp):
            # Host send time paired with LOCAL receipt monotonic time. This
            # maps capture to a conservative host-clock lower bound: delivery
            # delay makes it older, never newer. No PC clock synchronization.
            # Windows' coarse wall-clock ticks can otherwise put a mapped
            # capture a few milliseconds ahead of the next host tick. Age it
            # conservatively by 50 ms; never relax the host's age guard.
            self.clock_anchor=(stamp-.05,time.monotonic())
        if scope!=self.scope:
            self._cancel_local();self.turn_buffer.clear()
        self.scope=scope

    async def start(self):
        if self.running:return
        self.running=True
        self.tasks=[asyncio.create_task(fn()) for fn in (self._poll,self._stt,self._speak)]
        if self.turn_taking:self.tasks.append(asyncio.create_task(self._assemble()))

    async def audio(self,pcm,user,duration,captured_at):
        # Authenticated speaker ID, never display name/transcript identity.
        if (getattr(user,'bot',True) is not False or str(getattr(user,'id',''))!=self.owner_id or
                self.scope is None or not .1<=duration<=10 or not isinstance(pcm,bytes) or
                not 0<len(pcm)<=1920000 or type(captured_at) not in (int,float) or
                not 0<=time.time()-captured_at<=20):return False
        if self.audio_queue.full():
            self.audio_queue.get_nowait();self.turn_buffer.clear()
            self.log('VOICE_CAPTURE_DROPPED queue_budget')
        capture_monotonic=time.monotonic()-(time.time()-captured_at)
        self.audio_queue.put_nowait((pcm,dict(self.scope),captured_at,capture_monotonic))
        return True

    async def _poll(self):
        while self.running:
            try:
                channel=self.channel()
                if channel is None:
                    if self.scope:
                        try:await asyncio.to_thread(self.transport,'disconnect',self.scope)
                        except Exception:pass
                    self._cancel_local();self.turn_buffer.clear();self.scope=None;self.binding=None
                else:
                    if self.scope is None or channel!=self.binding:
                        self._cancel_local()
                        self._adopt(await asyncio.to_thread(self.transport,'connect',channel))
                        self.binding=dict(channel)
                    result=await asyncio.to_thread(self.transport,'poll',dict(self.scope))
                    self._adopt(result)
                    if self.scope!=dict(connection=result['connection'],generation=result['generation']):continue
                    for reply in result.get('replies',[]):
                        if not self.reply_queue.full():self.reply_queue.put_nowait((dict(self.scope),reply))
                        else:await self._receipt(dict(self.scope),reply,'failed')
            except Exception as exc:
                self._cancel_local();self.turn_buffer.clear();self.scope=None;self.binding=None
                self.log('VOICE_TRANSPORT_UNAVAILABLE '+type(exc).__name__)
            await asyncio.sleep(.1)

    async def _stt(self):
        while self.running:
            pcm,scope,captured,capture_monotonic=await self.audio_queue.get()
            try:
                if self.scope is None or scope['connection']!=self.scope['connection']:continue
                self.stt_busy=True
                text=await asyncio.to_thread(self.transcribe,pcm)
                if not isinstance(text,str) or not text.strip():continue
                is_stop=stop_text(text)
                if self.scope is None or scope['connection']!=self.scope['connection']:continue
                if scope!=self.scope and not is_stop:continue
                if not is_stop and self.echo(text):
                    self.log('VOICE_ECHO_DROPPED');continue
                if is_stop:
                    self._cancel_local();self.turn_buffer.clear()
                elif self.turn_taking:
                    normalized=' '.join(re.findall(r'\w+',text.casefold()))
                    if (not self.turn_buffer.pending and normalized not in _BACKCHANNELS and
                            (self.current is not None or not self.reply_queue.empty())):
                        previous=dict(self.scope)
                        result=await asyncio.to_thread(self.transport,'interrupt',previous)
                        self._adopt(result)
                        # Only carry captures across THIS known local speech interruption.
                        # Never across a reconnect, external generation change or world reset.
                        if self.scope==dict(connection=previous['connection'],generation=previous['generation']+1):
                            queued=[]
                            while not self.audio_queue.empty():
                                item=self.audio_queue.get_nowait()
                                if item[1]==previous and item[3]>=capture_monotonic:
                                    item=(item[0],dict(self.scope),item[2],item[3])
                                queued.append(item)
                            for item in queued:self.audio_queue.put_nowait(item)
                        else:continue
                    for row in self.turn_buffer.add(text.strip(),self.scope,captured,capture_monotonic):
                        await self._submit(row['text'],row['scope'],row['captured_at'],row['capture_monotonic'],row)
                    continue
                await self._submit(text.strip(),dict(self.scope),captured,capture_monotonic)
            except Exception as exc:self.log('VOICE_TURN_REFUSED '+type(exc).__name__)
            finally:self.stt_busy=False

    async def _submit(self,text,scope,captured,capture_monotonic,boundary=None):
        if scope!=self.scope:return
        host_captured=captured
        if self.clock_anchor is not None:
            host_time,local_monotonic=self.clock_anchor
            host_captured=host_time+(capture_monotonic-local_monotonic)
        request_id=str(uuid.uuid4())
        result=await asyncio.to_thread(self.transport,'turn',dict(scope,
            request_id=request_id,author_id=self.owner_id,is_bot=False,
            text=text,captured_at=host_captured))
        self._adopt(result)
        if boundary:
            self.log('VOICE_TURN_BOUNDARY '+json.dumps(dict(request_id=request_id,
                reason=boundary['boundary'],quiet_seconds=round(boundary['quiet_seconds'],3),
                assembly_seconds=round(boundary['assembly_seconds'],3),characters=len(text),
                fragment_count=boundary['fragment_count'])))

    async def _assemble(self):
        while self.running:
            if not self.stt_busy and self.audio_queue.empty():
                row=self.turn_buffer.take(time.monotonic(),activity=self.last_activity)
                if row:
                    try:await self._submit(row['text'],row['scope'],row['captured_at'],row['capture_monotonic'],row)
                    except Exception as exc:self.log('VOICE_TURN_REFUSED '+type(exc).__name__)
            await asyncio.sleep(.05)

    def echo(self,text):
        if self.recent_speech is None:return False
        previous,stamp=self.recent_speech
        if self.current is None and not 0<=time.time()-stamp<=2:return False
        normalize=lambda value:' '.join(re.findall(r'\w+',value.casefold()))
        current,previous=normalize(text),normalize(previous)
        return bool(current and (SequenceMatcher(None,current,previous).ratio()>=.86 or
                    (len(current)>=12 and current in previous)))

    async def _receipt(self,scope,reply,state):
        try:
            await asyncio.to_thread(self.transport,'playback',dict(scope,
                reply_id=reply['reply_id'],state=state))
        except Exception as exc:self.log('VOICE_RECEIPT_UNAVAILABLE '+type(exc).__name__)

    async def _speak(self):
        while self.running:
            scope,reply=await self.reply_queue.get()
            if scope!=self.scope:continue
            started=False;self.cancelled=False
            try:
                pcm=await asyncio.to_thread(self.synthesize,reply['text'])
                if scope!=self.scope or self.cancelled:
                    await self._receipt(scope,reply,'cancelled');continue
                loop=asyncio.get_running_loop();done=asyncio.Event();errors=[]
                def after(error):
                    if error:errors.append(type(error).__name__)
                    loop.call_soon_threadsafe(done.set)
                self.current=(scope,reply)
                self.recent_speech=(reply["text"],time.time())
                # Do not start an obsolete answer over an unfinished owner turn.
                if self.turn_taking and (self.turn_buffer.pending or self.stt_busy or
                        time.monotonic()-self.last_activity<self.turn_buffer.quiet):
                    await self._receipt(scope,reply,'cancelled');continue
                self.play(pcm,after);started=True
                await self._receipt(scope,reply,'started')
                await asyncio.wait_for(done.wait(),self.playback_timeout)
                state=('cancelled' if self.cancelled or scope!=self.scope else
                       'failed' if errors else 'completed')
                self.recent_speech=(reply['text'],time.time())
                await self._receipt(scope,reply,state)
            except asyncio.TimeoutError:
                self._cancel_local()
                self.log('VOICE_PLAYBACK_TIMEOUT')
                await self._receipt(scope,reply,'timeout')
            except Exception:
                state='cancelled' if self.cancelled or scope!=self.scope else 'failed'
                self._cancel_local()
                await self._receipt(scope,reply,state)
            finally:self.current=None

    async def close(self):
        self.running=False;self._cancel_local()
        if self.scope:
            try:await asyncio.to_thread(self.transport,'disconnect',dict(self.scope))
            except Exception:pass
        for task in self.tasks:task.cancel()
        await asyncio.gather(*self.tasks,return_exceptions=True)
        self.scope=None
        if hasattr(self.transport,'close'):
            await asyncio.to_thread(self.transport.close)
