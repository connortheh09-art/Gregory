"""Explicit isolated Windows probe. No bot, game launch, service or durable memory saves."""
import argparse
import base64
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'deployments/oldpc')]
from gregory_core.runtime import Core,LMStudioProvider
from gregory_core.screen import ScreenBuffer,CaptureLoop

def main():
 p=argparse.ArgumentParser()
 p.add_argument('--root',required=True,help='New isolated test root, never authoritative Core root')
 p.add_argument('--endpoint',required=True)
 p.add_argument('--model',required=True)
 p.add_argument('--persona',required=True,help='Read-only approved persona text')
 p.add_argument('--prompt',default='What would you like to do next in the game?')
 a=p.parse_args()
 root=Path(a.root).resolve()
 if root.exists():raise ValueError('probe root must not already exist')
 provider=LMStudioProvider(a.endpoint,a.model,temperature=1)
 url=urlsplit(a.endpoint)
 with urlopen(url.scheme+'://'+url.netloc+'/api/v1/models',timeout=5) as response:
  models=json.load(response).get('models',[])
 if not any(m.get('key')==a.model and m.get('loaded_instances') for m in models):
  print(json.dumps(dict(status='model_unloaded',started=False)));return
 persona=Path(a.persona).read_text(encoding='utf-8')
 if not 1<=len(persona)<=8192:raise ValueError('bounded persona required')
 from greg_vision_helper import capture_game
 # First foreground check before creating an isolated Core or model request.
 started=time.monotonic()
 frame,stamp=capture_game()
 buffer=ScreenBuffer('oldpc-game','isolated-screen-probe',game='gmod')
 buffer.publish(frame,stamp,started)
 # Probe-only evidence artifact: preserve exactly the model-selected bytes for QA.
 original_inspect=buffer.inspect
 def record_selected(session):
  image,meta=original_inspect(session)
  if image:
   dest=root/'probe-frames';dest.mkdir(parents=True,exist_ok=True)
   (dest/meta['display_name']).write_bytes(base64.b64decode(image.split(',',1)[1]))
  return image,meta
 buffer.inspect=record_selected
 loop=CaptureLoop(buffer,capture_game,seconds=90).start()
 core=None
 try:
  core=Core(root,provider=provider,screen_source=buffer).start()
  core.call('persona',dict(persona=persona))
  result=core.call('think',dict(prompt=a.prompt,screen_session=buffer.session,
                              metadata_only=True,deadline_seconds=60),timeout=65)
  # Private local artifact, not a public or Discord reply.
  (root/'probe-answer.json').write_text(json.dumps(result),encoding='utf-8')
  print(json.dumps(dict(status='completed',answer_file=str(root/'probe-answer.json'),
                       capture_failures=loop.failures)))
 finally:
  capture_stopped=loop.stop()
  receipt=core.call('stop',timeout=15) if core is not None and core.accepting else None
  if core is not None:core.thread.join(5)
  print(json.dumps(dict(capture_stopped=capture_stopped,core_stop=receipt)))

if __name__=='__main__':main()
