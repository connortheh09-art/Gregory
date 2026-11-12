"""Loopback intake capability: bind/batch only, no model, read, owner or game API."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import socket
import threading


class ExclusiveServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class InboxServer:
    def __init__(self, core, port=0):
        if type(port) is not int or not 0 <= port <= 65535:
            raise ValueError('bounded port required')
        self.token = secrets.token_urlsafe(32)
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, code, value):
                body = json.dumps(value).encode()
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers(); self.wfile.write(body)

            def do_POST(self):
                if (self.headers.get('Host') != f'127.0.0.1:{parent.port}' or
                    self.headers.get('Origin') is not None or
                    not secrets.compare_digest(self.headers.get('Authorization', ''), 'Bearer '+parent.token)):
                    return self.reply(403, {'error': 'intake capability refused'})
                if self.path != '/inbox':
                    return self.reply(404, {'error': 'not found'})
                try:
                    if self.headers.get('Transfer-Encoding'):
                        raise ValueError('chunked body refused')
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 262144:
                        raise ValueError('bounded JSON required')
                    self.connection.settimeout(3)
                    data = json.loads(self.rfile.read(length))
                    if not isinstance(data, dict) or data.get('operation') not in ('bind', 'batch', 'media_pending', 'media_commit', 'media_failed', 'media_retry'):
                        raise ValueError('intake operation refused')
                    return self.reply(200, core.call('inbox', data, timeout=5))
                except Exception as exc:
                    return self.reply(400, {'error': type(exc).__name__})

        self.server = ExclusiveServer(('127.0.0.1', port), Handler)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self.thread.start(); return self

    def close(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(3)
