"""B06 real PostgreSQL and loopback HTTP; Host provider fixtures are explicit."""
import json
import threading
import unittest
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import test_dsh_workbench_b_sst_postgres as prior
from tools.dsh_workbench.business_migrations import migrate,downgrade
from tools.dsh_workbench.business_scope import ScopeStore
from tools.dsh_workbench.business_http import create_scope_server,HostIdentity

@unittest.skipUnless(prior.prior.DSN and prior.prior.psycopg,'real PostgreSQL DSN and psycopg required')
class Scope(prior.SST):
    def setUp(self):
        super().setUp()
        migrate(self.owner,target=5)
        self.scope=ScopeStore(self.runtime,b'B06-local-test-cursor-key-32-bytes!!')

    def scope_seed(self):
        self.sst_seed()
        prior.import_verified_sst_link(self.owner,'P1','B1','R1','V1','SST1','source:link1','r1')
        self.relations.attach_sst('alice','P1','B1','R1','V1','SST1',4,'attach')
        self.relations.create_requirement('alice','P1','R2','src','prod','r2','r1','source:r2','r2')
        self.relations.attach_member('alice','P1','B1','requirement','R2',5,'ar2')
        prior.import_verified_requirement_version(self.owner,'P1','B1','R2','V1','source:rv2','r1')
        self.relations.attach_requirement_version('alice','P1','B1','R2','V1',6,'brv2')

    def test_scope_pages_real_join_unsplit_sources_and_bound_cursors(self):
        self.scope_seed()
        first=self.scope.scope('alice','P1',release_date='2026-11-12',page_size=1)
        self.assertEqual(first['records'][0]['sst_id'],'SST1')
        self.assertEqual(first['source_refs'],['source:link1','source:rv'])
        second=self.scope.scope('alice','P1','B1',page_size=1,page_cursor=first['next_page_cursor'])
        self.assertEqual(second['records'][0]['split_state'],'UNSPLIT')
        self.assertIsNone(second['records'][0]['sst_id']);self.assertIsNone(second['records'][0]['source_verified_link'])
        self.assertIsNone(second['next_page_cursor'])
        cursor=first['next_page_cursor']
        self.error(409,lambda:self.scope.scope('reader','P1','B1',page_size=1,page_cursor=cursor))
        self.error(409,lambda:self.scope.scope('alice','P1','B1',page_size=2,page_cursor=cursor))
        self.error(409,lambda:self.scope.scope('alice','P1','B1',page_size=1,page_cursor=cursor+'x'))
        self.error(422,lambda:self.scope.scope('alice','P1','B1',requirement_ids=['R2'],sst_ids=['SST1']))
        self.assertEqual(len(self.scope.scope('alice','P1','B1',requirement_ids=['R1','R1'])['records']),1)

    def test_scope_permission_and_relation_revision_changes_invalidate_cursor(self):
        self.scope_seed()
        cursor=self.scope.scope('alice','P1','B1',page_size=1)['next_page_cursor']
        self.owner.execute("UPDATE wb.project_acl SET can_write=can_write WHERE principal='reader'")
        self.error(409,lambda:self.scope.scope('alice','P1','B1',page_size=1,page_cursor=cursor))
        cursor=self.scope.scope('alice','P1','B1',page_size=1)['next_page_cursor']
        self.store.reschedule('alice','P1','B1','2026-11-13',1,'move','reason','CHG')
        self.error(409,lambda:self.scope.scope('alice','P1','B1',page_size=1,page_cursor=cursor))
        self.owner.execute("DELETE FROM wb.project_acl WHERE principal='alice'")
        self.error(403,lambda:self.scope.scope('alice','P1','B1'))
        self.error(403,lambda:self.scope.scope('bob','P1','missing'))

    def start_server(self,provider='fixture'):
        if provider=='fixture':
            provider=lambda request: HostIdentity('alice') if request.headers.get('Authorization')=='Bearer host-test-token' else None
        server=create_scope_server(('127.0.0.1',0),lambda:prior.prior.psycopg.connect(**self.params,autocommit=True),self.scope.key,provider)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        return 'http://127.0.0.1:'+str(server.server_port)

    def http(self,origin,path,token=True):
        headers={'Authorization':'Bearer host-test-token'} if token else {}
        request=Request(origin+path,headers=headers)
        try:
            with urlopen(request,timeout=5) as response:return response.status,json.load(response)
        except HTTPError as error:return error.code,json.load(error)

    def test_real_http_pagination_filters_auth_errors_and_recovery(self):
        self.scope_seed();origin=self.start_server()
        path='/api/workbench/v1/projects/P1/release-dates/2026-11-12/scope'
        status,page=self.http(origin,path+'?batch_id=B1&page_size=1');self.assertEqual(status,200)
        status,last=self.http(origin,path+'?batch_id=B1&page_size=1&page_cursor='+page['next_page_cursor']);self.assertEqual(status,200);self.assertIsNone(last['next_page_cursor'])
        self.assertEqual(self.http(origin,path,False)[0],403)
        self.assertEqual(self.http(origin,path+'?principal=alice',False)[0],403)
        self.assertEqual(self.http(origin,path+'?principal=bob')[0],400)
        self.assertEqual(self.http(origin,path+'?batch_id=missing')[0],404)
        self.assertEqual(self.http(origin,path+'?page_cursor=forged')[0],409)
        self.assertEqual(self.http(origin,path+'?requirement_ids=R2&sst_ids=SST1')[0],422)
        self.assertEqual(self.http(origin,path+'?requirement_ids=R1&requirement_ids=R2')[0],200)
        missing=self.start_server(None)
        self.assertEqual(self.http(missing,path)[0],503)
        self.assertEqual(self.http(origin,path)[0],200)

    def test_incremental_empty_downgrade_preserves_existing_date_domain(self):
        # Earlier schemas retain their empty-downgrade tests in their own classes.
        # Once signed cursor epochs exist, downgrade requires controlled key retirement.
        self.batch()
        with self.assertRaisesRegex(RuntimeError,'SCOPE_CURSOR_KEY_ROTATION'):downgrade(self.owner,1)
        self.assertEqual(self.store.reschedule('alice','P1','B1','2026-11-13',1,'move','reason','CHG'),2)

    def test_empty_sst_increment_downgrade_keeps_existing_brv(self):
        self.seed()
        with self.assertRaisesRegex(RuntimeError,'SCOPE_CURSOR_KEY_ROTATION'):downgrade(self.owner,3)
        self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.requirement').fetchone()[0],1)

    def test_http_connection_outage_is_503_and_recovery_has_no_unscoped_fallback(self):
        self.scope_seed()
        broken=create_scope_server(('127.0.0.1',0),lambda:(_ for _ in ()).throw(ConnectionError('injected DB outage')),self.scope.key,lambda request:HostIdentity('alice'))
        thread=threading.Thread(target=broken.serve_forever,daemon=True);thread.start()
        self.addCleanup(broken.server_close);self.addCleanup(broken.shutdown)
        path='/api/workbench/v1/projects/P1/release-dates/2026-11-12/scope'
        self.assertEqual(self.http('http://127.0.0.1:'+str(broken.server_port),path)[0],503)
        healthy=self.start_server()
        self.assertEqual(self.http(healthy,path)[0],200)
        self.assertEqual(self.http(healthy,'/api/missions/legacy/overview')[0],404)

    def test_concurrent_mutation_between_count_and_page_keeps_snapshot_then_stales_cursor(self):
        self.scope_seed()
        prior.import_sst_identity(self.owner,'P1','V1','SST2','src','prod','RAW-200','r1','source:sst2')
        prior.import_verified_sst_link(self.owner,'P1','B1','R1','V1','SST2','source:link2','r1')
        raw=self.runtime
        test=self
        class InjectConcurrentCommit:
            fired=False
            def __getattr__(self,name):return getattr(raw,name)
            def execute(self,query,params=None):
                result=raw.execute(query,params)
                if query.startswith('SELECT count(*)') and not self.fired:
                    self.fired=True
                    with prior.prior.psycopg.connect(**test.params,autocommit=True) as writer:
                        prior.prior.RelationStore(writer).attach_sst('alice','P1','B1','R1','V1','SST2',7,'concurrent-attach')
                return result
        page=ScopeStore(InjectConcurrentCommit(),self.scope.key).scope('alice','P1','B1',page_size=1)
        self.assertEqual(page['relation_revision'],7)
        self.error(409,lambda:self.scope.scope('alice','P1','B1',page_size=1,page_cursor=page['next_page_cursor']))
        fresh=self.scope.scope('alice','P1','B1')
        self.assertEqual(fresh['relation_revision'],8)
        self.assertEqual(len(fresh['records']),3)

    def test_c_scope_client_consumes_real_http_pg_scope(self):
        import pathlib,subprocess,shutil
        if not shutil.which('node'):self.skipTest('Node required for real C client integration')
        self.scope_seed();origin=self.start_server()
        client=(pathlib.Path(__file__).resolve().parents[1]/'rc7_admin/static/workbench/scope-client.mjs').as_uri()
        script="""import {ScopeClient,httpScopePort} from %s;
        const origin=%s;
        const port=httpScopePort((url,options)=>fetch(origin+url,{...options,headers:{...options.headers,Authorization:'Bearer host-test-token'}}));
        const client=new ScopeClient(port);
        const ok=await client.load({project_id:'P1',batch_id:'B1',release_date:'2026-11-12'});
        console.log(JSON.stringify({ok,state:client.state}));
        """%(json.dumps(client),json.dumps(origin))
        result=subprocess.run(['node','--input-type=module','-e',script],capture_output=True,text=True,timeout=15,check=True)
        value=json.loads(result.stdout)
        self.assertTrue(value['ok']);self.assertEqual(value['state']['status'],'READY')
        self.assertEqual(len(value['state']['records']),2)

    def test_reconnect_signed_cursor_same_key_and_rotated_key_rejects(self):
        self.scope_seed()
        cursor=self.scope.scope('alice','P1','B1',page_size=1)['next_page_cursor']
        with prior.prior.psycopg.connect(**self.params,autocommit=True) as connection:
            resumed=ScopeStore(connection,self.scope.key).scope('alice','P1','B1',page_size=1,page_cursor=cursor)
            self.assertIsNone(resumed['next_page_cursor'])
            self.error(409,lambda:ScopeStore(connection,b'rotated-cursor-key-32-bytes-long!!').scope('alice','P1','B1',page_size=1,page_cursor=cursor))

    def test_database_relation_trigger_invalidates_cursor_for_other_governed_writers(self):
        self.scope_seed()
        cursor=self.scope.scope('alice','P1','B1',page_size=1)['next_page_cursor']
        prior.import_sst_identity(self.owner,'P1','V1','SST2','src','prod','RAW-200','r1','source:sst2')
        prior.import_verified_sst_link(self.owner,'P1','B1','R1','V1','SST2','source:link2','r1')
        # Source proof exists; DB itself must advance the revision even for an
        # owner-governed write that does not pass through RelationStore.
        self.owner.execute("INSERT INTO wb.batch_requirement_version_sst VALUES('P1','B1','R1','V1','SST2')")
        self.error(409,lambda:self.scope.scope('alice','P1','B1',page_size=1,page_cursor=cursor))

    def test_controlled_scope_schema_rollback_reapply_with_retired_key_preserves_assets(self):
        import pathlib
        self.scope_seed()
        old_cursor=self.scope.scope('alice','P1','B1',page_size=1)['next_page_cursor']
        before=self.owner.execute('SELECT count(*) FROM wb.batch_requirement_version_sst').fetchone()[0]
        # No HTTP server is running in this test. Retire the old fixture key and
        # restore using a new key; raw down SQL is migration-owner-only.
        self.scope=None
        down=pathlib.Path(__file__).resolve().parents[1]/'tools/dsh_workbench/migrations/005_scope.down.sql'
        with self.owner.transaction():
            self.owner.execute(down.read_text())
            self.owner.execute('DELETE FROM public.wb_schema_migration WHERE version=5')
        self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.batch_requirement_version_sst').fetchone()[0],before)
        self.assertTrue(migrate(self.owner,target=5))
        self.scope=ScopeStore(self.runtime,b'new-fixture-key-after-retirement-32-bytes')
        self.error(409,lambda:self.scope.scope('alice','P1','B1',page_size=1,page_cursor=old_cursor))
        self.assertEqual(len(self.scope.scope('alice','P1','B1')['records']),2)
