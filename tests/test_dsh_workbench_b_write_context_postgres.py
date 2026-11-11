"""Real HTTP+PG subject fencing for unknown/pending asset writes."""
import json
import threading
import unittest
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import test_dsh_workbench_b_postgres as infra
from tools.dsh_workbench.business_migrations import migrate
from tools.dsh_workbench.business_http import create_scope_server,HostIdentity
from tools.dsh_workbench.business_store import BusinessStore
from tools.dsh_workbench.write_context import subject_write_context

KEY=b'write-context-regression-fixture-key-32bytes'

@unittest.skipUnless(infra.DSN and infra.psycopg,'real PostgreSQL DSN and psycopg required')
class WriteContext(infra.PostgresIdentity):
    def setUp(self):
        super().setUp();migrate(self.owner,target=7)
        for table in ['asset_root','asset_revision','asset_brv_link','asset_brvs_link','asset_outbox','asset_request_result','asset_payload']:
            self.owner.execute(infra.sql.SQL('GRANT SELECT,INSERT ON wb.{} TO {}').format(infra.sql.Identifier(table),infra.sql.Identifier(self.role)))
        self.owner.execute(infra.sql.SQL('GRANT UPDATE(current_revision) ON wb.asset_root TO {}').format(infra.sql.Identifier(self.role)))
        self.connections=[]
        self.path='/api/workbench/v1/projects/P1/batches/B1/assets'
        self.body={'request_id':'unknown-alice-write','expected_relation_revision':1,'kind':'milestone','title':'unknown result draft','payload':{'due_date':'2026-11-11'},'scope_level':'BATCH_WIDE'}

    def seed_context(self):
        self.owner.execute("INSERT INTO wb.project_acl VALUES('P1','bob',true)")
        BusinessStore(self.runtime).create_batch('alice','P1','B1','2026-11-12','batch-create')

    def server(self,key=KEY,provider='fixture'):
        if provider=='fixture':
            def provider(request):
                principal={'host-session=alice':'alice','host-session=bob':'bob','host-session=reader':'reader'}.get(request.headers.get('Cookie'))
                if principal is None:return None
                mutation=request.headers.get('Origin')=='https://host.test' and request.headers.get('X-CSRF-Token')=='session-proof'
                return HostIdentity(principal,mutation)
        def factory():
            self.connections.append(True)
            return infra.psycopg.connect(**self.params,autocommit=True)
        server=create_scope_server(('127.0.0.1',0),factory,key,provider)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        self.latest_server=server
        return 'http://127.0.0.1:'+str(server.server_port)

    def call(self,origin,method='GET',path='/api/workbench/v1/write-context',principal='alice',context=None,body=None,**headers):
        values={'Cookie':'host-session='+principal,'Origin':'https://host.test','X-CSRF-Token':'session-proof','Content-Type':'application/json'}
        if context is not None:values['X-DSH-Write-Context']=context
        values.update(headers)
        request=Request(origin+path,method=method,headers=values,data=json.dumps(body).encode() if body is not None else None)
        try:
            with urlopen(request,timeout=5) as response:return response.status,json.load(response)
        except HTTPError as error:return error.code,json.load(error)

    def test_alice_unknown_commit_bob_same_project_replay_rejected_then_alice_reconciles(self):
        self.seed_context()
        origin=self.server()
        status,identity=self.call(origin);self.assertEqual(status,200)
        alice=identity['write_context'];self.assertNotIn('alice',json.dumps(identity))
        # Alice committed; emulate the client losing/ignoring this HTTP response.
        status,committed=self.call(origin,'POST',self.path,context=alice,body=self.body);self.assertEqual(status,201)
        self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.asset_root').fetchone()[0],1)
        bob=self.call(origin,principal='bob')[1]['write_context'];self.assertNotEqual(alice,bob)
        before=len(self.connections)
        status,error=self.call(origin,'POST',self.path,principal='bob',context=alice,body=self.body)
        self.assertEqual((status,error['error']['code']),(409,'WRITE_CONTEXT_CHANGED'))
        self.assertEqual(len(self.connections),before)
        self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.asset_outbox').fetchone()[0],1)
        # Reading a fresh Bob context must not legitimize the captured Alice one.
        self.call(origin,principal='bob')
        self.assertEqual(self.call(origin,'POST',self.path,principal='bob',context=alice,body=self.body)[0],409)
        status,reconciled=self.call(origin,'POST',self.path,context=alice,body=self.body)
        self.assertEqual(status,201);self.assertEqual(reconciled,committed)
        self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.asset_root').fetchone()[0],1)

    def test_context_missing_forged_readonly_csrf_and_provider_are_independent(self):
        self.seed_context()
        origin=self.server()
        token=self.call(origin)[1]['write_context'];before=len(self.connections)
        status,error=self.call(origin,'POST',self.path,body=self.body)
        self.assertEqual((status,error['error']['code']),(403,'WRITE_CONTEXT_REQUIRED'))
        self.assertEqual(self.call(origin,'POST',self.path,context='forged',body=self.body)[0],409)
        self.assertEqual(self.call(origin,'POST',self.path,context=token,body=self.body,**{'X-CSRF-Token':''})[0],403)
        self.assertEqual(len(self.connections),before)
        reader=self.call(origin,principal='reader')[1]['write_context']
        self.assertEqual(self.call(origin,'POST',self.path,principal='reader',context=reader,body=self.body)[0],403)
        self.assertEqual(self.call(origin,path='/api/workbench/v1/write-context?principal=alice',principal='bob')[0],400)
        self.assertEqual(self.call(origin,principal='unknown')[0],403)
        missing=self.server(provider=None);self.assertEqual(self.call(missing)[0],503)
        no_key=self.server(key=None);self.assertEqual(self.call(no_key)[0],503)
        self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.asset_root').fetchone()[0],0)

    def test_stable_key_restart_recovers_but_rotated_key_cannot_rebind_pending(self):
        self.seed_context()
        first=self.server();token=self.call(first)[1]['write_context']
        status,committed=self.call(first,'POST',self.path,context=token,body=self.body);self.assertEqual(status,201)
        self.latest_server.shutdown();self.latest_server.server_close()
        restarted=self.server()
        self.assertEqual(self.call(restarted)[1]['write_context'],token)
        self.assertEqual(self.call(restarted,'POST',self.path,context=token,body=self.body)[1],committed)
        rotated=self.server(key=b'rotated-write-context-fixture-key-32bytes')
        self.assertNotEqual(self.call(rotated)[1]['write_context'],token)
        self.assertEqual(self.call(rotated,'POST',self.path,context=token,body=self.body)[0],409)
        self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.asset_root').fetchone()[0],1)
