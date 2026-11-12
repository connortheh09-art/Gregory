"""Explicit owner-selected private source records, not fabricated episodes."""
import re
from .inbox import snowflake

def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS inbox_pins(
        bot_id TEXT,channel_id TEXT,peer_id TEXT,label TEXT,message_id TEXT,
        revision INTEGER,authorization_message_id TEXT,
        PRIMARY KEY(bot_id,channel_id,peer_id,label))''')

def execute(core,p):
    from .inbox import execute as inbox
    required={'bot_id','channel_id','peer_id','label','message_id','expected_revision','authorization_message_id'}
    if not isinstance(p,dict) or set(p)!=required:raise ValueError('explicit owner pin fields required')
    if (not isinstance(p['label'],str) or not re.fullmatch(r'[a-z][a-z_.-]{0,47}',p['label']) or
            type(p['expected_revision']) is not int or not 0<=p['expected_revision']<=1000):
        raise ValueError('bounded revisioned pin required')
    for k in ('message_id','authorization_message_id'):snowflake(p[k])
    scope={k:p[k] for k in ('bot_id','channel_id','peer_id')}
    inbox(core,dict(scope,operation='context',surface='dm')) # existing identity/channel guard
    row=core.db.execute('SELECT content FROM inbox_messages WHERE bot_id=? AND channel_id=? AND peer_id=? AND message_id=?',
        (*scope.values(),p['message_id'])).fetchone()
    if row is None or not 1<=len(row['content'])<=500:raise ValueError('bounded committed owner source required')
    keys=(*scope.values(),p['label'])
    old=core.db.execute('SELECT message_id,revision FROM inbox_pins WHERE bot_id=? AND channel_id=? AND peer_id=? AND label=?',keys).fetchone()
    if old and old['message_id']==p['message_id']:
        return dict(label=p['label'],message_id=p['message_id'],revision=old['revision'],duplicate=True,visibility='dm_only')
    if (old['revision'] if old else 0)!=p['expected_revision']:raise ValueError('pin revision changed')
    if old is None and core.db.execute('SELECT count(*) FROM inbox_pins WHERE bot_id=? AND channel_id=? AND peer_id=?',tuple(scope.values())).fetchone()[0]>=4:
        raise ValueError('private pin capacity reached')
    revision=p['expected_revision']+1
    with core.db:
        core.db.execute('INSERT OR REPLACE INTO inbox_pins VALUES(?,?,?,?,?,?,?)',
            (*keys,p['message_id'],revision,p['authorization_message_id']))
        core._event('decision',dict(type='owner_private_inbox_pin',**p,revision=revision,visibility='dm_only'),source='owner')
    return dict(label=p['label'],message_id=p['message_id'],revision=revision,duplicate=False,visibility='dm_only')

def records(core,scope):
    rows=core.db.execute('''SELECT p.label,p.message_id,m.content FROM inbox_pins p
        JOIN inbox_messages m ON m.bot_id=p.bot_id AND m.channel_id=p.channel_id
        AND m.peer_id=p.peer_id AND m.message_id=p.message_id
        WHERE p.bot_id=? AND p.channel_id=? AND p.peer_id=? ORDER BY p.label LIMIT 4''',
        (scope['bot_id'],scope['channel_id'],scope['author_id'])).fetchall()
    return [dict(label=r['label'],message_id=r['message_id'],text=r['content']) for r in rows]
