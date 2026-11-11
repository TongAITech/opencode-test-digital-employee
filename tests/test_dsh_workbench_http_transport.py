"""Real loopback disconnects must not cause a second HTTP response."""
import json
import os
import socket
import struct
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import urlopen

from tools.dsh_workbench.business_http import HostIdentity, scope_handler


def controlled_server(base_handler, hold_at='body'):
    """Pause one response so a real peer reset precedes its header/body write."""
    class Server(ThreadingHTTPServer):
        daemon_threads = True

        def handle_error(self, request, client_address):
            self.errors.append(True)

    class Handler(base_handler):
        def send_response(self, status, message=None):
            self.server.statuses.append(status)
            self._first_response = len(self.server.statuses) == 1
            if self._first_response and hold_at == 'headers':
                self._wait_for_reset()
            super().send_response(status, message)

        def end_headers(self):
            super().end_headers()
            if self._first_response and hold_at == 'body':
                self._wait_for_reset()

        def _wait_for_reset(self):
            self.server.paused.set()
            if not self.server.release.wait(5):
                raise AssertionError('test peer did not release response')
            self.connection.settimeout(5)
            try:
                self.connection.recv(1)
            except (ConnectionResetError, ConnectionAbortedError):
                self.server.reset_seen.set()

        def finish(self):
            try:
                super().finish()
            finally:
                if getattr(self, '_first_response', False):
                    self.server.first_done.set()

    server = Server(('127.0.0.1', 0), Handler)
    server.statuses, server.errors = [], []
    server.paused, server.release = threading.Event(), threading.Event()
    server.reset_seen, server.first_done = threading.Event(), threading.Event()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def reset_first_response(server, request):
    with socket.create_connection(server.server_address, timeout=5) as client:
        client.sendall(request)
        if not server.paused.wait(5):
            raise AssertionError('response did not reach controlled write')
        linger = struct.pack('hh' if os.name == 'nt' else 'ii', 1, 0)
        client.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, linger)
    server.release.set()
    if not server.first_done.wait(5) or not server.reset_seen.is_set():
        raise AssertionError('real loopback reset was not observed')


class TransportDisconnect(unittest.TestCase):
    def start(self, hold_at='body', connection_factory=None):
        base = scope_handler(connection_factory, b'local-transport-fixture-key-32-bytes',
                             lambda request: HostIdentity('alice'))
        server = controlled_server(base, hold_at)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.addCleanup(server.release.set)
        return server

    def check_reset(self, hold_at, path, status):
        server = self.start(hold_at)
        request = ('GET ' + path + ' HTTP/1.0\r\nHost: localhost\r\n\r\n').encode()
        reset_first_response(server, request)
        self.assertEqual(server.statuses, [status])
        self.assertEqual(server.errors, [])
        with urlopen('http://127.0.0.1:%d/api/workbench/v1/write-context' %
                     server.server_port, timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(json.load(response)['schema'], 'dsh-workbench/write-context/v1')
        self.assertEqual(server.statuses, [status, 200])
        self.assertEqual(server.errors, [])

    def test_reset_during_success_body_has_no_second_response(self):
        self.check_reset('body', '/api/workbench/v1/write-context', 200)

    def test_reset_during_error_body_has_no_second_response(self):
        self.check_reset('body', '/api/workbench/v1/not-a-resource', 404)

    def test_reset_before_headers_has_no_second_response(self):
        self.check_reset('headers', '/api/workbench/v1/write-context', 200)

    def test_connected_database_failure_still_returns_real_503(self):
        def unavailable():
            raise RuntimeError('private database configuration must not be exposed')
        # No reset in this test: ordinary errors must still reach the client.
        base = scope_handler(unavailable, b'local-transport-fixture-key-32-bytes',
                             lambda request: HostIdentity('alice'))
        server = ThreadingHTTPServer(('127.0.0.1', 0), base)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with self.assertRaises(HTTPError) as caught:
            urlopen('http://127.0.0.1:%d/api/workbench/v1/projects' %
                    server.server_port, timeout=5)
        self.assertEqual(caught.exception.code, 503)
        body = json.load(caught.exception)
        self.assertEqual(body, {'error': {'code': 'SCOPE_SOURCE_UNAVAILABLE'}})


if __name__ == '__main__':
    unittest.main()
