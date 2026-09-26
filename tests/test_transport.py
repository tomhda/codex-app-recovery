"""Exercise the real HTTP/WebSocket client against an isolated local CDP fixture."""
import base64
import hashlib
import json
import socket
import struct
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import recovery

STATE = {
    'blank': False, 'queries': [],
    'features': {'status': 'success', 'fetch': 'idle', 'browser': True, 'automation': True},
    'settingsRead': True,
}


def recv_exact(stream, length):
    result = b''
    while len(result) < length:
        part = stream.read(length - len(result))
        if not part:
            raise EOFError()
        result += part
    return result


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def send_frame(self, message):
        data = json.dumps(message).encode()
        header = bytes([0x81, len(data)]) if len(data) < 126 else b'\x81\x7e' + struct.pack('!H', len(data))
        self.wfile.write(header + data)
        self.wfile.flush()

    def do_GET(self):
        fixture = self.server.fixture
        if self.path == '/json':
            fixture['discoveries'] += 1
            time.sleep(fixture['http_delay'])
            pages = [
                {'type': 'page', 'url': 'app://-/index.html?initialRoute=%2Fglobal-dictation'},
                {'type': 'page', 'url': 'app://-/index.html?initialRoute=%2Favatar-overlay'},
                {'type': 'page', 'url': 'app://-/index.html',
                 'webSocketDebuggerUrl': f'ws://127.0.0.1:{self.server.server_port}/devtools/page/{fixture["generation"]}'}
            ]
            data = json.dumps(pages).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except OSError:
                pass
            return
        if self.headers.get('Upgrade', '').lower() != 'websocket':
            self.send_error(404)
            return
        key = self.headers['Sec-WebSocket-Key'] + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
        self.send_response(101)
        self.send_header('Upgrade', 'websocket')
        self.send_header('Connection', 'Upgrade')
        self.send_header('Sec-WebSocket-Accept', base64.b64encode(hashlib.sha1(key.encode()).digest()).decode())
        self.end_headers()
        fixture['connections'].append(self.path)
        try:
            while True:
                h = recv_exact(self.rfile, 2)
                if (h[0] & 15) == 8:
                    self.wfile.write(b'\x88\x00')
                    self.wfile.flush()
                    return
                length = h[1] & 127
                if length == 126:
                    length = struct.unpack('!H', recv_exact(self.rfile, 2))[0]
                elif length == 127:
                    length = struct.unpack('!Q', recv_exact(self.rfile, 8))[0]
                mask = recv_exact(self.rfile, 4) if h[1] & 128 else None
                data = recv_exact(self.rfile, length)
                if mask:
                    data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
                request = json.loads(data)
                fixture['methods'].append(request['method'])
                if fixture['disconnect_once']:
                    fixture['disconnect_once'] = False
                    fixture['generation'] += 1
                    self.close_connection = True
                    self.connection.shutdown(socket.SHUT_RDWR)
                    return
                if request['method'] == 'Page.reload':
                    fixture['generation'] += 1
                    value = {}
                elif fixture['not_ready_once']:
                    fixture['not_ready_once'] = False
                    value = {'result': {'value': {'__recoveryError': {'code': 'engine_not_ready'}}}}
                else:
                    value = {'result': {'value': STATE}}
                self.send_frame({'method': 'Runtime.executionContextCreated', 'params': {}})
                self.send_frame({'id': request['id'], 'result': value})
        except (EOFError, OSError):
            return


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.fixture = {'generation': 1, 'discoveries': 0, 'connections': [], 'methods': [],
                        'http_delay': 0, 'disconnect_once': False, 'not_ready_once': False}
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.server.fixture = self.fixture
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.state = {'version': 'local-fixture', 'processes': [{'id': 424242, 'main': True}],
                      'listeners': [{'pid': 424242, 'port': self.server.server_port, 'address': '127.0.0.1'}]}

    def test_real_websocket_structured_readiness_retry(self):
        self.fixture['not_ready_once'] = True
        with patch.object(recovery, 'app_state', return_value=self.state):
            conn = recovery.connect_to_main(deadline=2)
            try:
                self.assertEqual(recovery._engine_snapshot(conn, attempts=2, delay=0, deadline=2), STATE)
            finally:
                conn.close()
        self.assertEqual(len(self.fixture['connections']), 1)
        self.assertEqual(self.fixture['methods'], ['Runtime.evaluate', 'Runtime.evaluate'])

    def test_check_recovers_closed_socket_by_rediscovery(self):
        self.fixture['disconnect_once'] = True
        with patch.object(recovery, 'app_state', return_value=self.state), patch.object(recovery, 'save_record') as saved:
            result = recovery.run_operation('check', lambda _: None)
        self.assertTrue(result)
        self.assertEqual(len(self.fixture['connections']), 2)
        self.assertTrue(self.fixture['connections'][1].endswith('/2'))
        self.assertTrue(all(method == 'Runtime.evaluate' for method in self.fixture['methods']))
        self.assertEqual(saved.call_args.args[0]['after'], STATE)

    def test_reload_uses_new_target_and_does_not_replay_mutation(self):
        with patch.object(recovery, 'app_state', return_value=self.state), patch.object(recovery, 'save_record'):
            recovery.run_operation('reload', lambda _: None)
        self.assertEqual(self.fixture['methods'].count('Page.reload'), 1)
        self.assertEqual(len(self.fixture['connections']), 2)
        self.assertTrue(self.fixture['connections'][1].endswith('/2'))

    def test_http_read_is_bounded_by_connection_deadline(self):
        self.fixture['http_delay'] = 1
        start = time.monotonic()
        with patch.object(recovery, 'app_state', return_value=self.state), self.assertRaises(recovery.RecoveryError):
            recovery.connect_to_main(attempts=8, delay=0, deadline=0.2)
        self.assertLess(time.monotonic() - start, 0.8)
        self.assertEqual(self.fixture['discoveries'], 1)
        self.assertFalse(self.fixture['connections'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
