"""Exercise the normal server entry points from the isolated source archive."""
import pathlib
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from rc7_release.package import SOURCE_DIRS


class ProductSourceArchiveTest(unittest.TestCase):
    def test_admin_and_unconfigured_workbench_start_without_repository_tools(self):
        repository = pathlib.Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='dsh-product-source-') as directory:
            source = pathlib.Path(directory)
            for name in SOURCE_DIRS:
                if pathlib.Path(name).parts[0] == 'tools':
                    continue
                shutil.copytree(repository / name, source / name,
                                ignore=shutil.ignore_patterns('__pycache__'))
            script = textwrap.dedent('''
                import contextlib
                import http.client
                import importlib.util
                import json
                from pathlib import Path
                import sys
                import threading

                sys.path.insert(0, sys.argv[1])
                assert importlib.util.find_spec('tools') is None
                from rc7_admin.product_server import (
                    ProductAdminApplication, WorkbenchPublicApplication, create_server,
                )

                @contextlib.contextmanager
                def running(application, **options):
                    server = create_server(application, port=0, **options)
                    thread = threading.Thread(target=server.serve_forever, daemon=True)
                    thread.start()
                    try:
                        yield server
                    finally:
                        server.shutdown()
                        server.server_close()
                        thread.join(3)

                def request(server, method, path):
                    connection = http.client.HTTPConnection(*server.server_address, timeout=3)
                    try:
                        connection.request(method, path)
                        response = connection.getresponse()
                        return response.status, response.read()
                    finally:
                        connection.close()

                def error(server, method, path, status, code):
                    actual, body = request(server, method, path)
                    assert actual == status, (method, path, actual)
                    assert json.loads(body) == {'error': {'code': code}}, body

                r1 = Path(sys.argv[1]) / 'r1.jsonl'
                with running(ProductAdminApplication(str(r1))) as admin:
                    status, body = request(admin, 'GET', '/api/meta')
                    assert status == 200
                    assert json.loads(body)['product_surface'] == 'RC7_ADMIN_PRODUCT_V4'
                original_r1 = r1.read_bytes()
                with running(WorkbenchPublicApplication(), workbench_mode=True) as workbench:
                    assert request(workbench, 'GET', '/workbench')[0] == 200
                    error(workbench, 'GET', '/api/missions', 403, 'FORBIDDEN')
                    metadata = '/api/workbench/v1/projects/P1/metadata'
                    error(workbench, 'GET', metadata, 503, 'HOST_IDENTITY_UNAVAILABLE')
                    error(workbench, 'PATCH', metadata, 503, 'HOST_IDENTITY_UNAVAILABLE')
                    error(workbench, 'PATCH', metadata + ';extra', 405, 'METHOD_NOT_ALLOWED')
                    error(workbench, 'POST', '/api/workbench/v1/projects/P1/batches/B1/assets',
                          503, 'HOST_IDENTITY_UNAVAILABLE')
                    error(workbench, 'POST', '/api/workbench/v1/write-context', 405,
                          'METHOD_NOT_ALLOWED')
                    error(workbench, 'PUT', metadata, 405, 'METHOD_NOT_ALLOWED')
                assert r1.read_bytes() == original_r1
            ''')
            result = subprocess.run([sys.executable, '-I', '-S', '-c', script, str(source)],
                                    cwd=source, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
