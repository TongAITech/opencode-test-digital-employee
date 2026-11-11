"""Native HTTP and real PostgreSQL 009, with an explicit fixture Host."""
import http.client
import json
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import threading
import unittest
from urllib.parse import urlencode

import test_dsh_workbench_b_postgres as infra
import test_dsh_workbench_b_project_metadata_postgres as metadata_fixture
from test_dsh_workbench_http_transport import controlled_server, reset_first_response
from rc7_admin.product_server import ProductAdminApplication, create_server
from tools.dsh_workbench.business_http import HostIdentity, scope_handler
from tools.dsh_workbench.project_metadata_store import ProjectMetadataStore
from tools.dsh_workbench.write_context import subject_write_context


@unittest.skipUnless(infra.DSN and infra.psycopg, 'real PostgreSQL required')
class ProjectMetadataHTTPPostgres(unittest.TestCase):
    path = '/api/workbench/v1/projects/P1/metadata'
    key = b'fixture-only-metadata-http-context-key'

    def setUp(self):
        self.fixture = metadata_fixture.MetadataPG(methodName='test_rename_single_fact_receipt_and_zero_batch_effect')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.fixture.govern()
        self.db = self.fixture.db
        self.db.owner.execute("INSERT INTO wb.project_acl VALUES('P1','bob',true)")

    def base_handler(self):
        def identity(handler):
            principal = handler.headers.get('X-Fixture-Principal')
            if principal not in ('alice', 'bob', 'reader'):
                return None
            expected_origin = 'http://127.0.0.1:%d' % handler.server.server_port
            return HostIdentity(principal, handler.headers.get('Origin') == expected_origin and
                                handler.headers.get('X-Fixture-CSRF') == 'fixture-proof')

        def connection():
            return infra.psycopg.connect(**self.db.params, autocommit=True)

        return scope_handler(connection, self.key, identity,
                             metadata_store_factory=ProjectMetadataStore)

    def native_server(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.r1 = Path(temp.name) / 'r1.jsonl'
        self.r1.write_bytes(b'')
        app = ProductAdminApplication(str(self.r1))
        server = create_server(app, '127.0.0.1', 0, workbench_handler=self.base_handler())
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def headers(self, server, actor='alice', original_actor=None):
        return {'X-Fixture-Principal': actor,
                'Origin': 'http://127.0.0.1:%d' % server.server_port,
                'X-Fixture-CSRF': 'fixture-proof', 'Content-Type': 'application/json',
                'X-DSH-Write-Context': subject_write_context(self.key, original_actor or actor)}

    def exchange(self, server, method, body=None, headers=None, path=None):
        connection = http.client.HTTPConnection(*server.server_address, timeout=5)
        try:
            connection.request(method, path or self.path, body=body,
                               headers=headers if headers is not None else self.headers(server))
            response = connection.getresponse()
            self.assertEqual(response.getheader('Cache-Control'), 'no-store')
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def body(self, name, key, revision='1'):
        access = self.fixture.scalar("SELECT access_scope_revision FROM wb.project WHERE project_id='P1'")
        return json.dumps({'request_id': key, 'expected_metadata_revision': revision,
                           'expected_access_scope_revision': str(access),
                           'changes': {'name': name}, 'reason': 'approved\x00\n'}).encode()

    def test_native_rename_replays_original_receipt_and_retains_current_name_and_batch(self):
        self.db.store.create_batch('alice', 'P1', 'B1', '2027-01-01', 'fixture-batch')
        before_batch = self.db.owner.execute('SELECT * FROM wb.release_batch').fetchall()
        server = self.native_server()
        before_r1 = self.r1.read_bytes()
        status, initial = self.exchange(server, 'GET')
        self.assertEqual((status, initial['name'], initial['metadata_revision']), (200, 'first', '1'))
        original = self.body('  新项目  ', 'rename-1')
        status, receipt = self.exchange(server, 'PATCH', original)
        self.assertEqual((status, receipt['outcome'], receipt['name'], receipt['applied_metadata_revision']),
                         (200, 'APPLIED', '新项目', '2'))
        self.assertEqual(self.exchange(server, 'PATCH', original,
                                      self.headers(server, 'bob', 'alice')),
                         (409, {'error': {'code': 'WRITE_CONTEXT_CHANGED'}}))
        self.assertEqual(self.exchange(server, 'PATCH', self.body('second', 'hidden-conflict', '2')),
                         (409, {'error': {'code': 'NAME_UNAVAILABLE'}}))
        self.assertEqual(self.exchange(server, 'PATCH', self.body('latest', 'rename-2', '2'))[0], 200)
        self.assertEqual(self.exchange(server, 'PATCH', original), (200, receipt))
        self.assertEqual(self.exchange(server, 'PATCH', self.body('stale', 'stale-revision')),
                         (409, {'error': {'code': 'REVISION_CONFLICT'}}))
        status, unchanged = self.exchange(server, 'PATCH', self.body('latest', 'same-name', '3'))
        self.assertEqual((status, unchanged['outcome'], unchanged['history_revision']), (200, 'NO_CHANGE', None))
        self.assertEqual(self.exchange(server, 'GET')[1]['name'], 'latest')
        self.assertEqual(self.db.owner.execute('SELECT * FROM wb.release_batch').fetchall(), before_batch)
        self.assertEqual(self.r1.read_bytes(), before_r1)
        self.assertEqual(self.fixture.scalar('SELECT count(*) FROM wb.project_metadata_history'), 2)
        self.assertEqual(self.fixture.scalar('SELECT count(*) FROM wb.project_metadata_outbox'), 2)

    def test_body_and_authorization_errors_leave_no_metadata_write(self):
        server = self.native_server()
        valid = self.headers(server)
        for headers, raw, expected_status, code in [
            (dict(valid, Origin='http://wrong.invalid'), b'bad', 403, 'MUTATION_AUTH_REQUIRED'),
            (self.headers(server, 'reader'), b'bad', 403, 'FORBIDDEN'),
            (dict(valid, **{'Content-Type': 'application/json; charset=latin1'}), b'{}', 400, 'INVALID_METADATA_BODY'),
            (dict(valid, **{'Transfer-Encoding': 'chunked'}), b'{}', 400, 'INVALID_METADATA_BODY'),
            (valid, b' ' * 16385, 400, 'INVALID_METADATA_BODY'),
            (valid, b'\xff', 400, 'JSON_INVALID_UTF8'),
            (valid, b'{"request_id":"r","request_id":"x"}', 400, 'JSON_DUPLICATE_KEY'),
        ]:
            with self.subTest(code=code):
                self.assertEqual(self.exchange(server, 'PATCH', raw, headers),
                                 (expected_status, {'error': {'code': code}}))
        self.assertEqual(self.exchange(server, 'GET', path=self.path + '?principal=bob'),
                         (400, {'error': {'code': 'INVALID_METADATA_QUERY'}}))
        connection = http.client.HTTPConnection(*server.server_address, timeout=5)
        try:
            connection.putrequest('PATCH', self.path)
            for name, value in valid.items():
                connection.putheader(name, value)
            connection.putheader('Content-Length', '2')
            connection.putheader('Content-Length', '2')
            connection.endheaders(b'{}')
            response = connection.getresponse()
            self.assertEqual((response.status, json.loads(response.read())),
                             (400, {'error': {'code': 'INVALID_METADATA_BODY'}}))
        finally:
            connection.close()
        connection = http.client.HTTPConnection(*server.server_address, timeout=5)
        try:
            connection.request('PATCH', self.path, body=b'{}',
                               headers=dict(valid, **{'Content-Length': '3'}))
            connection.sock.shutdown(socket.SHUT_WR)
            response = connection.getresponse()
            self.assertEqual((response.status, json.loads(response.read())),
                             (400, {'error': {'code': 'INCOMPLETE_METADATA_BODY'}}))
        finally:
            connection.close()
        self.assertEqual(self.fixture.scalar('SELECT count(*) FROM wb.project_metadata_result'), 0)
        self.assertEqual(self.fixture.scalar('SELECT count(*) FROM wb.project_metadata_outbox'), 0)
        self.assertEqual(self.exchange(server, 'GET')[1]['name'], 'first')

    def test_project_directory_rejects_aba_cursor_and_retains_batch_wire(self):
        self.db.owner.execute("INSERT INTO wb.project_acl VALUES('P2','alice',false)")
        self.db.store.create_batch('alice', 'P1', 'B1', '2027-01-01', 'fixture-batch')
        server = self.native_server()
        project_path = '/api/workbench/v1/projects'
        batch_path = project_path + '/P1/release-dates'
        page_path = project_path + '?page_size=1'
        status, before = self.exchange(server, 'GET', path=page_path)
        self.assertEqual(status, 200)
        cursor = before['next_page_cursor']
        self.assertIsInstance(cursor, str)
        batch_before = self.exchange(server, 'GET', path=batch_path)
        self.assertEqual(batch_before[0], 200)
        self.assertEqual(self.exchange(server, 'PATCH', self.body('temporary', 'aba-out'))[0], 200)
        self.assertEqual(self.exchange(server, 'PATCH', self.body('first', 'aba-back', '2'))[0], 200)
        status, after = self.exchange(server, 'GET', path=page_path)
        self.assertEqual(status, 200)
        self.assertEqual(after['schema'], 'dsh-workbench/business-directory/v1')
        self.assertEqual(after['records'], before['records'])
        self.assertNotEqual(after['directory_revision'], before['directory_revision'])
        old_page = project_path + '?' + urlencode({'page_size': 1, 'page_cursor': cursor})
        self.assertEqual(self.exchange(server, 'GET', path=old_page),
                         (409, {'error': {'code': 'STALE_CURSOR'}}))
        self.assertEqual(self.exchange(server, 'GET', path=batch_path), batch_before)

    def test_commit_then_lost_http_response_recovers_once(self):
        server = controlled_server(self.base_handler())
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.addCleanup(server.release.set)
        body = self.body('committed', 'response-lost')
        headers = self.headers(server)
        headers['Content-Length'] = str(len(body))
        request = 'PATCH %s HTTP/1.0\r\nHost: localhost\r\n%s\r\n\r\n' % (
            self.path, '\r\n'.join('%s: %s' % item for item in headers.items()))
        reset_first_response(server, request.encode() + body)
        self.assertEqual(server.statuses, [200])
        self.assertEqual(server.errors, [])
        self.assertEqual(self.fixture.scalar("SELECT name FROM wb.project WHERE project_id='P1'"), 'committed')
        status, receipt = self.exchange(server, 'PATCH', body)
        self.assertEqual((status, receipt['name'], receipt['applied_metadata_revision']), (200, 'committed', '2'))
        self.assertEqual(server.statuses, [200, 200])
        self.assertEqual(server.errors, [])
        self.assertEqual(self.fixture.scalar('SELECT count(*) FROM wb.project_metadata_history'), 1)
        self.assertEqual(self.fixture.scalar('SELECT count(*) FROM wb.project_metadata_outbox'), 1)
