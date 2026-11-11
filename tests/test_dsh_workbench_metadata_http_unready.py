"""Real HTTP negative transport checks, not metadata database acceptance."""
import http.client
import json
import threading
import unittest

from tools.dsh_workbench.business_http import HostIdentity, create_scope_server
from tools.dsh_workbench.write_context import subject_write_context


class MetadataUnreadyHTTPTest(unittest.TestCase):
    def test_unconfigured_backend_never_opens_a_connection_or_accepts_a_write(self):
        key = b'fixture-only-metadata-context-key!'
        opened = []

        def forbidden_connection():
            opened.append(True)
            raise AssertionError('unconfigured adapter must not reach a database')

        # Explicit test fixture; these headers are not a production Host adapter.
        def fixture_identity(handler):
            principal = handler.headers.get('X-Fixture-Principal')
            if principal not in ('Alice', 'Bob'):
                return None
            return HostIdentity(principal, handler.headers.get('X-Fixture-Mutation') == 'fixture')

        server = create_scope_server(('127.0.0.1', 0), forbidden_connection, key,
                                     fixture_identity)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        alice = subject_write_context(key, 'Alice')
        cases = [
            ('GET', '/api/workbench/v1/projects/P/metadata', {}, 403, 'FORBIDDEN'),
            ('GET', '/api/workbench/v1/projects/P/metadata', {'X-Fixture-Principal': 'Alice'}, 503, 'METADATA_ADAPTER_UNAVAILABLE'),
            ('PATCH', '/api/workbench/v1/projects/P/metadata', {'X-Fixture-Principal': 'Alice'}, 403, 'MUTATION_AUTH_REQUIRED'),
            ('PATCH', '/api/workbench/v1/projects/P/metadata', {'X-Fixture-Principal': 'Alice', 'X-Fixture-Mutation': 'fixture'}, 403, 'WRITE_CONTEXT_REQUIRED'),
            ('PATCH', '/api/workbench/v1/projects/P/metadata', {'X-Fixture-Principal': 'Bob', 'X-Fixture-Mutation': 'fixture', 'X-DSH-Write-Context': alice}, 409, 'WRITE_CONTEXT_CHANGED'),
            ('PATCH', '/api/workbench/v1/projects/P/metadata', {'X-Fixture-Principal': 'Alice', 'X-Fixture-Mutation': 'fixture', 'X-DSH-Write-Context': alice}, 503, 'METADATA_ADAPTER_UNAVAILABLE'),
            ('POST', '/api/workbench/v1/projects/P/metadata', {'X-Fixture-Principal': 'Alice'}, 405, 'METHOD_NOT_ALLOWED'),
            ('GET', '/api/workbench/v1/projects/P%2FQ/metadata', {'X-Fixture-Principal': 'Alice'}, 400, 'INVALID_METADATA_TARGET'),
            ('GET', '/api/workbench/v1/projects/P%00/metadata', {'X-Fixture-Principal': 'Alice'}, 400, 'INVALID_METADATA_TARGET'),
        ]
        try:
            for method, path, headers, expected_status, expected_code in cases:
                with self.subTest(method=method, path=path, expected=expected_code):
                    connection = http.client.HTTPConnection(*server.server_address, timeout=3)
                    try:
                        connection.request(method, path, body=b'invalid unparsed body', headers=headers)
                        response = connection.getresponse()
                        self.assertEqual(response.status, expected_status)
                        self.assertEqual(json.loads(response.read()), {'error': {'code': expected_code}})
                        self.assertEqual(response.getheader('Cache-Control'), 'no-store')
                    finally:
                        connection.close()
            self.assertEqual(opened, [])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(3)


if __name__ == '__main__':
    unittest.main()
