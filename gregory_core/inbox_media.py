"""Private content-addressed attachment objects. Network/decoding is off-writer."""
import base64,hashlib,json,os,re,tempfile,warnings,time
from pathlib import Path
from urllib.parse import urlsplit,unquote
from urllib.request import Request,build_opener,HTTPRedirectHandler

MAX_BYTES=20*1024*1024
MAX_STORE=100*1024*1024

def storage_bytes(root):
 return sum(p.stat().st_size for p in root.rglob('*') if p.is_file() and not p.is_symlink())

def descriptor(value,channel):
 if not isinstance(value,dict) or set(value)!={'attachment_id','url','filename','size','content_type'}:raise ValueError('attachment fields required')
 aid=value['attachment_id']
 if not isinstance(aid,str) or not re.fullmatch(r'[0-9]{1,20}',aid):raise ValueError('attachment identity required')
 if type(value['size']) is not int or not 0<value['size']<=MAX_BYTES:raise ValueError('bounded attachment bytes required')
 if not isinstance(value['filename'],str) or not 1<=len(value['filename'])<=255:raise ValueError('bounded display filename required')
 if value['content_type'] is not None and (not isinstance(value['content_type'],str) or len(value['content_type'])>120):raise ValueError('MIME field refused')
 url=value['url'];p=urlsplit(url) if isinstance(url,str) and len(url)<=4096 else None
 if (not p or p.scheme!='https' or p.hostname not in ('cdn.discordapp.com','media.discordapp.net') or p.port not in (None,443)
     or p.username or p.password or p.fragment or not p.path.startswith('/attachments/'+channel+'/'+aid+'/')):raise ValueError('Discord attachment CDN/source required')
 if '\\' in unquote(p.path) or any(x in ('.','..') for x in unquote(p.path).split('/')):raise ValueError('attachment path refused')
 return dict(value)

def directory(root):
 root=Path(root).absolute();root.mkdir(parents=True,exist_ok=True,mode=0o700)
 if root.resolve()!=root:raise ValueError('real private media directory required')
 for name in ['objects','incoming','previews']:
  p=root/name;p.mkdir(exist_ok=True,mode=0o700)
  if p.is_symlink() or p.resolve()!=p:raise ValueError('media directory redirection refused')
 return root

def object_path(root,digest):
 if not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest):raise ValueError('content hash required')
 return directory(root)/'objects'/digest

def verify_file(path,digest,size):
 if path.is_symlink() or path.resolve()!=path or not path.is_file() or path.stat().st_size!=size:raise ValueError('attachment object identity refused')
 if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('attachment object hash mismatch')

class NoRedirect(HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):raise ValueError('attachment redirect refused')

def store(root,attachment,*,opener=None):
 root=directory(root)
 opener=opener or build_opener(NoRedirect())
 expected=attachment['size'];descriptor(attachment, urlsplit(attachment['url']).path.split('/')[2])
 if storage_bytes(root)+expected>MAX_STORE:raise ValueError('private media test storage capacity')
 digest=hashlib.sha256();count=0
 fd,name=tempfile.mkstemp(prefix='download-',dir=root/'incoming');temp=Path(name)
 try:
  deadline=time.monotonic()+20
  with os.fdopen(fd,'wb') as out,opener.open(Request(attachment['url'],headers={'User-Agent':'GregoryCoreAttachmentTest/1.0'}),timeout=5) as response:
   if response.getcode()!=200:raise ValueError('attachment HTTP outcome refused')
   length=response.headers.get('Content-Length')
   length=int(length) if length is not None else None
   if length is not None and not 0<length<=MAX_BYTES:raise ValueError('attachment response byte budget exceeded')
   actual_type=response.headers.get('Content-Type')
   while True:
    if time.monotonic()>deadline:raise TimeoutError('attachment total deadline')
    chunk=getattr(response,'read1',response.read)(65536)
    if not chunk:break
    count+=len(chunk)
    if count>MAX_BYTES or storage_bytes(root)+len(chunk)>MAX_STORE:raise ValueError('attachment byte budget exceeded')
    out.write(chunk);digest.update(chunk)
   out.flush();os.fsync(out.fileno())
  if not count or length is not None and count!=length:raise ValueError('incomplete attachment response')
  if storage_bytes(root)>MAX_STORE:raise ValueError('private media storage capacity')
  key=digest.hexdigest();target=object_path(root,key);reused=target.exists()
  if reused:verify_file(target,key,count)
  else:
   # No source-controlled filename ever becomes a filesystem path.
   os.link(temp,target)
  return dict(sha256=key,size=count,reused_object=reused,declared_bytes=expected,
              representation_changed=count!=expected or actual_type!=attachment['content_type'],downloaded_content_type=actual_type)
 finally:
  temp.unlink(missing_ok=True)

def preview(root,digest,size):
 """Decode static image or at most three GIF frames; opaque files stay opaque."""
 from PIL import Image,UnidentifiedImageError
 root=directory(root);path=object_path(root,digest);verify_file(path,digest,size)
 manifest=root/'previews'/(digest+'-v1.json')
 if manifest.exists():return read_preview(root,digest)
 result=dict(format='opaque',frames=[],sampled_animation=False)
 try:
  with warnings.catch_warnings():
   warnings.simplefilter('error',Image.DecompressionBombWarning)
   with Image.open(path) as image:
    if image.format not in ('PNG','JPEG','GIF','WEBP'):raise ValueError('stored file type has no supported image preview')
    if image.width*image.height>16_000_000:raise ValueError('image pixel budget exceeded')
    total=getattr(image,'n_frames',1)
    indices=sorted(set([0,total//2,total-1])) if 1<total<=200 and image.width*image.height*total<=64_000_000 else [0]
    result=dict(format=image.format,frames=[],sampled_animation=total>1,total_frames=total)
    for slot,index in enumerate(indices):
     image.seek(index);frame=image.convert('RGB');frame.thumbnail((768,768))
     dest=root/'previews'/(digest+'-v1-'+str(slot)+'.jpg')
     if dest.is_symlink():raise ValueError('preview redirection refused')
     frame.save(dest,format='JPEG',quality=85)
     data=dest.read_bytes()
     if len(data)>512*1024:raise ValueError('bounded JPEG preview required')
     if storage_bytes(root)>MAX_STORE:
      dest.unlink();raise ValueError('private media preview storage capacity')
     result['frames'].append(dict(name=dest.name,sha256=hashlib.sha256(data).hexdigest(),bytes=len(data),frame_index=index))
 except UnidentifiedImageError:
  pass
 with manifest.open('x',encoding='utf8') as f:json.dump(result,f)
 return read_preview(root,digest)

def read_preview(root,digest):
 root=directory(root);p=root/'previews'/(digest+'-v1.json')
 if p.is_symlink() or not p.is_file():raise ValueError('private preview manifest required')
 data=json.loads(p.read_text(encoding='utf8'))
 if not isinstance(data.get('frames'),list) or len(data['frames'])>3:raise ValueError('preview frame limit')
 for slot,f in enumerate(data['frames']):
  if f.get('name')!=digest+'-v1-'+str(slot)+'.jpg' or type(f.get('bytes')) is not int or not 0<f['bytes']<=512*1024:raise ValueError('preview identity refused')
  verify_file(root/'previews'/f['name'],f['sha256'],f['bytes'])
 return data

def initialize(db):
 db.execute('''CREATE TABLE IF NOT EXISTS inbox_attachments(
  bot_id TEXT,channel_id TEXT,message_id TEXT,attachment_id TEXT,peer_id TEXT,
  descriptor TEXT,status TEXT,sha256 TEXT,error_category TEXT,
  PRIMARY KEY(bot_id,channel_id,message_id,attachment_id))''')
 if 'stored_bytes' not in [r[1] for r in db.execute('PRAGMA table_info(inbox_attachments)')]:
  db.execute('ALTER TABLE inbox_attachments ADD COLUMN stored_bytes INTEGER')

def register(core,bot,channel,peer,mid,attachments):
 if not isinstance(attachments,list) or len(attachments)>4:raise ValueError('at most four attachments per message')
 validated=[descriptor(x,channel) for x in attachments]
 if len({x['attachment_id'] for x in validated})!=len(validated):raise ValueError('duplicate attachment ID')
 for a in validated:
  old=core.db.execute('SELECT descriptor FROM inbox_attachments WHERE bot_id=? AND channel_id=? AND message_id=? AND attachment_id=?',(bot,channel,mid,a['attachment_id'])).fetchone()
  if old:
   prior=json.loads(old['descriptor'])
   if any(prior[k]!=a[k] for k in ('attachment_id','filename','size','content_type')):raise ValueError('attachment identity changed')
   core.db.execute('UPDATE inbox_attachments SET descriptor=? WHERE bot_id=? AND channel_id=? AND message_id=? AND attachment_id=?',(json.dumps(a),bot,channel,mid,a['attachment_id']))
  else:
   core.db.execute('INSERT INTO inbox_attachments(bot_id,channel_id,message_id,attachment_id,peer_id,descriptor,status) VALUES(?,?,?,?,?,?,?)',(bot,channel,mid,a['attachment_id'],peer,json.dumps(a),'queued'))
   cached=core.db.execute("SELECT sha256,descriptor,stored_bytes FROM inbox_attachments WHERE bot_id=? AND channel_id=? AND peer_id=? AND attachment_id=? AND status='ready' LIMIT 1",(bot,channel,peer,a['attachment_id'])).fetchone()
   if cached and json.loads(cached['descriptor'])['size']==a['size']:
    size=cached['stored_bytes'] or a['size']
    verify_file(object_path(core.root/'inbox-media',cached['sha256']),cached['sha256'],size)
    read_preview(core.root/'inbox-media',cached['sha256'])
    core.db.execute("UPDATE inbox_attachments SET status='ready',sha256=?,stored_bytes=? WHERE bot_id=? AND channel_id=? AND message_id=? AND attachment_id=?",(cached['sha256'],size,bot,channel,mid,a['attachment_id']))
 return validated

def execute(core,p):
 from gregory_core.inbox import execute as inbox
 cfg=core.inbox_config
 if not cfg or not cfg.get('media_enabled'):raise PermissionError('inbox media disabled')
 required={'operation','bot_id','channel_id','peer_id'}
 op=p.get('operation')
 extra=set() if op=='media_pending' else {'message_id','attachment_id','sha256','size'} if op=='media_commit' else {'message_id','attachment_id','error_category'} if op=='media_failed' else {'message_id','attachment_id'} if op=='media_retry' else None
 if extra is None or set(p)!=required|extra:raise ValueError('media operation fields refused')
 # Existing binding is checked without admitting a new DM channel.
 inbox(core,dict(operation='context',bot_id=p['bot_id'],channel_id=p['channel_id'],peer_id=p['peer_id'],surface='dm'))
 scope=(p['bot_id'],p['channel_id'],p['peer_id'])
 if op=='media_pending':
  rows=core.db.execute("SELECT message_id,attachment_id,descriptor FROM inbox_attachments WHERE bot_id=? AND channel_id=? AND peer_id=? AND status='queued' ORDER BY length(message_id),message_id LIMIT 10",scope).fetchall()
  return dict(attachments=[dict(json.loads(r['descriptor']),message_id=r['message_id']) for r in rows])
 row=core.db.execute('SELECT * FROM inbox_attachments WHERE bot_id=? AND channel_id=? AND peer_id=? AND message_id=? AND attachment_id=?',scope+(p['message_id'],p['attachment_id'])).fetchone()
 if row is None:raise PermissionError('attachment source refused')
 if op=='media_retry':
  if row['status']=='failed':
   with core.db:core.db.execute("UPDATE inbox_attachments SET status='queued',error_category=NULL WHERE bot_id=? AND channel_id=? AND peer_id=? AND message_id=? AND attachment_id=?",scope+(p['message_id'],p['attachment_id']))
  return dict(queued=row['status'] in ('failed','queued'),ready=row['status']=='ready')
 if op=='media_commit':
  a=json.loads(row['descriptor'])
  if type(p['size']) is not int or not 0<p['size']<=MAX_BYTES:raise ValueError('attachment byte identity refused')
  path=object_path(core.root/'inbox-media',p['sha256']);verify_file(path,p['sha256'],p['size'])
  info=read_preview(core.root/'inbox-media',p['sha256'])
  if row['status']=='ready':
   if row['sha256']!=p['sha256'] or row['stored_bytes']!=p['size']:raise ValueError('committed attachment identity changed')
   return dict(ready=True,sha256=p['sha256'],preview_frames=len(info['frames']),duplicate=True)
  with core.db:core.db.execute("UPDATE inbox_attachments SET status='ready',sha256=?,stored_bytes=?,error_category=NULL WHERE bot_id=? AND channel_id=? AND peer_id=? AND message_id=? AND attachment_id=?",(p['sha256'],p['size'])+scope+(p['message_id'],p['attachment_id']))
  cid=core.db.execute('SELECT correlation_id FROM inbox_messages WHERE bot_id=? AND channel_id=? AND message_id=?',(p['bot_id'],p['channel_id'],p['message_id'])).fetchone()[0]
  previous=core.command_context;core.command_context=cid
  try:core._event('conversation',dict(type='attachment.received',surface='dm',visibility='dm_only',bot_id=p['bot_id'],channel_id=p['channel_id'],author_id=p['peer_id'],correlation_id=cid,message_id=p['message_id'],attachment_id=p['attachment_id'],sha256=p['sha256'],bytes=p['size'],declared_bytes=a['size'],representation_changed=p['size']!=a['size'],preview_frames=len(info['frames'])),source='discord_inbox')
  finally:core.command_context=previous
  return dict(ready=True,sha256=p['sha256'],preview_frames=len(info['frames']))
 error=p['error_category']
 if row['status']=='ready':return dict(ready=True,already_committed=True)
 if not isinstance(error,str) or not re.fullmatch(r'[A-Za-z0-9_.]{1,80}',error):raise ValueError('typed media failure required')
 with core.db:core.db.execute("UPDATE inbox_attachments SET status='failed',error_category=? WHERE bot_id=? AND channel_id=? AND peer_id=? AND message_id=? AND attachment_id=?",(error,)+scope+(p['message_id'],p['attachment_id']))
 return dict(failed=True,error_category=error)

def images_for_turn(core,scope):
 if not core.inbox_config.get('media_enabled'):return [],[]
 rows=core.db.execute("""SELECT * FROM inbox_attachments WHERE bot_id=? AND channel_id=? AND peer_id=?
  AND message_id IN (SELECT message_id FROM inbox_messages WHERE bot_id=? AND channel_id=? AND peer_id=?
  ORDER BY length(message_id) DESC,message_id DESC LIMIT 8)
  ORDER BY length(message_id) DESC,message_id DESC""",(scope['bot_id'],scope['channel_id'],scope['author_id'])*2).fetchall()
 if not rows:return [],[]
 newest=rows[0]['message_id']
 for row in rows:
  if row['message_id']!=newest:break
  if row['status']!='ready':continue
  meta=read_preview(core.root/'inbox-media',row['sha256'])
  if not meta['frames']:continue
  root=directory(core.root/'inbox-media');a=json.loads(row['descriptor']);verify_file(object_path(root,row['sha256']),row['sha256'],row['stored_bytes'] or a['size'])
  images=['data:image/jpeg;base64,'+base64.b64encode((root/'previews'/f['name']).read_bytes()).decode() for f in meta['frames']]
  return images,[dict(message_id=row['message_id'],attachment_id=row['attachment_id'],sha256=row['sha256'],format=meta['format'],sampled_animation=meta['sampled_animation'],frame_indices=[f['frame_index'] for f in meta['frames']])]
 return [],[]
