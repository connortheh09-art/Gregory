"""Foreground, time-limited Discord runner. No network without --connect.

Live use is qualification/owner-approval bound; this is not a service installer.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from gregory_core.runtime import Core,LMStudioProvider
from gregory_core.control_http import ControlServer
from gregory_core.discord_text import DiscordTextAdapter,GregoryCoreClient,Message
from lms_embedder import build_embedder

CONFIG_KEYS={'core_root','lm_endpoint','lm_model','guild_id','channel_id','bot_id','users','bots',
    'embed_endpoint','embed_model','embed_revision'}


def validate(config):
    if set(config)!=CONFIG_KEYS:
        raise ValueError('explicit Core/model/Discord config required; no token in config')
    for field in ('guild_id','channel_id','bot_id'):
        if not isinstance(config[field],str) or not re.fullmatch(r'[0-9]{1,20}',config[field]):
            raise ValueError('Discord IDs must be numeric strings')
    for field in ('users','bots'):
        if not isinstance(config[field],list) or len(config[field])>8 or any(
            not isinstance(v,str) or not re.fullmatch(r'[0-9]{1,20}',v) for v in config[field]):
            raise ValueError('bounded participant IDs required')
    if not config['users'] or config['bot_id'] in config['bots']:raise ValueError('owner user and distinct bot required')
    root=Path(config['core_root']).absolute()
    if root.resolve()!=root or not all((root/f).is_file() for f in ('core.sqlite3','episodes.sqlite3')):
        raise ValueError('existing initialized authoritative Core root required; never create another character')
    LMStudioProvider(config['lm_endpoint'],config['lm_model'])
    for field in ('embed_endpoint','embed_model','embed_revision'):
        if not isinstance(config[field],str) or not config[field].strip():
            raise ValueError('explicit pinned embedder required; keyword-only is not a lane')
    # Constructing the embedder validates the pin without any network request.
    embedder(config)
    return root


def embedder(config):
    return build_embedder(config['embed_endpoint'],model_id=config['embed_model'],
        revision=config['embed_revision'])


async def run(config,minutes):
    # Lazy import: isolated tests and --check need neither SDK nor credentials.
    import discord
    token=os.environ.get('DISCORD_BOT_TOKEN')
    if not token:raise ValueError('DISCORD_BOT_TOKEN environment secret required')
    core=observer=client=adapter=None
    try:
        core=Core(validate(config),provider=LMStudioProvider(config['lm_endpoint'],config['lm_model']),
            embedder=embedder(config)).start()
        observer=ControlServer(core).start()
        intents=discord.Intents.none()
        intents.guilds=True;intents.guild_messages=True;intents.message_content=True
        client=discord.Client(intents=intents,allowed_mentions=discord.AllowedMentions.none())
        class Transport:
            async def send(self,channel,body,*,reply_to,allowed_mentions):
                if allowed_mentions:raise ValueError('mentions forbidden')
                target=client.get_channel(int(channel))
                if target is None:raise ConnectionError('allowlisted channel unavailable')
                message=await target.send(body,reference=discord.MessageReference(
                    message_id=int(reply_to),channel_id=int(channel),guild_id=int(config['guild_id']),fail_if_not_exists=False),
                    allowed_mentions=discord.AllowedMentions.none(),mention_author=False,nonce=int(reply_to))
                return str(message.id)
        # A cold local 12B spends far longer than the 5s rewrite default; an abandoned
        # rewrite keeps Core's single model slot and the answer think is refused.
        adapter=DiscordTextAdapter(GregoryCoreClient(core),Transport(),guild_id=config['guild_id'],
            channel_id=config['channel_id'],bot_id=config['bot_id'],users=config['users'],bots=config['bots'],
            model_seconds=25,retrieval_seconds=15,fixture=False).start()
        adapter.disconnect()
        @client.event
        async def on_ready():
            if str(client.user.id)!=config['bot_id']:
                await client.close();return
            adapter.reconnect()
            status=core.call('status')
            print(json.dumps(dict(type='discord_ready',bot_id=config['bot_id'],core_run_id=core.run_id,
                control_url='http://127.0.0.1:'+str(observer.port),supervised_minutes=minutes,
                embedding=status['embedding'],memory_count=status['memory_count'])),flush=True)
        @client.event
        async def on_disconnect():adapter.disconnect()
        @client.event
        async def on_resumed():
            if str(client.user.id)==config['bot_id']:adapter.reconnect()
        @client.event
        async def on_message(message):
            if message.guild is None:return
            parent=getattr(message.reference,'resolved',None) if message.reference else None
            # Bot reply with an unresolved parent is ambiguous: fail closed.
            reply_own=bool(message.reference and message.author.bot and
                (parent is None or str(getattr(getattr(parent,'author',None),'id',''))==config['bot_id']))
            future=adapter.offer(Message(str(message.guild.id),str(message.channel.id),str(message.id),
                str(message.author.id),message.content,message.created_at.timestamp(),bot=message.author.bot,
                webhook=message.webhook_id is not None,reply_to_own=reply_own))
            if future is not None:
                result=await future
                print(json.dumps(dict(type='discord_turn',message_id=str(message.id),
                    correlation_id=result.get('correlation_id'),state=result.get('state'),
                    error_category=result.get('error_category'))),flush=True)
        print(json.dumps(dict(type='discord_supervised_start',core_run_id=core.run_id,
            character_id=core.call('status')['profile']['character_id'])),flush=True)
        await asyncio.wait_for(client.start(token,reconnect=True),minutes*60)
    except asyncio.TimeoutError:pass
    finally:
        if adapter is not None:adapter.disconnect()
        errors=[]
        # Cleanup failures cannot starve Core stop or conceal an incomplete run.
        for name,close,seconds in (('discord',client.close if client else None,5),('adapter',adapter.close if adapter else None,30)):
            if close is None:continue
            try:await asyncio.wait_for(close(),seconds)
            except Exception as exc:errors.append(dict(stage=name,error_category=type(exc).__name__))
        try:
            if observer is not None:observer.close()
        except Exception as exc:errors.append(dict(stage='observer',error_category=type(exc).__name__))
        try:result=core.call('stop',timeout=5) if core is not None else {'stopped':True,'not_started':True}
        except Exception as exc:
            result={'stopped':False,'error_category':type(exc).__name__}
            errors.append(dict(stage='core',error_category=type(exc).__name__))
        if core is not None:core.thread.join(5)
        print(json.dumps(dict(type='discord_supervised_stop',errors=errors,**result)),flush=True)
        if errors:raise RuntimeError('Discord supervised cleanup incomplete')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--connect',action='store_true',help='requires approved supervised live window')
    parser.add_argument('--minutes',type=float,default=10)
    args=parser.parse_args()
    if not 0<args.minutes<=20:parser.error('supervised window must be 0–20 minutes')
    config=json.loads(args.config.read_text())
    validate(config)
    if not args.connect:
        print('Configuration validated; no Core start, model request or Discord connection.')
        return 0
    asyncio.run(run(config,args.minutes))
    return 0


if __name__=='__main__':raise SystemExit(main())
