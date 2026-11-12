"""Durable turn metadata plus ephemeral dialogue; NOT episodic evidence.

Raw context fields are validated in transit but never stored in the turn table
or event payloads. Core owns the RAM window; acceptance alone appends to it.
"""
import hashlib
import json
import re
import time
import uuid


class ConversationConflict(ValueError): pass


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS conversation_turns(
        source_key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
        correlation_id TEXT UNIQUE NOT NULL, state TEXT NOT NULL,
        metadata TEXT NOT NULL, outbound_id TEXT)''')


def execute(core,p):
    if set(p)-{'operation','guild_id','channel_id','message_id','author_id','content_sha256',
              'source_at','received_at','trigger','state','outbound_id','response_sha256','error_category','fixture',
              'context_user','context_reply'}:
        raise ValueError('conversation metadata fields only')
    ids=[p[k] for k in ('guild_id','channel_id','message_id')]
    if any(not isinstance(v,str) or not re.fullmatch(r'[0-9]{1,20}',v) for v in ids):
        raise ValueError('Discord source identity required')
    key='discord:'+':'.join(ids)
    row=core.db.execute('SELECT * FROM conversation_turns WHERE source_key=?',(key,)).fetchone()
    operation=p['operation']
    context_fields={'context_user','context_reply'} & set(p)
    if context_fields and (operation!='transition' or p.get('state')!='accepted' or
                           context_fields!={'context_user','context_reply'}):
        raise ValueError('dialogue requires a complete accepted exchange')
    if operation=='reserve':
        if type(p.get('fixture',False)) is not bool:raise ValueError('explicit fixture origin required')
        if not re.fullmatch(r'[a-f0-9]{64}',p['content_sha256']):raise ValueError('content digest required')
        if not isinstance(p['author_id'],str) or not re.fullmatch(r'[0-9]{1,20}',p['author_id']):
            raise ValueError('author identity required')
        if p['trigger'] not in ('mention','prefix'):raise ValueError('explicit trigger required')
        for name in ('received_at','source_at'):
            if type(p[name]) not in (int,float) or not 0<p[name]<=time.time()+60:
                raise ValueError('source/receipt timestamp required')
        fingerprint=hashlib.sha256(json.dumps([p['author_id'],p['content_sha256']],separators=(',',':')).encode()).hexdigest()
        if row:
            if row['fingerprint']!=fingerprint:raise ConversationConflict('Discord identity/content conflict')
            return dict(row,metadata=json.loads(row['metadata']),duplicate=True)
        correlation=str(uuid.uuid5(uuid.NAMESPACE_URL,key))
        metadata={k:p[k] for k in ('guild_id','channel_id','message_id','author_id','content_sha256','source_at','received_at','trigger')}
        metadata['fixture']=p.get('fixture',False)
        context_error=None
        try:dialogue=core.dialogue.snapshot(metadata)
        except Exception as exc:
            dialogue=[];context_error=type(exc).__name__
        previous=core.command_context;core.command_context=correlation
        try:
            try:memory_context=core.memory_context(core.dialogue.scope(metadata))
            except Exception as exc:
                memory_context=dict(state='unavailable',reason=type(exc).__name__)
            with core.db:
                core.db.execute('INSERT INTO conversation_turns VALUES(?,?,?,?,?,NULL)',
                    (key,fingerprint,correlation,'received',json.dumps(metadata)))
                core._event('conversation',dict(type='conversation.received',**metadata,
                    context_error_category=context_error,
                    memory_context_state=memory_context['state'],
                    qualification='conversation metadata; not world observation or episodic evidence'),source='discord_text',fixture=metadata['fixture'])
        finally:core.command_context=previous
        row=core.db.execute('SELECT * FROM conversation_turns WHERE source_key=?',(key,)).fetchone()
        return dict(row,metadata=metadata,duplicate=False,dialogue_context=dialogue,
                    context_error_category=context_error,memory_context=memory_context)
    if row is None:raise ValueError('unknown conversation identity')
    if operation=='get':return dict(row,metadata=json.loads(row['metadata']))
    if operation!='transition':raise ValueError('unknown conversation operation')
    state=p['state']
    edges={'received':{'intent','error','cancelled'},'intent':{'sending','error','cancelled'},
           'sending':{'accepted','unknown'}}
    if state not in edges.get(row['state'],set()):raise ValueError('invalid conversation transition')
    outbound=p.get('outbound_id')
    if state=='accepted' and (not isinstance(outbound,str) or not re.fullmatch(r'[0-9]{1,20}',outbound)):
        raise ValueError('Discord acceptance message id required')
    digest=p.get('response_sha256')
    if digest is not None and not re.fullmatch(r'[a-f0-9]{64}',digest):raise ValueError('response digest required')
    metadata=json.loads(row['metadata'])
    if context_fields:
        user,reply=p['context_user'],p['context_reply']
        if (not isinstance(user,str) or not 1<=len(user)<=1800 or
            not isinstance(reply,str) or not 1<=len(reply)<=1800):
            raise ValueError('bounded dialogue text required')
        if (hashlib.sha256(user.encode('utf8')).hexdigest()!=metadata['content_sha256'] or
            hashlib.sha256(reply.encode('utf8')).hexdigest()!=digest):
            raise ConversationConflict('dialogue text does not match accepted digests')
    error=p.get('error_category')
    if state in ('error','cancelled','unknown') and not error:
        raise ValueError('typed error category required for failed/uncertain outcome')
    if error is not None and (not isinstance(error,str) or not re.fullmatch(r'[A-Za-z0-9_.]{1,80}',error)):
        raise ValueError('typed error category required')
    previous=core.command_context;core.command_context=row['correlation_id']
    try:
        with core.db:
            core.db.execute('UPDATE conversation_turns SET state=?,outbound_id=? WHERE source_key=?',(state,outbound,key))
            core._event('outcome' if state in ('accepted','unknown','error','cancelled') else 'conversation',
                dict(type='conversation.'+state,source_key=key,outbound_id=outbound,response_sha256=digest,
                    error_category=error,qualification='Discord API acceptance is not client delivery'),
                source='discord_text',fixture=json.loads(row['metadata']).get('fixture',False))
        if context_fields:
            try:core.dialogue.append(metadata,key,user,reply)
            except Exception as exc:
                # The API acceptance is still true if working context is lost.
                with core.db:
                    core._event('conversation',dict(type='conversation.context_unavailable',
                        source_key=key,error_category=type(exc).__name__,stage='append'),
                        source='discord_text',fixture=metadata.get('fixture',False))
    finally:core.command_context=previous
    return dict(source_key=key,correlation_id=row['correlation_id'],state=state,outbound_id=outbound,error_category=error)
