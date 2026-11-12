#!/usr/bin/env python3
"""Isolated Gregory Core control; never manages installed game/voice/model services."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from gregory_core.runtime import Core, FixtureProvider
from gregory_core.control_http import ControlServer


def rpc(control, path, data=None, *, adapter=False):
    config=json.loads(Path(control).read_text(encoding='utf8'))
    headers={'Content-Type':'application/json'}
    if data is not None:
        headers['Authorization']='Bearer '+config['adapter_token' if adapter else 'owner_token']
    body=None if data is None else json.dumps(data).encode()
    with urlopen(Request(config['url']+path,data=body,headers=headers),timeout=40) as response:
        return json.load(response)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    serve=sub.add_parser('serve'); serve.add_argument('--root',required=True)
    serve.add_argument('--port',type=int,default=0)
    serve.add_argument('--fixture-provider',action='store_true')
    for command in ('status','stop','lookup','goals','think','import'):
        p=sub.add_parser(command); p.add_argument('--control',required=True)
        if command in ('lookup','think'): p.add_argument('text')
        if command=='goals': p.add_argument('text',nargs='*')
        if command=='import': p.add_argument('--file',required=True)
    adapter=sub.add_parser('fixture-adapter'); adapter.add_argument('--control',required=True)
    adapter.add_argument('--kind',choices=['game','voice'],required=True)
    adapter.add_argument('--seconds',type=float,default=3)
    executor=sub.add_parser('fixture-executor',help='Explicit local fixture marker, never a game action')
    executor.add_argument('--control',required=True)
    executor.add_argument('--root',required=True)
    executor.add_argument('--correlation',required=True)
    args=parser.parse_args()
    if args.command=='serve':
        # Live routing is not part of this slice. The LMStudioProvider seam is
        # unit-tested separately; a reviewed future adapter may select it.
        provider=FixtureProvider() if args.fixture_provider else None
        core=Core(args.root,provider=provider).start()
        server=ControlServer(core,port=args.port).start()
        path=core.root/'control.json'
        temporary=path.with_suffix('.tmp')
        with temporary.open('w',encoding='utf8') as handle:
            os.chmod(temporary,0o600)
            json.dump(server.control_receipt(),handle); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary,path)
        print(json.dumps({'url':server.url,'control_file':str(path),'pid':os.getpid(),
                          'mode':'isolated-prototype','provider':provider.name if provider else 'not-connected'}),flush=True)
        try:
            core.finished.wait()
        except KeyboardInterrupt:
            core.call('stop')
        finally:
            server.close()
            core.thread.join(5)
        return 1 if core.failure else 0
    if args.command=='fixture-executor':
        import hashlib
        import uuid
        from urllib.parse import quote
        uuid.UUID(args.correlation)
        chain=rpc(args.control,'/api/correlation?id='+quote(args.correlation))['events']
        if not any(e['kind']=='decision' and e['origin']=='fixture' and
                   (e['payload'].get('intent') or {}).get('kind')=='fixture-marker' for e in chain):
            raise ValueError('matching fixture decision required; not a general dispatcher')
        target=Path(args.root).absolute()
        if target.resolve()!=target:raise ValueError('real private fixture output directory required')
        target.mkdir(mode=0o700)  # fresh root; refuses reusing an existing target
        marker=target/'fixture-marker.txt'
        with marker.open('xb') as handle:
            handle.write(b'FIXTURE ONLY - not a live Gregory action\n');handle.flush();os.fsync(handle.fileno())
        result=dict(origin='fixture',executor_pid=os.getpid(),marker_exists=marker.is_file(),
                    marker_sha256=hashlib.sha256(marker.read_bytes()).hexdigest())
        session='fixture-executor-'+str(uuid.uuid4())
        data=dict(kind='game',session=session,event='connect',fixture=True,pid=os.getpid())
        rpc(args.control,'/api/adapter',data,adapter=True)
        try:
            rpc(args.control,'/api/adapter',dict(data,event='event',category='outcome',
                correlation_id=args.correlation,executor='fixture-marker-executor',data=result),adapter=True)
        finally:
            rpc(args.control,'/api/adapter',dict(data,event='disconnect'),adapter=True)
        print(json.dumps(result));return 0
    if args.command=='fixture-adapter':
        import uuid
        session='fixture-'+str(uuid.uuid4())
        data={'kind':args.kind,'session':session,'event':'connect','pid':os.getpid(),'fixture':True}
        rpc(args.control,'/api/adapter',data,adapter=True)
        end=time.monotonic()+min(max(args.seconds,.1),30)
        try:
            while time.monotonic()<end:
                rpc(args.control,'/api/adapter',dict(data,event='heartbeat'),adapter=True)
                time.sleep(.25)
        finally:
            rpc(args.control,'/api/adapter',dict(data,event='disconnect'),adapter=True)
        print(json.dumps({'fixture_adapter':args.kind,'origin':'fixture','session':session,'disconnected':True}))
        return 0
    paths={'status':'/api/status','stop':'/api/stop','lookup':'/api/memory',
           'goals':'/api/goals','think':'/api/think','import':'/api/import'}
    if args.command=='lookup':
        from urllib.parse import quote
        result=rpc(args.control,paths['lookup']+'?q='+quote(args.text))
    else:
        data=None if args.command=='status' else {} if args.command=='stop' else \
            {'goals':args.text} if args.command=='goals' else {'prompt':args.text} if args.command=='think' else \
            json.loads(Path(args.file).read_text(encoding='utf8'))
        result=rpc(args.control,paths[args.command],data)
    print(json.dumps(result,ensure_ascii=False))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
