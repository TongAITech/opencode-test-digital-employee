"""Explicit 009 qualification against the accepted disposable PG schema."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_dsh_workbench_b_project_metadata_postgres as fixture
from tools.dsh_workbench.project_metadata_migrations import MANIFEST_SHA256, downgrade_project_metadata, grant_project_metadata_runtime
from tools.dsh_workbench.scope_source_policy_profile import ReadOnlyScopeSourcePolicyQualification
from tools.dsh_workbench.scope_source_policy_profile_009 import ReadOnlyScopeSourcePolicyQualification009


@unittest.skipUnless(fixture.infra.DSN and fixture.infra.psycopg, 'real PostgreSQL required')
class Optional009Profile(unittest.TestCase):
    def setUp(self):
        self.case = fixture.MetadataPG('test_009_profile_v2_explicit_unqualified_not_learned')
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.db = self.case.db
        self.admin = self.db.owner.execute('SELECT current_user::text').fetchone()[0]
        self.probe = ReadOnlyScopeSourcePolicyQualification009(
            self.db.runtime, admin_role=self.admin, executor_role=self.case.executor)

    def matched(self):
        result = self.probe.probe()
        self.assertEqual(result['status'], 'MATCHED_AS_OF', result['reasons'])
        self.assertEqual(result['reasons'], [])
        self.assertFalse(result['admission_authorized'])
        return result

    def drift(self, subject):
        result = self.probe.probe()
        self.assertEqual(result['status'], 'UNQUALIFIED', result['reasons'])
        self.assertFalse(result['admission_authorized'])
        self.assertIn({'code': 'OPTIONAL_009_CATALOG_PROFILE_DRIFT', 'subject': subject}, result['reasons'])
        return result

    def test_same_fixed_profile_fresh_roles_and_default_does_not_upgrade(self):
        first = self.matched()
        self.assertEqual(self.matched()['facts_hash'], first['facts_hash'])
        another = fixture.MetadataPG('test_009_profile_v2_explicit_unqualified_not_learned')
        another.setUp()
        self.addCleanup(another.doCleanups)
        second = ReadOnlyScopeSourcePolicyQualification009(
            another.db.runtime, admin_role=self.admin, executor_role=another.executor).probe()
        self.assertEqual(second['status'], 'MATCHED_AS_OF', second['reasons'])
        self.assertEqual(first['facts']['profile_009_sections'], second['facts']['profile_009_sections'])
        self.assertEqual(ReadOnlyScopeSourcePolicyQualification(self.db.runtime).probe()['status'], 'UNQUALIFIED')

    def test_explicit_009_never_downgrades_to_default(self):
        self.matched()
        self.assertTrue(downgrade_project_metadata(self.db.owner))
        self.drift('definitions')
        self.assertEqual(ReadOnlyScopeSourcePolicyQualification(self.db.runtime).probe()['status'], 'MATCHED_AS_OF')

    def test_wrong_trusted_role_identities_reject(self):
        for admin, executor in [(self.admin, 'missing-metadata-executor'), ('other-admin', self.case.executor)]:
            result = ReadOnlyScopeSourcePolicyQualification009(self.db.runtime, admin_role=admin, executor_role=executor).probe()
            self.assertEqual(result['status'], 'UNQUALIFIED')
            self.assertFalse(result['admission_authorized'])

    def test_executor_flag_drift_and_restore(self):
        role = fixture.infra.sql.Identifier(self.case.executor)
        self.db.owner.execute(fixture.infra.sql.SQL('ALTER ROLE {} INHERIT').format(role))
        try:
            self.drift('roles')
        finally:
            self.db.owner.execute(fixture.infra.sql.SQL('ALTER ROLE {} NOINHERIT').format(role))
        self.matched()

    def test_executor_column_and_runtime_function_grant_revoke_restore(self):
        sql = fixture.infra.sql
        executor = sql.Identifier(self.case.executor)
        runtime = sql.Identifier(self.db.role)
        self.db.owner.execute(sql.SQL('REVOKE UPDATE(namespace_revision) ON wb.project_namespace FROM {}').format(executor))
        try:
            self.drift('column_boundary')
        finally:
            self.db.owner.execute(sql.SQL('GRANT UPDATE(namespace_revision) ON wb.project_namespace TO {}').format(executor))
        self.db.owner.execute(sql.SQL('REVOKE EXECUTE ON FUNCTION wb.get_project_metadata(text) FROM {}').format(runtime))
        try:
            self.drift('function_boundary')
        finally:
            grant_project_metadata_runtime(self.db.owner, self.db.role)
        self.matched()

    def test_new_governance_trigger_and_body_drift_redacts_literal(self):
        owner = self.db.owner
        owner.execute('ALTER TABLE wb.project_namespace_population DISABLE TRIGGER metadata_governance_advance')
        try:
            self.drift('definitions')
        finally:
            owner.execute('ALTER TABLE wb.project_namespace_population ENABLE TRIGGER metadata_governance_advance')
        original = owner.execute("SELECT pg_get_functiondef('wb.metadata_governance_advance()'::regprocedure)").fetchone()[0]
        changed = original.replace('BEGIN', 'BEGIN\n -- profile-literal-sentinel', 1)
        owner.execute(changed)
        try:
            value = self.drift('definitions')
            self.assertNotIn('profile-literal-sentinel', json.dumps(value))
        finally:
            owner.execute(original)
        self.matched()

    def test_new_composite_fk_internal_execution_drift(self):
        owner = self.db.owner
        name = owner.execute("""SELECT t.tgname FROM pg_trigger t JOIN pg_constraint c ON c.oid=t.tgconstraint
            WHERE t.tgrelid='wb.project_metadata_result'::regclass AND t.tgisinternal
            AND c.confrelid='wb.request_log'::regclass ORDER BY t.tgname LIMIT 1""").fetchone()[0]
        sql = fixture.infra.sql
        owner.execute(sql.SQL('ALTER TABLE wb.project_metadata_result DISABLE TRIGGER {}').format(sql.Identifier(name)))
        try:
            self.drift('definitions')
        finally:
            owner.execute(sql.SQL('ALTER TABLE wb.project_metadata_result ENABLE TRIGGER {}').format(sql.Identifier(name)))
        self.matched()

    def test_009_policy_drift_rolled_back_and_no_business_rows_read(self):
        first = self.matched()
        with self.assertRaisesRegex(RuntimeError, 'ROLLBACK_POLICY_FIXTURE'):
            with self.db.owner.transaction():
                self.db.owner.execute('CREATE POLICY transient_restrict ON wb.project_name_binding AS RESTRICTIVE FOR SELECT USING(false)')
                raise RuntimeError('ROLLBACK_POLICY_FIXTURE')
        self.assertEqual(self.matched()['facts_hash'], first['facts_hash'])
        self.db.owner.execute('CREATE POLICY observed_restrict ON wb.project_name_binding AS RESTRICTIVE FOR SELECT USING(false)')
        try:
            self.drift('definitions')
        finally:
            self.db.owner.execute('DROP POLICY observed_restrict ON wb.project_name_binding')
        self.case.govern()
        self.case.store.rename('alice', self.case.request())
        count = self.case.scalar('SELECT count(*) FROM wb.audit')
        self.assertEqual(self.matched()['facts_hash'], first['facts_hash'])
        self.assertEqual(self.case.scalar('SELECT count(*) FROM wb.audit'), count)

    def test_outer_transaction_rejected_and_session_settings_restored(self):
        conn = self.db.runtime
        with conn.transaction():
            with self.assertRaisesRegex(ValueError, 'IDLE_CONNECTION_REQUIRED'):
                self.probe.probe()
        original = conn.execute("SELECT current_setting('search_path'),current_setting('statement_timeout')").fetchone()
        self.matched()
        self.assertEqual(conn.execute("SELECT current_setting('search_path'),current_setting('statement_timeout')").fetchone(), original)


class Optional009Artifact(unittest.TestCase):
    def test_manifest_binding_and_pinned_artifact_reject_tamper(self):
        path = Path(__file__).resolve().parents[1] / 'tools/dsh_workbench/scope_source_profile_009_pg17.json'
        artifact = json.loads(path.read_text())
        self.assertEqual(artifact['migration_manifest_sha256'], MANIFEST_SHA256)
        del artifact['section_hashes']['role_boundary']
        class NoDatabase:
            autocommit = True
            def execute(self, *_):
                raise AssertionError('artifact must be checked before SQL')
        with patch('tools.dsh_workbench.scope_source_policy_profile.Path.read_text', return_value=json.dumps(artifact)):
            with self.assertRaisesRegex(ValueError, 'SCOPE_SOURCE_PROFILE_ARTIFACT_INVALID'):
                ReadOnlyScopeSourcePolicyQualification009(NoDatabase(), admin_role='owner', executor_role='executor')
