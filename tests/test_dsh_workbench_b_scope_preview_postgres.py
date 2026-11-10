"""Read-only V3 preview against real PostgreSQL; no R1 fixture or create permit."""
import json
import unittest
from unittest.mock import patch

import test_dsh_workbench_b_scope_postgres as fixture
from tools.dsh_workbench.business_relations import (
    RelationStore, import_sst_identity, import_verified_requirement_version, import_verified_sst_link,
)
from tools.dsh_workbench.business_scope_preview import ReadOnlyScopeSnapshotPreview
from tools.dsh_workbench.business_store import BusinessError, BusinessStore

infra = fixture.prior.prior


@unittest.skipUnless(infra.DSN and infra.psycopg, 'real PostgreSQL DSN and psycopg required')
class ScopeSnapshotPreview(unittest.TestCase):
    def setUp(self):
        self.db = fixture.Scope(methodName='test_scope_pages_real_join_unsplit_sources_and_bound_cursors')
        self.db.setUp()
        self.addCleanup(self.db.doCleanups)
        self.db.scope_seed()
        self.preview = ReadOnlyScopeSnapshotPreview(self.db.runtime)

    def read(self, **kwargs):
        return self.preview.preview('alice', 'P1', 'B1', **kwargs)

    def error(self, status, code, call):
        with self.assertRaises(BusinessError) as caught:
            call()
        self.assertEqual((caught.exception.status, caught.exception.code), (status, code))

    def identities(self, result):
        return [(edge['requirement_id'], edge['version_id'], edge['sst_id']) for edge in result['snapshot']['edges']]

    def test_full_real_source_shape_and_date_revisions_no_authority_or_business_writes(self):
        before = self.db.owner.execute('SELECT count(*) FROM wb.audit').fetchone()[0]
        value = self.read(release_date='2026-11-12')
        self.assertEqual(value['preview_state'], 'READ_ONLY_SNAPSHOT_NOT_ADMISSION')
        self.assertEqual(set(value), {'preview_state', 'snapshot'})
        snapshot = value['snapshot']
        self.assertEqual(set(snapshot), {'schema_version', 'project_id', 'batch_id', 'release_date', 'date_revision', 'relation_revision', 'access_scope_revision', 'filters', 'edges'})
        self.assertEqual((snapshot['date_revision'], snapshot['relation_revision']), (1, 7))
        oracle = self.db.owner.execute("SELECT b.revision,b.relation_revision,p.access_scope_revision FROM wb.release_batch b JOIN wb.project p USING(project_id) WHERE b.project_id='P1' AND b.batch_id='B1'").fetchone()
        self.assertEqual((snapshot['date_revision'], snapshot['relation_revision'], snapshot['access_scope_revision']), oracle)
        self.assertEqual(self.identities(value), [('R1', 'V1', 'SST1'), ('R2', 'V1', None)])
        edge = snapshot['edges'][0]
        req = self.db.owner.execute("SELECT source_system,source_namespace,source_object_id,source_revision,source_ref FROM wb.requirement WHERE project_id='P1' AND requirement_id='R1'").fetchone()
        keys = ['source_system', 'source_namespace', 'source_object_id', 'source_revision', 'source_ref']
        self.assertEqual(edge['requirement_source'], dict(kind='REQUIREMENT_IDENTITY', **dict(zip(keys, req))))
        self.assertEqual(edge['system_id'], 'S1')
        self.assertNotIn('source_ref', edge['version_source'])
        self.assertEqual(edge['version_source']['kind'], 'SYSTEM_VERSION_IDENTITY')
        self.assertEqual(edge['brv_source'], {'kind':'VERIFIED_REQUIREMENT_VERSION', 'source_link_ref':'source:rv', 'source_revision':'r1'})
        self.assertEqual(edge['sst_source']['kind'], 'SST_IDENTITY')
        self.assertEqual(edge['brvs_source'], {'kind':'VERIFIED_SST_LINK', 'source_link_ref':'source:link1', 'verified_source_revision':'r1'})
        self.assertEqual(self.db.owner.execute('SELECT count(*) FROM wb.audit').fetchone()[0], before)
        self.assertEqual(self.db.owner.execute('SELECT max(version) FROM public.wb_schema_migration').fetchone()[0], 5)
        self.assertFalse(hasattr(self.preview,'create_batch'))
        self.assertFalse(hasattr(self.preview,'reschedule'))
        self.assertNotIn('scope_digest', value)  # Pure codec and formal admission are separate.

    def test_unsplit_does_not_inherit_other_requirements_sst_and_filter_coverage(self):
        unsplit = self.read(requirement_ids=['R2'])['snapshot']['edges'][0]
        self.assertIsNone(unsplit['sst_id'])
        self.assertIsNone(unsplit['sst_source'])
        self.assertIsNone(unsplit['brvs_source'])
        self.assertEqual(self.identities(self.read(sst_ids=['SST1'])), [('R1','V1','SST1')])
        for filters in [dict(requirement_ids=['R2'], sst_ids=['SST1']), dict(requirement_ids=['R1','missing']), dict(requirement_ids=['R1','R2'], sst_ids=['SST1']), dict(version_ids=['missing'])]:
            self.error(422, 'ILLEGAL_ASSOCIATION', lambda: self.read(**filters))

    def test_multiple_requirements_shared_versions_have_exact_separate_sst_edges(self):
        d = self.db
        d.store.create_version('alice','P1','V2','S1','same label','src','prod','v2','r2','preview-v2')
        d.relations.attach_member('alice','P1','B1','version','V2',7,'preview-v2-member')
        import_verified_requirement_version(d.owner,'P1','B1','R1','V2','source:rv-v2','r2')
        d.relations.attach_requirement_version('alice','P1','B1','R1','V2',8,'preview-r1-v2')
        import_sst_identity(d.owner,'P1','V1','SST2','src','prod','RAW-200','r2','source:sst2')
        import_verified_sst_link(d.owner,'P1','B1','R2','V1','SST2','source:r2-link2','r2')
        d.relations.attach_sst('alice','P1','B1','R2','V1','SST2',9,'preview-r2-sst2')
        import_sst_identity(d.owner,'P1','V2','SST3','src','prod','RAW-100','r3','source:sst3')
        import_verified_sst_link(d.owner,'P1','B1','R1','V2','SST3','source:r1-v2-sst3','r3')
        d.relations.attach_sst('alice','P1','B1','R1','V2','SST3',10,'preview-r1-sst3')
        value = self.read(requirement_ids=['R2','R1'], version_ids=['V2','V1'])
        self.assertEqual(self.identities(value), [('R1','V1','SST1'), ('R1','V2','SST3'), ('R2','V1','SST2')])
        self.assertEqual(value['snapshot']['filters'], {'requirement_ids':['R1','R2'],'version_ids':['V1','V2'],'sst_ids':[]})
        self.error(422, 'ILLEGAL_ASSOCIATION', lambda: self.read(version_ids=['V2'], sst_ids=['SST1']))
        self.error(422, 'ILLEGAL_ASSOCIATION', lambda: self.read(requirement_ids=['R1'], sst_ids=['SST2']))

    def test_authorized_reader_is_not_create_permission_revoke_and_recover(self):
        self.assertEqual(self.preview.preview('reader','P1','B1')['preview_state'], 'READ_ONLY_SNAPSHOT_NOT_ADMISSION')
        for actor, project in [('bob','P1'), ('alice','P2'), ('unknown','P1')]:
            self.error(403, 'FORBIDDEN', lambda: self.preview.preview(actor,project,'missing'))
        self.db.owner.execute("DELETE FROM wb.project_acl WHERE project_id='P1' AND principal='alice'")
        self.error(403, 'FORBIDDEN', self.read)
        self.db.owner.execute("INSERT INTO wb.project_acl VALUES('P1','alice',true)")
        self.assertEqual(len(self.read()['snapshot']['edges']), 2)

    def test_empty_missing_batch_and_date_mismatch_do_not_return_success(self):
        self.db.store.create_batch('alice','P1','empty','2026-11-15','preview-empty')
        self.error(422, 'ILLEGAL_ASSOCIATION', lambda: self.preview.preview('alice','P1','empty'))
        self.error(404, 'RESOURCE_NOT_FOUND', lambda: self.preview.preview('alice','P1','missing'))
        self.error(409, 'SCOPE_PREVIEW_DATE_CHANGED', lambda: self.read(release_date='2026-11-13'))
        self.error(400, 'INVALID_BUSINESS_DATE', lambda: self.read(release_date='2026-02-30'))

    def test_duplicate_invalid_filters_and_parameters_rejected_without_loosening_b06(self):
        for filters in [dict(requirement_ids=['R1','R1']),dict(version_ids='V1'),dict(sst_ids=['']),dict(requirement_ids=['\ud800']),dict(version_ids=[True]),dict(requirement_ids=['R']*101)]:
            self.error(400, 'INVALID_SCOPE_PREVIEW_REQUEST', lambda: self.read(**filters))
        # Existing B06 duplicate query semantics remain unchanged.
        self.assertEqual(len(self.db.scope.scope('alice','P1','B1',requirement_ids=['R1','R1'])['records']), 1)
        with self.assertRaises(TypeError):
            self.read(verified=True)

    def test_outer_transaction_cannot_switch_or_leak_subject_and_recovers(self):
        with self.db.runtime.transaction():
            self.db.runtime.execute("SELECT set_config('wb.principal','bob',true)")
            with self.assertRaisesRegex(ValueError, 'IDLE_CONNECTION_REQUIRED'):
                self.read()
            self.assertEqual(self.db.runtime.execute("SELECT current_setting('wb.principal',true)").fetchone()[0], 'bob')
            self.assertEqual(self.db.runtime.execute("SELECT count(*) FROM wb.requirement WHERE project_id='P1'").fetchone()[0], 0)
        self.assertEqual(len(self.read()['snapshot']['edges']), 2)
        self.assertEqual(self.db.runtime.execute("SELECT current_setting('wb.principal',true)").fetchone()[0], '')

    def test_hidden_proof_or_identity_fails_whole_read_then_recovers(self):
        for table in ['verified_requirement_version','system_version','requirement','verified_sst_link','sst_identity','system_identity','batch_requirement','batch_version']:
            self.db.owner.execute('CREATE POLICY preview_hide ON wb.'+table+' AS RESTRICTIVE FOR SELECT USING(false)')
            try:
                self.error(503, 'SCOPE_PREVIEW_SOURCE_UNAVAILABLE', self.read)
            finally:
                self.db.owner.execute('DROP POLICY preview_hide ON wb.'+table)
            self.assertEqual(len(self.read()['snapshot']['edges']), 2)

    def test_read_only_transaction_and_local_settings_reset_on_success_and_error(self):
        raw, observed = self.db.runtime, []
        original_timeout = raw.execute('SHOW statement_timeout').fetchone()[0]
        class Observe:
            def __getattr__(self, name): return getattr(raw,name)
            def execute(self, query, params=None):
                if query.startswith('SELECT count(*)'):
                    observed.append(raw.execute('SHOW transaction_read_only').fetchone()[0])
                    observed.append(raw.execute('SHOW transaction_isolation').fetchone()[0])
                return raw.execute(query,params)
        preview = ReadOnlyScopeSnapshotPreview(Observe())
        preview.preview('alice','P1','B1')
        self.assertEqual(observed, ['on','repeatable read'])
        self.assertEqual(raw.execute('SHOW statement_timeout').fetchone()[0], original_timeout)
        self.error(422, 'ILLEGAL_ASSOCIATION', lambda: preview.preview('alice','P1','B1',requirement_ids=['missing']))
        self.assertEqual(raw.execute('SHOW statement_timeout').fetchone()[0], original_timeout)
        self.assertEqual(raw.execute("SELECT current_setting('wb.principal',true)").fetchone()[0], '')

    def test_row_and_exact_serialized_byte_budgets_never_return_partial_scope(self):
        self.error(413, 'SCOPE_PREVIEW_BUDGET_EXCEEDED', lambda: ReadOnlyScopeSnapshotPreview(self.db.runtime,max_edges=1).preview('alice','P1','B1'))
        self.assertEqual(len(ReadOnlyScopeSnapshotPreview(self.db.runtime,max_edges=2).preview('alice','P1','B1')['snapshot']['edges']), 2)
        self.error(413, 'SCOPE_PREVIEW_BUDGET_EXCEEDED', lambda: ReadOnlyScopeSnapshotPreview(self.db.runtime,max_bytes=1).preview('alice','P1','B1'))
        value = self.read()
        size = len(json.dumps(value['snapshot'],ensure_ascii=False,separators=(',',':')).encode('utf-8'))
        self.assertEqual(ReadOnlyScopeSnapshotPreview(self.db.runtime,max_bytes=size).preview('alice','P1','B1'),value)
        self.error(413, 'SCOPE_PREVIEW_BUDGET_EXCEEDED', lambda: ReadOnlyScopeSnapshotPreview(self.db.runtime,max_bytes=size-1).preview('alice','P1','B1'))
        for option in [dict(max_edges=True),dict(max_bytes=0),dict(statement_timeout_ms=30001)]:
            with self.assertRaisesRegex(ValueError,'INVALID_SCOPE_PREVIEW_BUDGET'):
                ReadOnlyScopeSnapshotPreview(self.db.runtime,**option)

    def test_real_statement_cancellation_rolls_back_and_same_connection_recovers(self):
        raw = self.db.runtime
        class SlowOnce:
            fired = False
            def __getattr__(self, name): return getattr(raw,name)
            def execute(self, query, params=None):
                if query.startswith('SELECT count(*)') and not self.fired:
                    self.fired=True
                    raw.execute('SELECT pg_sleep(0.05)')
                return raw.execute(query,params)
        slow = SlowOnce()
        preview = ReadOnlyScopeSnapshotPreview(slow,statement_timeout_ms=10)
        self.error(503, 'SCOPE_PREVIEW_READ_TIMEOUT', lambda: preview.preview('alice','P1','B1'))
        self.assertTrue(slow.fired)
        self.assertEqual(raw.info.transaction_status,0)
        self.assertEqual(raw.execute("SELECT current_setting('wb.principal',true)").fetchone()[0], '')
        self.assertEqual(len(self.read()['snapshot']['edges']),2)

    def test_concurrent_commits_do_not_mix_date_revisions_or_relation_rows(self):
        d = self.db
        import_sst_identity(d.owner,'P1','V1','SST2','src','prod','RAW-200','r2','source:sst2')
        import_verified_sst_link(d.owner,'P1','B1','R2','V1','SST2','source:link2','r2')
        raw = d.runtime
        class ChangeAfterHeader:
            fired = False
            def __getattr__(self, name): return getattr(raw,name)
            def execute(self, query, params=None):
                result = raw.execute(query,params)
                if 'SELECT b.release_date,b.revision' in query and not self.fired:
                    self.fired=True
                    with infra.psycopg.connect(**d.params,autocommit=True) as writer:
                        BusinessStore(writer).reschedule('alice','P1','B1','2026-11-13',1,'preview-move','approved change','CHG-preview')
                        RelationStore(writer).attach_sst('alice','P1','B1','R2','V1','SST2',8,'preview-concurrent-sst')
                return result
        old = ReadOnlyScopeSnapshotPreview(ChangeAfterHeader()).preview('alice','P1','B1')['snapshot']
        self.assertEqual((old['release_date'],old['date_revision'],old['relation_revision']),('2026-11-12',1,7))
        self.assertIsNone(old['edges'][1]['sst_id'])
        fresh = self.read()['snapshot']
        self.assertEqual((fresh['release_date'],fresh['date_revision'],fresh['relation_revision']),('2026-11-13',2,9))
        self.assertEqual(fresh['edges'][1]['sst_id'],'SST2')

    def test_closed_connection_has_no_unscoped_fallback_and_fresh_connection_recovers(self):
        self.db.runtime.close()
        self.error(503, 'BUSINESS_DATABASE_UNAVAILABLE', self.read)
        with infra.psycopg.connect(**self.db.params,autocommit=True) as connection:
            self.assertEqual(len(ReadOnlyScopeSnapshotPreview(connection).preview('alice','P1','B1')['snapshot']['edges']),2)

    def test_sources_are_raw_unicode_text_and_results_are_detached(self):
        self.db.relations.create_requirement('alice','P1','R中','源\n系统','prod','对象"\\','rev\t1','来源:中','preview-unicode')
        self.db.relations.attach_member('alice','P1','B1','requirement','R中',7,'preview-unicode-member')
        import_verified_requirement_version(self.db.owner,'P1','B1','R中','V1','链接:中\n','rev\t1')
        self.db.relations.attach_requirement_version('alice','P1','B1','R中','V1',8,'preview-unicode-brv')
        value = self.read(requirement_ids=['R中'])
        self.assertEqual(value['snapshot']['edges'][0]['requirement_source']['source_system'],'源\n系统')
        self.assertEqual(value['snapshot']['edges'][0]['brv_source']['source_revision'],'rev\t1')
        value['snapshot']['edges'].clear()
        self.assertEqual(len(self.read(requirement_ids=['R中'])['snapshot']['edges']),1)

    def test_no_python_file_access_or_runtime_store_needed(self):
        with patch('builtins.open',side_effect=AssertionError('UNEXPECTED_FILE_ACCESS')), patch('pathlib.Path.open',side_effect=AssertionError('UNEXPECTED_FILE_ACCESS')):
            self.assertEqual(len(self.read()['snapshot']['edges']),2)

    def test_same_business_ids_in_other_project_cannot_cross_join_sources(self):
        d = self.db
        d.store.create_batch('bob','P2','B1','2026-11-12','preview-p2-batch')
        d.store.create_system('bob','P2','S1','other','prod','other-sys','other-rev','preview-p2-sys')
        d.store.create_version('bob','P2','V1','S1','same label','other','prod','other-ver','other-rev','preview-p2-ver')
        d.relations.create_requirement('bob','P2','R1','other','prod','other-req','other-rev','source:p2-req','preview-p2-req')
        d.relations.attach_member('bob','P2','B1','requirement','R1',1,'preview-p2-r')
        d.relations.attach_member('bob','P2','B1','version','V1',2,'preview-p2-v')
        import_verified_requirement_version(d.owner,'P2','B1','R1','V1','source:p2-rv','other-rev')
        d.relations.attach_requirement_version('bob','P2','B1','R1','V1',3,'preview-p2-brv')
        import_sst_identity(d.owner,'P2','V1','SST1','other','prod','RAW-100','other-rev','source:p2-sst')
        import_verified_sst_link(d.owner,'P2','B1','R1','V1','SST1','source:p2-link','other-rev')
        d.relations.attach_sst('bob','P2','B1','R1','V1','SST1',4,'preview-p2-sst')
        other = self.preview.preview('bob','P2','B1')['snapshot']['edges'][0]
        self.assertEqual(other['requirement_source']['source_system'],'other')
        self.assertEqual(other['brv_source']['source_link_ref'],'source:p2-rv')
        first = self.read()['snapshot']['edges'][0]
        self.assertEqual(first['requirement_source']['source_system'],'src')
        self.assertEqual(first['brv_source']['source_link_ref'],'source:rv')

    def test_database_source_privilege_missing_fails_without_fallback_and_recovers(self):
        role = infra.sql.Identifier(self.db.role)
        self.db.owner.execute(infra.sql.SQL('REVOKE SELECT ON wb.system_version FROM {}').format(role))
        try:
            self.error(503,'SCOPE_PREVIEW_SOURCE_UNAVAILABLE',self.read)
        finally:
            self.db.owner.execute(infra.sql.SQL('GRANT SELECT ON wb.system_version TO {}').format(role))
        self.assertEqual(len(self.read()['snapshot']['edges']),2)
