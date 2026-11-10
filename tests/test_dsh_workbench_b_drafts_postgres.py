"""Six B07 draft kinds on real PostgreSQL and HTTP; no canonical R1 writes."""
import copy
import json
import threading
import unittest
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import test_dsh_workbench_b_milestone_postgres as prior
import test_dsh_workbench_b_postgres as infra
from tools.dsh_workbench.business_assets import AssetStore
from tools.dsh_workbench.business_migrations import migrate,downgrade
from tools.dsh_workbench.business_http import create_scope_server,HostIdentity

PAYLOADS={
 'case_draft':{'preconditions':[],'steps':['send request'],'expected_results':['business rule holds'],'oracle_notes':'human draft only'},
 'obligation_draft':{'business_rule':'amount must be positive','scenario':'boundary validation','oracle_notes':'draft'},
 'defect_note':{'reproduction_notes':'candidate observation','expected_notes':'expected text','actual_notes':'unqualified observation'},
 'report_draft':{'body':'PASS is quoted draft text, never a formal report','tags':['draft']},
 'knowledge':{'body':'domain context','tags':['reference']},
 'meeting_minutes':{'body':'decision and action notes','tags':[]},
}

@unittest.skipUnless(infra.DSN and infra.psycopg,'real PostgreSQL DSN and psycopg required')
class DraftKinds(prior.Milestone):
    def setUp(self):
        super().setUp();migrate(self.owner,target=7)
        self.owner.execute(infra.sql.SQL('GRANT SELECT,INSERT ON wb.asset_payload TO {}').format(infra.sql.Identifier(self.role)))

    def draft(self,kind,request=None,**changes):
        body=self.body(request or 'draft-'+kind,kind=kind,payload=copy.deepcopy(PAYLOADS[kind]))
        body.update(changes);return body

    def test_six_kinds_create_patch_retire_restore_original_response_and_filter(self):
        self.scope_seed()
        for kind in PAYLOADS:
            with self.subTest(kind=kind):
                body=self.draft(kind)
                created=self.assets.mutate('alice','P1','B1','create',body);asset=created['record']['asset_id']
                self.assertEqual(created['record']['payload'],PAYLOADS[kind])
                self.assertEqual(created['record']['r1_reference_state'],'UNRESOLVED')
                self.assertEqual(self.assets.list('alice','P1','B1',kind=kind)['records'][0]['asset_id'],asset)
                self.assets.mutate('alice','P1','B1','update',self.change('edit-'+kind,title='edited '+kind),asset)
                self.assertEqual(self.assets.mutate('alice','P1','B1','create',body),created)
                self.assets.mutate('alice','P1','B1','retire',self.change('retire-'+kind,2),asset)
                self.assertEqual(self.assets.list('alice','P1','B1',kind=kind)['records'],[])
                self.assets.mutate('alice','P1','B1','restore',self.change('restore-'+kind,3),asset)
                self.assertEqual(self.assets.get('alice','P1','B1',asset,revision=1)['record']['payload'],PAYLOADS[kind])
        self.assertEqual(len(self.assets.list('alice','P1','B1')['records']),6)
        self.assertEqual(self.assets.list('alice','P1','B1',kind='milestone')['records'],[])
        self.error(400,lambda:self.assets.list('alice','P1','B1',kind='knowledge',due_from='2026-11-10'))

    def test_nested_formal_facts_types_unknown_fields_and_complex_json_are_rejected(self):
        self.scope_seed()
        for kind in PAYLOADS:
            for bad in [dict(PAYLOADS[kind],nodegate='PASS'),{'body':{'attempt':'PASS'}},['not','object'],None]:
                self.error(400,lambda:self.assets.mutate('alice','P1','B1','create',self.draft(kind,'bad-'+kind,payload=bad)))
        self.error(400,lambda:self.assets.mutate('alice','P1','B1','create',self.draft('case_draft','nested',payload={'steps':[{'actual_result':'PASS'}],'expected_results':['expected']})))
        self.error(400,lambda:self.assets.mutate('alice','P1','B1','create',self.draft('knowledge','tag-object',payload={'body':'text','tags':[{'verified':True}]})))
        self.error(400,lambda:self.assets.mutate('alice','P1','B1','create',self.draft('knowledge','formal',verified=True)))
        self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.asset_payload').fetchone()[0],0)
        self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.asset_root').fetchone()[0],0)

    def test_draft_exact_scope_bad_sst_audit_failure_and_current_acl_replay(self):
        self.scope_seed()
        exact=self.draft('knowledge',scope_level='EXACT_RELATIONS',brvs_links=[{'requirement_id':'R1','system_version_id':'V1','sst_id':'SST1'}])
        created=self.assets.mutate('alice','P1','B1','create',exact)
        self.assertEqual(len(self.assets.list('alice','P1','B1',kind='knowledge',sst_ids=['SST1'])['records']),1)
        bad=self.draft('knowledge','bad-link',scope_level='EXACT_RELATIONS',brvs_links=[{'requirement_id':'R2','system_version_id':'V1','sst_id':'SST1'}])
        self.error(422,lambda:self.assets.mutate('alice','P1','B1','create',bad))
        self.owner.execute("CREATE FUNCTION wb.fail_payload() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'payload unavailable'; END $$")
        self.owner.execute('CREATE TRIGGER fail BEFORE INSERT ON wb.asset_payload FOR EACH ROW EXECUTE FUNCTION wb.fail_payload()')
        with self.assertRaises(infra.psycopg.Error):self.assets.mutate('alice','P1','B1','create',self.draft('meeting_minutes'))
        self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.asset_root').fetchone()[0],1)
        self.owner.execute('DROP TRIGGER fail ON wb.asset_payload')
        self.assets.mutate('alice','P1','B1','create',self.draft('meeting_minutes'))
        self.owner.execute("DELETE FROM wb.project_acl WHERE principal='alice'")
        self.error(403,lambda:self.assets.mutate('alice','P1','B1','create',exact))
        self.error(403,lambda:self.assets.get('alice','P1','B1',created['record']['asset_id'],revision=1))

    def test_payload_database_types_immutable_history_and_nonempty_downgrade(self):
        self.scope_seed()
        created=self.assets.mutate('alice','P1','B1','create',self.draft('case_draft'))
        self.assertFalse(self.owner.execute("SELECT wb.draft_payload_valid('case_draft',%s::jsonb)",(json.dumps({'steps':[{'nodegate':'PASS'}],'expected_results':['text']}),)).fetchone()[0])
        self.assertFalse(self.owner.execute("SELECT wb.draft_payload_valid('report_draft',%s::jsonb)",(json.dumps({'body':'text','formal_result':'PASS'}),)).fetchone()[0])
        for statement in ["UPDATE wb.asset_payload SET payload='{}'",'DELETE FROM wb.asset_payload']:
            with self.assertRaises(infra.psycopg.Error):self.owner.execute(statement)
        with self.assertRaisesRegex(RuntimeError,'ROLLBACK_REQUIRES_BACKUP'):downgrade(self.owner,6)
        self.assertEqual(self.assets.get('alice','P1','B1',created['record']['asset_id'])['record']['payload'],PAYLOADS['case_draft'])

    def test_additive_migration_preserves_milestone_and_empty_payload_downgrade(self):
        self.scope_seed()
        created=self.assets.mutate('alice','P1','B1','create',self.body())
        downgrade(self.owner,6)
        self.assertEqual(self.assets.get('alice','P1','B1',created['record']['asset_id'])['record'],created['record'])
        self.assertTrue(migrate(self.owner,target=7))
        self.owner.execute(infra.sql.SQL('GRANT SELECT,INSERT ON wb.asset_payload TO {}').format(infra.sql.Identifier(self.role)))
        self.assertEqual(self.assets.get('alice','P1','B1',created['record']['asset_id'])['record'],created['record'])

    def test_all_draft_kinds_real_http_and_no_formal_result_acceptance(self):
        self.scope_seed()
        provider=lambda request:HostIdentity('alice',request.headers.get('Origin')=='https://host-fixture.test' and request.headers.get('X-CSRF-Token')=='session-proof') if request.headers.get('Cookie')=='host-session-fixture' else None
        server=create_scope_server(('127.0.0.1',0),lambda:infra.psycopg.connect(**self.params,autocommit=True),self.scope.key,provider)
        threading.Thread(target=server.serve_forever,daemon=True).start();self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        url='http://127.0.0.1:'+str(server.server_port)+'/api/workbench/v1/projects/P1/batches/B1/assets'
        context_url='http://127.0.0.1:'+str(server.server_port)+'/api/workbench/v1/write-context'
        with urlopen(Request(context_url,headers={'Cookie':'host-session-fixture'}),timeout=5) as context_response:context=json.load(context_response)['write_context']
        for kind in PAYLOADS:
            request=Request(url,data=json.dumps(self.draft(kind)).encode(),headers={'X-DSH-Write-Context':context,'Content-Type':'application/json','Cookie':'host-session-fixture','Origin':'https://host-fixture.test','X-CSRF-Token':'session-proof'},method='POST')
            with urlopen(request,timeout=5) as response:
                self.assertEqual(response.status,201);value=json.load(response)
                self.assertEqual(value['record']['kind'],kind);self.assertEqual(value['record']['r1_reference_state'],'UNRESOLVED')
            with urlopen(Request(url+'?kind='+kind,headers={'Cookie':'host-session-fixture'}),timeout=5) as response:self.assertEqual(json.load(response)['records'][0]['kind'],kind)

    def test_unicode_surrogate_payload_is_rejected_without_partial_asset(self):
        self.scope_seed()
        self.error(400,lambda:self.assets.mutate('alice','P1','B1','create',self.draft('knowledge',payload={'body':'\ud800'})))
        self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.asset_root').fetchone()[0],0)

    def test_database_rejects_asset_kind_change_across_versions(self):
        self.scope_seed()
        created=self.assets.mutate('alice','P1','B1','create',self.draft('case_draft'))
        with self.assertRaisesRegex(infra.psycopg.Error,'IMMUTABLE_ASSET_KIND'):
            self.owner.execute("INSERT INTO wb.asset_revision(project_id,batch_id,asset_id,revision,kind,title,due_date,state,scope_level,created_release_date,scope_link_count,actor,reason) SELECT project_id,batch_id,asset_id,2,'knowledge',title,NULL,state,scope_level,created_release_date,scope_link_count,actor,'forged kind' FROM wb.asset_revision WHERE asset_id=%s",(created['record']['asset_id'],))
        self.assertEqual(self.assets.get('alice','P1','B1',created['record']['asset_id'])['record']['kind'],'case_draft')
