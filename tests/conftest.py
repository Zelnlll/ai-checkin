"""本地回环 HTTP 假服务器：测试打真 socket，不 mock urllib。"""

from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


class _Handler(BaseHTTPRequestHandler):
    def _handle(self):
        length = int(self.headers.get('Content-Length') or 0)
        req_body = self.rfile.read(length) if length else b''
        path = self.path.split('?')[0]
        self.server.received.append(
            {'method': self.command, 'path': self.path,
             'headers': dict(self.headers), 'body': req_body})
        route = self.server.routes.get((self.command, path))
        if route is None:
            payload = b'{"detail": "no route"}'
            status, ctype = 404, 'application/json'
        else:
            status = route.get('status', 200)
            ctype = route.get('content_type', 'application/json')
            if 'dynamic' in route:
                payload = json.dumps(route['dynamic']()).encode('utf-8')
            elif 'raw' in route:
                payload = route['raw'].encode('utf-8')
            else:
                payload = json.dumps(route.get('body')).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = do_POST = _handle

    def log_message(self, *args):
        pass


class LocalServer:
    def __init__(self):
        self._httpd = ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
        self._httpd.routes = {}
        self._httpd.received = []
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self.base = 'http://127.0.0.1:%d' % self._httpd.server_address[1]

    def start(self):
        self._thread.start()
        return self

    def route(self, method, path, body=None, raw=None, status=200,
              content_type='application/json', dynamic=None):
        route = {'status': status, 'content_type': content_type}
        if dynamic is not None:
            route['dynamic'] = dynamic
        elif raw is not None:
            route['raw'] = raw
        else:
            route['body'] = body
        self._httpd.routes[(method, path)] = route

    @property
    def received(self):
        return self._httpd.received

    def stop(self):
        self._httpd.shutdown()
        self._httpd.server_close()


@pytest.fixture
def local_server():
    server = LocalServer().start()
    yield server
    server.stop()


def make_jwt(payload: dict) -> str:
    seg = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')
    return f'header.{seg}.sig'


class FakeStore:
    """CredentialStore 替身：构造时给 {platform: creds}。"""

    def __init__(self, creds: dict):
        self._creds = dict(creds)

    def load(self, platform):
        return self._creds.get(platform)


class FakeState:
    """DailyState 替身：done=当天已完成平台集合。"""

    def __init__(self, done: set[str] | None = None):
        self._done = set(done or ())
        self.marked: list = []

    def done_today(self, platform):
        return platform in self._done

    def mark(self, platform, result, day):
        self.marked.append((platform, result.state))


class FakeConfig:
    retry_times = 0
