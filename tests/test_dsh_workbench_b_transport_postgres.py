"""A real committed PG mutation survives loss of its HTTP response unchanged."""
import json
import unittest
from urllib.request import Request, urlopen

import test_dsh_workbench_b_milestone_postgres as fixture
import test_dsh_workbench_b_postgres as infra
from test_dsh_workbench_http_transport import controlled_server, reset_first_response
from tools.dsh_workbench.business_http import HostIdentity, scope_handler
from tools.dsh_workbench.write_context import subject_write_context


@unittest.skipUnless(infra.DSN and infra.psycopg, 'real PostgreSQL DSN and psycopg required')
class CommittedResponseLoss(unittest.TestCase):
    def test_reset_after_commit_then_same_key_replay_is_not_reexecution(self):
        db = fixture.Milestone(methodName='test_same_milestone_calendar_detail_update_idempotency_retire_restore')
        db.setUp()
        self.addCleanup(db.doCleanups)
        db.scope_seed()
        base = scope_handler(lambda: infra.psycopg.connect(**db.params, autocommit=True),
                             db.scope.key, lambda request: HostIdentity('alice', True))
        server = controlled_server(base)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.addCleanup(server.release.set)
        path = '/api/workbench/v1/projects/P1/batches/B1/assets'
        payload = db.body(request='transport-committed-then-reset')
        body = json.dumps(payload).encode()
        context = subject_write_context(db.scope.key, 'alice')
        request = ('POST ' + path + ' HTTP/1.0\r\nHost: localhost\r\n'
                   'Content-Type: application/json\r\nX-DSH-Write-Context: ' + context +
                   '\r\nContent-Length: ' + str(len(body)) + '\r\n\r\n').encode() + body
        reset_first_response(server, request)
        self.assertEqual(server.statuses, [201])
        self.assertEqual(server.errors, [])
        self.assertEqual(db.owner.execute('SELECT count(*) FROM wb.asset_root').fetchone()[0], 1)
        self.assertEqual(db.owner.execute('SELECT count(*) FROM wb.asset_revision').fetchone()[0], 1)
        self.assertEqual(db.owner.execute('SELECT count(*) FROM wb.asset_outbox').fetchone()[0], 1)
        with urlopen(Request('http://127.0.0.1:%d' % server.server_port + path,
                             method='POST', data=body,
                             headers={'Content-Type': 'application/json',
                                      'X-DSH-Write-Context': context}), timeout=5) as response:
            self.assertEqual(response.status, 201)
            replay = json.load(response)
        self.assertEqual(replay['record']['revision'], 1)
        self.assertEqual(server.statuses, [201, 201])
        self.assertEqual(server.errors, [])
        for table in ('asset_root', 'asset_revision', 'asset_outbox'):
            self.assertEqual(db.owner.execute('SELECT count(*) FROM wb.' + table).fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
