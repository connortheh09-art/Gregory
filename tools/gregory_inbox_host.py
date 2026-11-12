"""Bounded foreground inbox host on the existing sole-authority Core root."""
import argparse,json,os,sqlite3,sys,time
from pathlib import Path
from contextlib import closing
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gregory_core.runtime import Core
from gregory_core.inbox_http import InboxServer

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--core-root',type=Path,required=True);p.add_argument('--receipt',type=Path,required=True)
 p.add_argument('--bot-id',required=True);p.add_argument('--users',nargs='+',required=True)
 p.add_argument('--after-id',required=True);p.add_argument('--seconds',type=int,default=900)
 p.add_argument('--media-enabled',action='store_true')
 a=p.parse_args()
 if not 60<=a.seconds<=1800:raise ValueError('bounded test window required')
 root=a.core_root.absolute()
 if not all((root/n).is_file() for n in ('core.sqlite3','episodes.sqlite3')):raise ValueError('existing authoritative root required')
 stamp=str(int(time.time()));backup=a.receipt.parent/('backup-'+stamp);backup.mkdir()
 for name in ('core.sqlite3','episodes.sqlite3'):
  with closing(sqlite3.connect((root/name).as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(backup/name)) as dst:
   src.backup(dst)
   if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('backup integrity')
 core=server=None
 try:
  core=Core(root,inbox_config=dict(bot_id=a.bot_id,users=a.users,after_id=a.after_id,media_enabled=a.media_enabled)).start()
  if core.call('status')['profile']['character_id']!='99f51369-64a2-4941-8c60-5d272194be88':raise RuntimeError('authoritative character mismatch')
  server=InboxServer(core,18667).start()
  receipt=dict(url='http://127.0.0.1:18667',capability=server.token,bot_id=a.bot_id,users=a.users,
    core_run_id=core.run_id,pid=os.getpid(),expires_at=time.time()+a.seconds)
  with a.receipt.open('x',encoding='utf8') as f:json.dump(receipt,f)
  print(json.dumps(dict(type='inbox.core_ready',core_run_id=core.run_id,pid=os.getpid(),seconds=a.seconds,port=server.port)),flush=True)
  deadline=time.monotonic()+a.seconds
  while time.monotonic()<deadline and not a.receipt.with_suffix('.stop').exists():time.sleep(.5)
 finally:
  if server:server.close()
  if core and core.accepting:
   result=core.call('stop',timeout=8);core.thread.join(5)
   print(json.dumps(dict(type='inbox.core_stopped',**result)),flush=True)
if __name__=='__main__':main()
