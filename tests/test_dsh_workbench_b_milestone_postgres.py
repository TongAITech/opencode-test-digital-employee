"""B07 milestone drafts: real PostgreSQL, HTTP and explicit Host/CSRF fixtures."""
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import test_dsh_workbench_b_scope_postgres as prior
import test_dsh_workbench_b_postgres as infra
from tools.dsh_workbench.business_assets import AssetStore
from tools.dsh_workbench.business_migrations import migrate,downgrade
from tools.dsh_workbench.business_http import create_scope_server,HostIdentity

@unittest.skipUnless(infra.DSN and infra.psycopg,'real PostgreSQL DSN and psycopg required')
class Milestone(prior.Scope):
    def setUp(self):
        super().setUp();migrate(self.owner,target=6)
        for table in ['asset_root','asset_revision','asset_brv_link','asset_brvs_link','asset_outbox','asset_request_result']:
            self.owner.execute(infra.sql.SQL('GRANT SELECT,INSERT ON wb.{} TO {}').format(infra.sql.Identifier(table),infra.sql.Identifier(self.role)))
        self.owner.execute(infra.sql.SQL('GRANT UPDATE(current_revision) ON wb.asset_root TO {}').format(infra.sql.Identifier(self.role)))
        self.assets=AssetStore(self.runtime,self.scope.key)

    def body(self,request='create',**overrides):
        result={'request_id':request,'expected_relation_revision':7,'kind':'milestone','title':'投产评审','payload':{'due_date':'2026-11-11','description':'draft PASS is just text'},'scope_level':'BATCH_WIDE','brv_links':[],'brvs_links':[]}
        result.update(overrides);return result

    def change(self,request,revision=1,**overrides):
        result={'request_id':request,'expected_relation_revision':7,'expected_asset_revision':revision,'reason':'approved business edit'};result.update(overrides);return result

    def test_same_milestone_calendar_detail_update_idempotency_retire_restore(self):
        self.scope_seed()
        created=self.assets.mutate('alice','P1','B1','create',self.body());asset=created['record']['asset_id']
        self.assertEqual(created,self.assets.mutate('alice','P1','B1','create',self.body()))
        calendar=self.assets.list('alice','P1','B1',due_from='2026-11-10',due_to='2026-11-12')['records']
        self.assertEqual(calendar[0],self.assets.get('alice','P1','B1',asset)['record'])
        updated=self.assets.mutate('alice','P1','B1','update',self.change('move',payload={'due_date':'2026-11-13'}),asset)
        self.assertEqual(updated['record']['revision'],2)
        self.assertEqual(self.assets.list('alice','P1','B1',due_to='2026-11-12')['records'],[])
        self.assertEqual(created,self.assets.mutate('alice','P1','B1','create',self.body()))
        self.error(409,lambda:self.assets.mutate('alice','P1','B1','update',self.change('stale',title='stale'),asset))
        self.assets.mutate('alice','P1','B1','retire',self.change('retire',2),asset)
        self.assertEqual(self.assets.list('alice','P1','B1')['records'],[])
        self.error(404,lambda:self.assets.get('alice','P1','B1',asset))
        self.assertEqual(self.assets.get('alice','P1','B1',asset,revision=1)['record'],created['record'])
        restored=self.assets.mutate('alice','P1','B1','restore',self.change('restore',3),asset)
        self.assertEqual(restored['record']['state'],'ACTIVE');self.assertEqual(restored['record']['revision'],4)
        self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.asset_revision').fetchone()[0],4)
        self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.asset_outbox').fetchone()[0],4)

    def test_scope_exact_unsplit_illegal_brvs_and_formal_fields_rejected(self):
        self.scope_seed()
        body=self.body(scope_level='EXACT_RELATIONS',brv_links=[{'requirement_id':'R2','system_version_id':'V1'}])
        created=self.assets.mutate('alice','P1','B1','create',body)
        self.assertEqual(len(self.assets.list('alice','P1','B1',requirement_ids=['R2'])['records']),1)
        self.assertEqual(self.assets.list('alice','P1','B1',sst_ids=['SST1'])['records'],[])
        bad=self.body('bad',scope_level='EXACT_RELATIONS',brvs_links=[{'requirement_id':'R2','system_version_id':'V1','sst_id':'SST1'}])
        self.error(422,lambda:self.assets.mutate('alice','P1','B1','create',bad))
        self.error(400,lambda:self.assets.mutate('alice','P1','B1','create',self.body('forged',payload={'due_date':'2026-11-11','nodegate':'PASS'})))
        self.error(400,lambda:self.assets.mutate('alice','P1','B1','create',self.body('formal',kind='report_draft')))
        self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.asset_root').fetchone()[0],1)
        self.assertEqual(created['record']['r1_reference_state'],'NOT_LINKED')

    def test_audit_outbox_failure_rolls_back_root_revision_request_and_recovers(self):
        self.scope_seed()
        self.owner.execute("CREATE FUNCTION wb.fail_asset_outbox() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'outbox unavailable'; END $$")
        self.owner.execute('CREATE TRIGGER fail BEFORE INSERT ON wb.asset_outbox FOR EACH ROW EXECUTE FUNCTION wb.fail_asset_outbox()')
        before=self.owner.execute('SELECT count(*) FROM wb.audit').fetchone()[0]
        with self.assertRaises(infra.psycopg.Error):self.assets.mutate('alice','P1','B1','create',self.body())
        self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.asset_root').fetchone()[0],0)
        self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.audit').fetchone()[0],before)
        self.assertEqual(self.owner.execute("SELECT count(*) FROM wb.request_log WHERE request_id='create'").fetchone()[0],0)
        self.assertEqual(self.owner.execute('SELECT assets_revision FROM wb.release_batch').fetchone()[0],1)
        self.owner.execute('DROP TRIGGER fail ON wb.asset_outbox')
        self.assets.mutate('alice','P1','B1','create',self.body())
        self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.asset_root').fetchone()[0],1)

    def test_asset_cas_concurrent_and_history_permission_after_revoke(self):
        self.scope_seed();created=self.assets.mutate('alice','P1','B1','create',self.body());asset=created['record']['asset_id']
        def update(index):
            with infra.psycopg.connect(**self.params,autocommit=True) as connection:
                try:AssetStore(connection,self.scope.key).mutate('alice','P1','B1','update',self.change('u'+str(index),title='title'+str(index)),asset);return 200
                except infra.BusinessError as error:return error.status
        with ThreadPoolExecutor(2) as pool:self.assertEqual(sorted(pool.map(update,[1,2])),[200,409])
        self.owner.execute("DELETE FROM wb.project_acl WHERE principal='alice'")
        self.error(403,lambda:self.assets.get('alice','P1','B1',asset,revision=1,include_retired=True))
        self.error(403,lambda:self.assets.mutate('alice','P1','B1','create',self.body()))

    def test_asset_pagination_mutation_stales_and_empty_migration_downgrade(self):
        downgrade(self.owner,5)
        self.assertTrue(migrate(self.owner,target=6))
        # Restore runtime grants after empty rollback; production runs runtime.sql.
        for table in ['asset_root','asset_revision','asset_brv_link','asset_brvs_link','asset_outbox','asset_request_result']:
            self.owner.execute(infra.sql.SQL('GRANT SELECT,INSERT ON wb.{} TO {}').format(infra.sql.Identifier(table),infra.sql.Identifier(self.role)))
        self.owner.execute(infra.sql.SQL('GRANT UPDATE(current_revision) ON wb.asset_root TO {}').format(infra.sql.Identifier(self.role)))
        self.scope_seed()
        self.assets.mutate('alice','P1','B1','create',self.body('one'))
        self.assets.mutate('alice','P1','B1','create',self.body('two'))
        page=self.assets.list('alice','P1','B1',page_size=1)
        self.assertIsNotNone(page['next_page_cursor'])
        self.assertIsNone(self.assets.list('alice','P1','B1',page_size=1,page_cursor=page['next_page_cursor'])['next_page_cursor'])
        self.assets.mutate('alice','P1','B1','create',self.body('three'))
        self.error(409,lambda:self.assets.list('alice','P1','B1',page_size=1,page_cursor=page['next_page_cursor']))
        with self.assertRaisesRegex(RuntimeError,'ROLLBACK_REQUIRES_BACKUP'):downgrade(self.owner,5)

    def test_real_http_trusted_host_csrf_origin_and_shared_calendar_detail(self):
        self.scope_seed()
        def provider(request):
            if request.headers.get('Cookie')!='host-fixture=alice':return None
            return HostIdentity('alice',request.headers.get('Origin')=='https://trusted-host.test' and request.headers.get('X-CSRF-Token')=='session-bound-fixture')
        server=create_scope_server(('127.0.0.1',0),lambda:infra.psycopg.connect(**self.params,autocommit=True),self.scope.key,provider)
        threading.Thread(target=server.serve_forever,daemon=True).start();self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        origin='http://127.0.0.1:'+str(server.server_port)
        path='/api/workbench/v1/projects/P1/batches/B1/assets'
        def request(method,path,body=None,**headers):
            data=json.dumps(body).encode() if body is not None else None
            with urlopen(Request(origin+'/api/workbench/v1/write-context',headers={'Cookie':'host-fixture=alice'}),timeout=5) as context_response:context=json.load(context_response)['write_context']
            values={'X-DSH-Write-Context':context,'Cookie':'host-fixture=alice','Content-Type':'application/json','Origin':'https://trusted-host.test','X-CSRF-Token':'session-bound-fixture'};values.update(headers)
            try:
                with urlopen(Request(origin+path,data=data,headers=values,method=method),timeout=5) as response:return response.status,json.load(response)
            except HTTPError as error:return error.code,json.load(error)
        self.assertEqual(request('POST',path,self.body(),Origin='https://attacker.test')[0],403)
        self.assertEqual(request('POST',path,self.body(),**{'X-CSRF-Token':''})[0],403)
        self.assertEqual(request('POST',path,self.body(mutation_authorized=True))[0],400)
        status,created=request('POST',path,self.body());self.assertEqual(status,201)
        asset=created['record']['asset_id']
        self.assertEqual(request('GET',path+'?kind=milestone&due_from=2026-11-10&due_to=2026-11-12')[1]['records'][0],request('GET',path+'/'+asset)[1]['record'])
        self.assertEqual(request('PATCH',path+'/'+asset,self.change('move',payload={'due_date':'2026-11-14'}))[0],200)
        self.assertEqual(request('DELETE',path+'/'+asset,self.change('delete',2))[0],200)
        self.assertEqual(request('POST',path+'/'+asset+'/restore',self.change('restore',3))[0],200)
        self.assertEqual(request('GET',path+'/'+asset,**{'Cookie':'invalid'})[0],403)

    def test_milestone_invalid_date_formal_nested_fields_and_audit_failure_leave_no_assets(self):
        self.scope_seed()
        for index,payload in enumerate([{'due_date':'2026-02-29'},{'due_date':'infinity'},{'due_date':'2026-11-11','description':{'test_result':'PASS'}}]):
            self.error(400,lambda:self.assets.mutate('alice','P1','B1','create',self.body('invalid'+str(index),payload=payload)))
        self.owner.execute("CREATE FUNCTION wb.fail_milestone_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.action LIKE 'asset.%' THEN RAISE EXCEPTION 'audit unavailable'; END IF; RETURN NEW; END $$")
        self.owner.execute('CREATE TRIGGER fail BEFORE INSERT ON wb.audit FOR EACH ROW EXECUTE FUNCTION wb.fail_milestone_audit()')
        with self.assertRaises(infra.psycopg.Error):self.assets.mutate('alice','P1','B1','create',self.body())
        self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.asset_root').fetchone()[0],0)
        self.owner.execute('DROP TRIGGER fail ON wb.audit')
        self.assets.mutate('alice','P1','B1','create',self.body())
        for table in ['asset_revision','asset_outbox','asset_request_result']:
            with self.assertRaises(infra.psycopg.Error):self.owner.execute('DELETE FROM wb.'+table)

    def test_milestone_backend_disconnect_before_commit_rolls_back_and_replay_recovers(self):
        self.scope_seed();raw=self.runtime;test=self
        class DisconnectBeforeCommit:
            def __getattr__(self,name):return getattr(raw,name)
            def execute(self,query,params=None):
                result=raw.execute(query,params)
                if query.startswith('INSERT INTO wb.asset_outbox'):
                    test.owner.execute('SELECT pg_terminate_backend(%s)',(raw.info.backend_pid,))
                return result
        with self.assertRaises(infra.psycopg.Error):AssetStore(DisconnectBeforeCommit(),self.scope.key).mutate('alice','P1','B1','create',self.body())
        raw.close();self.runtime=infra.psycopg.connect(**self.params,autocommit=True);self.assets=AssetStore(self.runtime,self.scope.key)
        self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.asset_root').fetchone()[0],0)
        self.assets.mutate('alice','P1','B1','create',self.body())
        self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.asset_outbox').fetchone()[0],1)

    def test_committed_asset_scope_cannot_gain_new_links_by_insert(self):
        self.scope_seed()
        created=self.assets.mutate('alice','P1','B1','create',self.body(scope_level='EXACT_RELATIONS',brv_links=[{'requirement_id':'R2','system_version_id':'V1'}]))
        asset=created['record']['asset_id']
        with self.assertRaises(infra.psycopg.Error):
            self.owner.execute("INSERT INTO wb.asset_brv_link VALUES('P1','B1',%s,1,'R1','V1')",(asset,))
        self.assertEqual(self.assets.get('alice','P1','B1',asset)['record']['brv_links'],[{'requirement_id':'R2','system_version_id':'V1'}])
