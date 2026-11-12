"""Loopback observer UI and separate owner/adapter capabilities for the prototype."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
from urllib.parse import parse_qs, urlsplit


class ControlServer:
    def __init__(self, core, *, port=0):
        self.core = core
        self.owner_token, self.adapter_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass  # no token/query logging to shared legacy log paths

            def reply(self, status, value, content_type='application/json'):
                body = value.encode('utf8') if isinstance(value,str) else json.dumps(value).encode('utf8')
                self.send_response(status)
                self.send_header('Content-Type', content_type+'; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                self.wfile.write(body)

            def valid_host(self):
                return self.headers.get('Host') == f'127.0.0.1:{parent.port}'

            def do_GET(self):
                if not self.valid_host():
                    return self.reply(403, {'error':'loopback host required'})
                parsed = urlsplit(self.path)
                try:
                    if parsed.path == '/':
                        html=(Path(__file__).parent/'web/control.html').read_text(encoding='utf8')
                        return self.reply(200, html, 'text/html')
                    if parsed.path == '/api/status':
                        return self.reply(200, core.call('status'))
                    if parsed.path == '/api/memory':
                        query=parse_qs(parsed.query)
                        payload={'memory_id':query['memory_id'][0]} if 'memory_id' in query else {'query':query.get('q',[''])[0]}
                        return self.reply(200, core.call('lookup',payload))
                    if parsed.path == '/api/correlation':
                        return self.reply(200,core.call('correlation',{'correlation_id':parse_qs(parsed.query).get('id',[''])[0]}))
                    return self.reply(404, {'error':'not found'})
                except Exception as exc:
                    return self.reply(503 if isinstance(exc,RuntimeError) else 400,
                                      {'error':type(exc).__name__, 'detail':str(exc)[:300]})

            def do_POST(self):
                if not self.valid_host():
                    return self.reply(403, {'error':'loopback host required'})
                actions={'/api/adapter':('adapter',parent.adapter_token),
                         '/api/goals':('goals',parent.owner_token),
                         '/api/import':('import',parent.owner_token),
                         '/api/think':('think',parent.owner_token),
                         '/api/profile':('profile',parent.owner_token),
                         '/api/stop':('stop',parent.owner_token)}
                action=actions.get(self.path)
                if action is None:
                    return self.reply(404, {'error':'not found'})
                authorization=self.headers.get('Authorization','')
                if not secrets.compare_digest(authorization, 'Bearer '+action[1]) or self.path=='/api/profile':
                    actor='adapter' if secrets.compare_digest(authorization,'Bearer '+parent.adapter_token) else 'owner' if secrets.compare_digest(authorization,'Bearer '+parent.owner_token) else 'unknown'
                    receipt={'type':'capability_refused','actor':actor,'scope':self.path}
                    try:
                        core.call('audit_refusal',receipt,timeout=2)
                    except (RuntimeError, TimeoutError):
                        with core.admission: core._refusal('capability refused',self.path,actor=actor)
                    return self.reply(403, receipt)
                try:
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0 < length <= 1024*1024:
                        raise ValueError('bounded JSON body required')
                    self.connection.settimeout(5)
                    data=json.loads(self.rfile.read(length))
                    if not isinstance(data,dict):
                        raise ValueError('JSON object required')
                    result=core.call(action[0],data)
                    return self.reply(200,result)
                except Exception as exc:
                    return self.reply(503 if isinstance(exc,RuntimeError) else 400,
                                      {'error':type(exc).__name__,'detail':str(exc)[:300],
                                       'receipt':getattr(exc,'receipt',None)})

        self.server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
        self.port=self.server.server_address[1]
        self.url=f'http://127.0.0.1:{self.port}'
        self.thread=threading.Thread(target=self.server.serve_forever,name='gregory-control-http')

    def start(self):
        self.thread.start()
        return self

    def control_receipt(self):
        # Caller writes this into its private root; never print tokens into logs.
        return {'url':self.url,'owner_token':self.owner_token,'adapter_token':self.adapter_token,
                'run_id':self.core.run_id,'mode':'isolated-prototype'}

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)
