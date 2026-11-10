"""Real PG17 source-profile qualification; no schema/privilege mutations in probe."""
import hashlib
import json
import pathlib
import unittest

import test_dsh_workbench_b_scope_postgres as fixture
from tools.dsh_workbench.business_migrations import migrate
from tools.dsh_workbench.scope_source_policy_profile import ReadOnlyScopeSourcePolicyQualification,PROFILE_ID

infra=fixture.prior.prior


@unittest.skipUnless(infra.DSN and infra.psycopg,'real PostgreSQL DSN and psycopg required')
class ScopeSourcePolicyQualification(unittest.TestCase):
    def setUp(self):
        self.db=fixture.Scope(methodName='test_scope_pages_real_join_unsplit_sources_and_bound_cursors')
        self.db.setUp();self.addCleanup(self.db.doCleanups)
        migrate(self.db.owner,target=7)
        self.db.scope_seed()
        self.probe=ReadOnlyScopeSourcePolicyQualification(self.db.runtime)

    def result(self): return self.probe.probe()

    def matched(self):
        value=self.result()
        self.assertEqual(value['status'],'MATCHED_AS_OF',value['reasons'])
        self.assertEqual(value['reasons'],[])
        self.assertFalse(value['admission_authorized'])
        self.assertTrue(value['observation_complete'])
        self.assertEqual(value['profile_id'],PROFILE_ID)
        self.assertEqual(value['as_of_source'],'DATABASE_TRANSACTION_TIMESTAMP')
        return value

    def denied(self, code, subject=None, probe=None):
        value=(probe or self.probe).probe()
        self.assertEqual(value['status'],'UNQUALIFIED')
        self.assertFalse(value['admission_authorized'])
        self.assertTrue(any(r['code']==code and (subject is None or r['subject']==subject) for r in value['reasons']),value['reasons'])
        return value

    def test_migrated_standard_runtime_matches_frozen_profile_without_business_reads(self):
        before=self.db.owner.execute('SELECT count(*) FROM wb.audit').fetchone()[0]
        value=self.matched();again=self.matched()
        self.assertEqual(value['profile_hash'],again['profile_hash'])
        self.assertEqual(value['facts_hash'],again['facts_hash'])
        self.assertEqual(len(value['facts']['tables']),13)
        self.assertEqual(value['facts']['memberships'],[])
        self.assertFalse(value['facts']['allowed_functions'][0]['public_execute'])
        self.assertEqual(self.db.owner.execute('SELECT count(*) FROM wb.audit').fetchone()[0],before)
        artifact=pathlib.Path(__file__).resolve().parents[1]/'tools/dsh_workbench/scope_source_profile_pg17.json'
        manifest=json.loads(artifact.read_text())
        migrations=artifact.parent/'migrations'
        self.assertEqual(manifest['migration_source_sha256'],{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(migrations.glob('*.up.sql'))})
        self.assertIn('NO_DDL_OR_ROLE_FENCE',value['limitation'])

    def test_restrictive_relation_policy_produces_fake_unsplit_but_never_profile_match(self):
        self.assertEqual(self.db.scope.scope('alice','P1','B1',requirement_ids=['R1'])['records'][0]['split_state'],'SPLIT')
        before=self.matched()
        self.db.owner.execute('CREATE POLICY hide_sst ON wb.batch_requirement_version_sst AS RESTRICTIVE FOR SELECT USING(false)')
        try:
            # The original adapter is intentionally unchanged; this is the F202 dependency.
            hidden=self.db.scope.scope('alice','P1','B1',requirement_ids=['R1'])
            self.assertEqual(hidden['records'][0]['split_state'],'UNSPLIT')
            value=self.denied('SOURCE_SCHEMA_OR_SELECT_POLICY_DRIFT','wb.batch_requirement_version_sst')
            self.assertNotEqual(before['facts_hash'],value['facts_hash'])
        finally:self.db.owner.execute('DROP POLICY hide_sst ON wb.batch_requirement_version_sst')
        self.matched()

    def test_permissive_all_or_even_nonapplicable_extra_select_policy_is_not_auto_approved(self):
        self.db.owner.execute('CREATE POLICY broaden ON wb.requirement FOR ALL USING(true) WITH CHECK(true)')
        try:self.denied('SOURCE_SCHEMA_OR_SELECT_POLICY_DRIFT','wb.requirement')
        finally:self.db.owner.execute('DROP POLICY broaden ON wb.requirement')
        role=self.db.role+'_other'
        self.db.admin.execute(infra.sql.SQL('CREATE ROLE {} NOLOGIN').format(infra.sql.Identifier(role)))
        try:
            self.db.owner.execute(infra.sql.SQL('CREATE POLICY other_reader ON wb.sst_identity FOR SELECT TO {} USING(false)').format(infra.sql.Identifier(role)))
            value=self.denied('SOURCE_SCHEMA_OR_SELECT_POLICY_DRIFT','wb.sst_identity')
            row=next(r for r in value['facts']['policies'] if r['polname']=='other_reader')
            self.assertFalse(row['applies_to_role'])
        finally:
            self.db.owner.execute('DROP POLICY IF EXISTS other_reader ON wb.sst_identity')
            self.db.admin.execute(infra.sql.SQL('DROP ROLE {}').format(infra.sql.Identifier(role)))
        self.matched()

    def test_rls_disabled_and_session_row_security_off_fail_closed_then_restore(self):
        self.db.owner.execute('ALTER TABLE wb.sst_identity DISABLE ROW LEVEL SECURITY')
        try:self.denied('SOURCE_RLS_NOT_ACTIVE','wb.sst_identity')
        finally:self.db.owner.execute('ALTER TABLE wb.sst_identity ENABLE ROW LEVEL SECURITY')
        self.db.runtime.execute('SET row_security=off')
        try:
            self.denied('ROW_SECURITY_SETTING_NOT_ON')
            self.assertEqual(self.db.runtime.execute('SHOW row_security').fetchone()[0],'off')
        finally:self.db.runtime.execute('SET row_security=on')
        self.matched()

    def test_missing_source_table_or_column_and_fk_definition_drift_refused(self):
        self.db.owner.execute('ALTER TABLE wb.sst_identity RENAME COLUMN source_revision TO drift_revision')
        try:self.denied('SOURCE_SCHEMA_OR_SELECT_POLICY_DRIFT','wb.sst_identity')
        finally:self.db.owner.execute('ALTER TABLE wb.sst_identity RENAME COLUMN drift_revision TO source_revision')
        self.db.owner.execute('ALTER TABLE wb.verified_sst_link RENAME TO hidden_source_link')
        try:self.denied('SOURCE_RELATION_MISSING','wb.verified_sst_link')
        finally:self.db.owner.execute('ALTER TABLE wb.hidden_source_link RENAME TO verified_sst_link')
        name,definition=self.db.owner.execute("SELECT conname,pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='wb.batch_requirement_version_sst'::regclass AND contype='f'").fetchone()
        self.db.owner.execute(infra.sql.SQL('ALTER TABLE wb.batch_requirement_version_sst DROP CONSTRAINT {}').format(infra.sql.Identifier(name)))
        try:self.denied('SOURCE_SCHEMA_OR_SELECT_POLICY_DRIFT','wb.batch_requirement_version_sst')
        finally:self.db.owner.execute(infra.sql.SQL('ALTER TABLE wb.batch_requirement_version_sst ADD CONSTRAINT {} {}').format(infra.sql.Identifier(name),infra.sql.SQL(definition)))
        self.matched()

    def test_allowed_body_security_path_and_public_execute_drift_rejected(self):
        source=self.matched()['facts']['allowed_functions'][0]['prosrc']
        self.db.owner.execute("CREATE OR REPLACE FUNCTION wb.allowed(p text,writing boolean) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,wb AS $$SELECT true$$")
        try:self.denied('ALLOWED_FUNCTION_DEFINITION_DRIFT')
        finally:self.db.owner.execute(infra.sql.SQL('CREATE OR REPLACE FUNCTION wb.allowed(p text,writing boolean) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,wb AS {}').format(infra.sql.Literal(source)))
        self.db.owner.execute('ALTER FUNCTION wb.allowed(text,boolean) SECURITY INVOKER')
        try:self.denied('ALLOWED_FUNCTION_DEFINITION_DRIFT')
        finally:self.db.owner.execute('ALTER FUNCTION wb.allowed(text,boolean) SECURITY DEFINER')
        self.db.owner.execute('ALTER FUNCTION wb.allowed(text,boolean) SET search_path=public,wb')
        try:self.denied('ALLOWED_FUNCTION_DEFINITION_DRIFT')
        finally:self.db.owner.execute('ALTER FUNCTION wb.allowed(text,boolean) SET search_path=pg_catalog,wb')
        self.db.owner.execute('GRANT EXECUTE ON FUNCTION wb.allowed(text,boolean) TO PUBLIC')
        try:self.denied('ALLOWED_FUNCTION_EXECUTE_GRANT_DRIFT')
        finally:self.db.owner.execute('REVOKE EXECUTE ON FUNCTION wb.allowed(text,boolean) FROM PUBLIC')
        self.matched()

    def test_select_function_or_schema_permissions_and_acl_column_write_are_observed(self):
        role=infra.sql.Identifier(self.db.role)
        self.db.owner.execute(infra.sql.SQL('REVOKE SELECT ON wb.system_version FROM {}').format(role))
        try:self.denied('SOURCE_SELECT_PRIVILEGE_MISSING','wb.system_version')
        finally:self.db.owner.execute(infra.sql.SQL('GRANT SELECT ON wb.system_version TO {}').format(role))
        self.db.owner.execute(infra.sql.SQL('REVOKE EXECUTE ON FUNCTION wb.allowed(text,boolean) FROM {}').format(role))
        try:self.denied('ALLOWED_FUNCTION_EXECUTE_GRANT_DRIFT')
        finally:self.db.owner.execute(infra.sql.SQL('GRANT EXECUTE ON FUNCTION wb.allowed(text,boolean) TO {}').format(role))
        self.db.owner.execute(infra.sql.SQL('GRANT UPDATE(can_write) ON wb.project_acl TO {}').format(role))
        try:self.denied('UNAPPROVED_SOURCE_OR_ACL_PRIVILEGE','wb.project_acl')
        finally:self.db.owner.execute(infra.sql.SQL('REVOKE UPDATE(can_write) ON wb.project_acl FROM {}').format(role))
        self.db.owner.execute(infra.sql.SQL('GRANT INSERT ON wb.verified_sst_link TO {}').format(role))
        try:self.denied('UNAPPROVED_SOURCE_OR_ACL_PRIVILEGE','wb.verified_sst_link')
        finally:self.db.owner.execute(infra.sql.SQL('REVOKE INSERT ON wb.verified_sst_link FROM {}').format(role))
        self.db.owner.execute(infra.sql.SQL('GRANT CREATE ON SCHEMA wb TO {}').format(role))
        try:self.denied('SCHEMA_OWNER_OR_DDL_CAPABILITY','wb')
        finally:self.db.owner.execute(infra.sql.SQL('REVOKE CREATE ON SCHEMA wb FROM {}').format(role))
        self.matched()

    def test_bypass_and_actual_migration_owner_are_not_qualified(self):
        role=infra.sql.Identifier(self.db.role)
        self.db.admin.execute(infra.sql.SQL('ALTER ROLE {} BYPASSRLS').format(role))
        try:self.denied('ELEVATED_ROLE_CAPABILITY')
        finally:self.db.admin.execute(infra.sql.SQL('ALTER ROLE {} NOBYPASSRLS').format(role))
        self.denied('SOURCE_RELATION_OWNER_CAPABILITY','wb.project',ReadOnlyScopeSourcePolicyQualification(self.db.owner))
        self.matched()

    def test_noinherit_membership_to_source_owner_is_still_unapproved_capability(self):
        helper=self.db.role+'_owner'
        helper_id,runtime_id=infra.sql.Identifier(helper),infra.sql.Identifier(self.db.role)
        owner_name=self.db.owner.execute('SELECT current_user').fetchone()[0]
        self.db.admin.execute(infra.sql.SQL('CREATE ROLE {} NOLOGIN').format(helper_id))
        try:
            self.db.admin.execute(infra.sql.SQL('GRANT {} TO {} WITH INHERIT FALSE').format(helper_id,runtime_id))
            self.db.owner.execute(infra.sql.SQL('ALTER TABLE wb.system_version OWNER TO {}').format(helper_id))
            membership=self.db.runtime.execute("SELECT pg_has_role(current_user,%s,'MEMBER'),pg_has_role(current_user,%s,'USAGE')",(helper,helper)).fetchone()
            self.assertEqual(membership,(True,False))
            self.denied('SOURCE_RELATION_OWNER_CAPABILITY','wb.system_version')
            self.denied('UNAPPROVED_ROLE_MEMBERSHIP')
        finally:
            self.db.owner.execute(infra.sql.SQL('ALTER TABLE wb.system_version OWNER TO {}').format(infra.sql.Identifier(owner_name)))
            self.db.admin.execute(infra.sql.SQL('REVOKE {} FROM {}').format(helper_id,runtime_id))
            self.db.owner.execute(infra.sql.SQL('REVOKE ALL ON wb.system_version FROM {}').format(runtime_id))
            self.db.owner.execute(infra.sql.SQL('GRANT SELECT,INSERT ON wb.system_version TO {}').format(runtime_id))
            self.db.admin.execute(infra.sql.SQL('DROP ROLE {}').format(helper_id))
        self.matched()

    def test_switched_session_owner_cannot_hide_behind_runtime_current_role(self):
        self.db.owner.execute(infra.sql.SQL('SET ROLE {}').format(infra.sql.Identifier(self.db.role)))
        try:self.denied('SESSION_ROLE_SWITCH_NOT_QUALIFIED',probe=ReadOnlyScopeSourcePolicyQualification(self.db.owner))
        finally:self.db.owner.execute('RESET ROLE')
        self.matched()

    def test_outer_transaction_not_reused_and_principal_settings_not_changed(self):
        raw=self.db.runtime
        with raw.transaction():
            raw.execute("SELECT set_config('wb.principal','bob',true)")
            with self.assertRaisesRegex(ValueError,'IDLE_CONNECTION_REQUIRED'):
                self.result()
            self.assertEqual(raw.execute("SELECT current_setting('wb.principal',true)").fetchone()[0],'bob')
        before=(raw.execute('SHOW search_path').fetchone()[0],raw.execute('SHOW statement_timeout').fetchone()[0])
        self.matched()
        self.assertEqual(raw.execute("SELECT current_setting('wb.principal',true)").fetchone()[0],'')
        self.assertEqual((raw.execute('SHOW search_path').fetchone()[0],raw.execute('SHOW statement_timeout').fetchone()[0]),before)

    def test_real_catalog_timeout_is_unqualified_with_rollback_and_recovery(self):
        raw=self.db.runtime
        class SlowOnce:
            fired=False
            def __getattr__(self,name):return getattr(raw,name)
            def execute(self,query,params=None):
                if query.startswith('SELECT current_user::text') and not self.fired:
                    self.fired=True;raw.execute('SELECT pg_sleep(0.05)')
                return raw.execute(query,params)
        slow=SlowOnce()
        value=self.denied('CATALOG_READ_TIMEOUT',probe=ReadOnlyScopeSourcePolicyQualification(slow,statement_timeout_ms=10))
        self.assertTrue(slow.fired)
        self.assertFalse(value['observation_complete'])
        self.assertEqual(value['as_of_source'],'CLIENT_FAILURE_OBSERVATION')
        self.assertIsNone(value['facts'])
        self.assertEqual(raw.info.transaction_status,0)
        self.matched()

    def test_committed_policy_then_rolled_back_removal_never_learns_unknown_profile(self):
        self.db.owner.execute('CREATE POLICY unknown_reader ON wb.batch_requirement_version FOR SELECT USING(true)')
        self.denied('SOURCE_SCHEMA_OR_SELECT_POLICY_DRIFT','wb.batch_requirement_version')
        try:
            with self.db.owner.transaction():
                self.db.owner.execute('DROP POLICY unknown_reader ON wb.batch_requirement_version')
                raise RuntimeError('rollback policy removal')
        except RuntimeError:pass
        self.denied('SOURCE_SCHEMA_OR_SELECT_POLICY_DRIFT','wb.batch_requirement_version')
        self.db.owner.execute('DROP POLICY unknown_reader ON wb.batch_requirement_version')
        self.matched()

    def test_closed_connection_returns_unqualified_and_fresh_connection_recovers(self):
        self.db.runtime.close()
        value=self.denied('CATALOG_CONNECTION_CLOSED')
        self.assertFalse(value['observation_complete'])
        with infra.psycopg.connect(**self.db.params,autocommit=True) as connection:
            self.assertEqual(ReadOnlyScopeSourcePolicyQualification(connection).probe()['status'],'MATCHED_AS_OF')

    def test_source_revision_and_append_only_trigger_or_function_drift_rejected(self):
        self.db.owner.execute('ALTER TABLE wb.batch_requirement_version_sst DISABLE TRIGGER append_only')
        try:self.denied('SOURCE_SCHEMA_OR_SELECT_POLICY_DRIFT','wb.batch_requirement_version_sst')
        finally:self.db.owner.execute('ALTER TABLE wb.batch_requirement_version_sst ENABLE TRIGGER append_only')
        self.db.owner.execute('ALTER FUNCTION wb.relation_row_changed() SET search_path=public,wb')
        try:self.denied('SOURCE_REVISION_OR_IMMUTABILITY_FUNCTION_DRIFT')
        finally:self.db.owner.execute('ALTER FUNCTION wb.relation_row_changed() SET search_path=pg_catalog,wb')
        self.matched()

    def test_probe_uses_only_readonly_catalog_queries_and_never_business_rows(self):
        raw=self.db.runtime
        observed=[]
        class Observe:
            def __getattr__(self,name):return getattr(raw,name)
            def execute(self,query,params=None):
                if query.startswith('SELECT current_user::text'):
                    observed.extend([raw.execute('SHOW transaction_read_only').fetchone()[0],raw.execute('SHOW transaction_isolation').fetchone()[0]])
                self_query=query.lower()
                if ' from wb.' in self_query or ' join wb.' in self_query:
                    raise AssertionError('BUSINESS_ROW_QUERY_NOT_ALLOWED')
                return raw.execute(query,params)
        value=ReadOnlyScopeSourcePolicyQualification(Observe()).probe()
        self.assertEqual(value['status'],'MATCHED_AS_OF',value['reasons'])
        self.assertEqual(observed,['on','repeatable read'])

    def test_session_authorization_cannot_mask_privileged_original_backend_role(self):
        original=self.db.owner.execute('SELECT session_user').fetchone()[0]
        self.db.owner.execute(infra.sql.SQL('SET SESSION AUTHORIZATION {}').format(infra.sql.Identifier(self.db.role)))
        try:
            current,session,backend=self.db.owner.execute('SELECT current_user,session_user,(SELECT usename FROM pg_stat_activity WHERE pid=pg_backend_pid())').fetchone()
            self.assertEqual((current,session),(self.db.role,self.db.role))
            self.assertEqual(backend,original)
            self.denied('AUTHENTICATED_BACKEND_ROLE_MISMATCH',probe=ReadOnlyScopeSourcePolicyQualification(self.db.owner))
        finally:self.db.owner.execute('RESET SESSION AUTHORIZATION')
        self.matched()
