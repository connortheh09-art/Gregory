"""Scheduled DM-only intake. No model calls, replies, tool execution or VC access."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import time
import sys
from urllib.request import Request, urlopen
from urllib.parse import urlsplit


class Intake:
    def __init__(self, receipt):
        parsed = urlsplit(receipt['url'])
        if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or not parsed.port
                or parsed.path not in ('', '/') or parsed.query or parsed.fragment or parsed.username):
            raise ValueError('loopback intake required')
        self.url = receipt['url'].rstrip('/')+'/inbox'
        self.token = receipt['capability']

    def call(self, payload):
        request = Request(self.url, data=json.dumps(payload).encode(),
                          headers={'Authorization': 'Bearer '+self.token, 'Content-Type': 'application/json'})
        with urlopen(request, timeout=8) as response:
            return json.load(response)


async def check_channel(intake, channel, bot_id, peer_id, media_root=None):
    """Oldest-first bounded catch-up; cursor advances only after Core commits."""
    scope = dict(bot_id=bot_id, channel_id=str(channel.id), peer_id=peer_id)
    state = await asyncio.to_thread(intake.call, dict(scope, operation='bind'))
    if media_root:
        await process_media(intake, scope, media_root)
    inserted = 0
    for page in range(4):
        # Lazy import lets fixtures use a fake channel with integer cursors.
        after = type('After', (), {'id': int(state['cursor'])})()
        messages = []
        async for message in channel.history(limit=25, after=after, oldest_first=True):
            if message.guild is not None or getattr(message, 'webhook_id', None) is not None:
                raise ValueError('non-DM source refused')
            item = dict(message_id=str(message.id), author_id=str(message.author.id), content=message.content)
            if media_root:
                item['attachments'] = [dict(attachment_id=str(a.id), url=a.url, filename=a.filename,
                                            size=a.size, content_type=a.content_type) for a in message.attachments]
            messages.append(item)
        if not messages:
            break
        state = await asyncio.to_thread(intake.call, dict(scope, operation='batch', messages=messages))
        inserted += state['inserted']
        if media_root:
            await process_media(intake, scope, media_root)
        print(json.dumps(dict(type='inbox.scheduled_receipt', channel_id=scope['channel_id'],
                              inserted=state['inserted'], duplicates=state['duplicates'],
                              correlation_ids=state['correlation_ids'], cursor=state['cursor'])), flush=True)
        if len(messages) < 25:
            break
    return inserted


async def process_media(intake, scope, root):
    from gregory_core.inbox_media import store, preview
    pending = await asyncio.to_thread(intake.call, dict(scope, operation='media_pending'))
    for descriptor in pending['attachments']:
        message_id = descriptor['message_id']
        attachment = {k:v for k,v in descriptor.items() if k != 'message_id'}
        source = dict(scope, message_id=message_id, attachment_id=attachment['attachment_id'])
        try:
            saved = await asyncio.to_thread(store, root, attachment)
            await asyncio.to_thread(preview, root, saved['sha256'], saved['size'])
            result = await asyncio.to_thread(intake.call, dict(source, operation='media_commit', sha256=saved['sha256'], size=saved['size']))
            print(json.dumps(dict(type='inbox.attachment_ready', message_id=message_id,
                                  sha256=saved['sha256'], reused_object=saved['reused_object'],
                                  preview_frames=result['preview_frames'])), flush=True)
        except Exception as exc:
            await asyncio.to_thread(intake.call, dict(source, operation='media_failed', error_category=type(exc).__name__))
            print(json.dumps(dict(type='inbox.attachment_failed', message_id=message_id,
                                  error_category=type(exc).__name__)), flush=True)


async def run(args):
    import discord
    receipt = json.loads(args.receipt.read_text(encoding='utf8'))
    if receipt['bot_id'] != args.bot_id or set(receipt['users']) != set(args.users):
        raise ValueError('explicit bot/participant binding required')
    intake = Intake(receipt)
    token = args.token_file.read_text(encoding='utf-8-sig').strip()
    if token.startswith('Bot '):
        token = token[4:].strip()
    intents = discord.Intents.none()
    intents.dm_messages = True
    client = discord.Client(intents=intents, allowed_mentions=discord.AllowedMentions.none())
    ready = asyncio.Event()

    @client.event
    async def on_ready():
        if str(client.user.id) != args.bot_id:
            await client.close(); return
        ready.set()
        print(json.dumps(dict(type='inbox.discord_ready', bot_id=args.bot_id,
                              interval_seconds=args.interval, dm_messages=True, automatic_replies=False)), flush=True)

    task = asyncio.create_task(client.start(token, reconnect=True))
    try:
        await asyncio.wait_for(ready.wait(), 30)
        await asyncio.sleep(args.initial_delay)
        deadline = time.monotonic()+args.minutes*60
        while time.monotonic() < deadline and not client.is_closed():
            if not client.is_ready():
                await asyncio.sleep(2); continue
            print(json.dumps(dict(type='inbox.scheduled_check', at=time.time())), flush=True)
            for peer in args.users:
                try:
                    user = await client.fetch_user(int(peer))
                    channel = await user.create_dm()
                    await check_channel(intake, channel, args.bot_id, peer, args.media_root)
                except Exception as exc:
                    print(json.dumps(dict(type='inbox.check_failed', peer_id=peer,
                                          error_category=type(exc).__name__)), flush=True)
            await asyncio.sleep(min(args.interval, max(0, deadline-time.monotonic())))
    finally:
        await client.close()
        try:
            await asyncio.wait_for(task, 5)
        except asyncio.TimeoutError:
            task.cancel()
        print(json.dumps(dict(type='inbox.discord_closed')), flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--receipt', type=Path, required=True)
    p.add_argument('--token-file', type=Path, required=True)
    p.add_argument('--bot-id', required=True)
    p.add_argument('--users', nargs='+', required=True)
    p.add_argument('--interval', type=int, default=300)
    p.add_argument('--initial-delay', type=int, default=60)
    p.add_argument('--minutes', type=int, default=10)
    p.add_argument('--media-root', type=Path)
    p.add_argument('--connect', action='store_true')
    args = p.parse_args()
    if not args.connect or not 120 <= args.interval <= 600 or not 1 <= args.initial_delay <= 300 or not 1 <= args.minutes <= 30:
        p.error('explicit bounded supervised connection required')
    asyncio.run(run(args))


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    main()
