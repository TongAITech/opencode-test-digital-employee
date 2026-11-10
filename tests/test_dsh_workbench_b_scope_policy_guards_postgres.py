"""F220 configuration regressions plus real PG17 parameter/RI/body boundaries.

F's unchanged independent script is also rerun separately. These are B tests,
not an independent F acceptance, and all injected business rows roll back.
"""
import hashlib
import json
import unittest

import test_dsh_workbench_b_scope_policy_postgres as fixture
from tools.dsh_workbench.scope_source_policy_profile import _parameter_capabilities,_hash


@unittest.skipUnless(fixture.infra.DSN and fixture.infra.psycopg,'real PostgreSQL DSN and psycopg required')
class SourceGuardConfiguration(unittest.TestCase):
    def setUp(self):
        self.case=fixture.ScopeSourcePolicyQualification(methodName='test_migrated_standard_runtime_matches_frozen_profile_without_business_reads')
        self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.db=self.case.db;self.role=fixture.infra.sql.Identifier(self.db.role)
        self.case.matched()

    def grant(self,privilege,role=None):
        # Privilege is a fixed test constant, never a production input.
        self.db.admin.execute(fixture.infra.sql.SQL('GRANT '+privilege+' ON PARAMETER session_replication_role TO {}').format(role or self.role))

    def revoke(self,privilege,role=None):
        self.db.admin.execute(fixture.infra.sql.SQL('REVOKE '+privilege+' ON PARAMETER session_replication_role FROM {}').format(role or self.role))

    def test_f220_parameter_set_capability_fails_in_origin_then_revoke_recovers(self):
        self.grant('SET')
        try:
            rights=_parameter_capabilities(self.db.runtime)
            self.assertEqual(rights['mode'],'origin');self.assertTrue(rights['can_set'])
            self.case.denied('SOURCE_GUARD_PARAMETER_CAPABILITY')
        finally:self.revoke('SET')
        self.case.matched()

    def test_f220_replica_bypasses_fk_revision_but_qualification_rejects_no_data_survives(self):
        d=self.db;self.grant('SET');d.runtime.execute('SET session_replication_role=replica')
        try:
            before=d.owner.execute("SELECT relation_revision FROM wb.release_batch WHERE project_id='P1' AND batch_id='B1'").fetchone()[0]
            try:
                with d.runtime.transaction():
                    d.runtime.execute("SELECT set_config('wb.principal','alice',true)")
                    d.runtime.execute("INSERT INTO wb.batch_requirement_version VALUES('P1','B1','F_NONEXIST_R','F_NONEXIST_V')")
                    self.assertEqual(d.runtime.execute("SELECT count(*) FROM wb.batch_requirement_version WHERE requirement_id='F_NONEXIST_R'").fetchone()[0],1)
                    self.assertEqual(d.runtime.execute("SELECT relation_revision FROM wb.release_batch WHERE project_id='P1' AND batch_id='B1'").fetchone()[0],before)
                    raise RuntimeError('ROLLBACK_GUARD_FIXTURE')
            except RuntimeError as error:
                if str(error)!='ROLLBACK_GUARD_FIXTURE':raise
            self.assertEqual(d.owner.execute("SELECT count(*) FROM wb.batch_requirement_version WHERE requirement_id='F_NONEXIST_R'").fetchone()[0],0)
            value=self.case.denied('SOURCE_GUARDS_REPLICATION_MODE_NOT_ORIGIN')
            self.assertEqual(value['facts']['parameter_capabilities']['mode'],'replica')
            self.assertEqual(d.runtime.execute('SHOW session_replication_role').fetchone()[0],'replica')
        finally:
            d.runtime.execute('SET session_replication_role=origin');self.revoke('SET')
        self.case.matched()

    def test_nonorigin_after_capability_revoked_still_rejects_until_actual_restore(self):
        self.grant('SET');self.db.runtime.execute('SET session_replication_role=replica');self.revoke('SET')
        try:
            self.assertFalse(_parameter_capabilities(self.db.runtime)['can_set'])
            self.case.denied('SOURCE_GUARDS_REPLICATION_MODE_NOT_ORIGIN')
        finally:
            self.grant('SET');self.db.runtime.execute('SET session_replication_role=origin');self.revoke('SET')
        self.case.matched()

    def test_alter_system_capability_is_rejected_without_executing_alter_system(self):
        self.grant('ALTER SYSTEM')
        try:
            rights=_parameter_capabilities(self.db.runtime)
            self.assertTrue(rights['can_alter_system'])
            self.assertEqual(rights['mode'],'origin')
            self.case.denied('SOURCE_GUARD_PARAMETER_CAPABILITY')
        finally:self.revoke('ALTER SYSTEM')
        self.case.matched()

    def test_public_parameter_acl_effective_semantics_in_uncommitted_rollback_only(self):
        # Parameter ACLs are cluster-wide: never commit PUBLIC grants on the
        # shared test cluster or perturb other workers' runtime connections.
        try:
            with self.db.owner.transaction():
                self.db.owner.execute('GRANT SET ON PARAMETER session_replication_role TO PUBLIC')
                self.db.owner.execute('GRANT ALTER SYSTEM ON PARAMETER session_replication_role TO PUBLIC')
                self.db.owner.execute(fixture.infra.sql.SQL('SET LOCAL ROLE {}').format(self.role))
                rights=_parameter_capabilities(self.db.owner)
                self.assertTrue(rights['can_set']);self.assertTrue(rights['can_alter_system'])
                self.assertEqual(_parameter_capabilities(self.db.runtime),{'mode':'origin','can_set':False,'can_alter_system':False})
                raise RuntimeError('ROLLBACK_PUBLIC_PARAMETER_ACL')
        except RuntimeError as error:
            if str(error)!='ROLLBACK_PUBLIC_PARAMETER_ACL':raise
        self.assertEqual(_parameter_capabilities(self.db.runtime),{'mode':'origin','can_set':False,'can_alter_system':False})
        self.case.matched()

    def test_inherited_parameter_capability_is_resolved_by_pg_effective_privileges(self):
        helper=self.db.role+'_inherit';identifier=fixture.infra.sql.Identifier(helper)
        self.db.admin.execute(fixture.infra.sql.SQL('CREATE ROLE {} NOLOGIN').format(identifier))
        try:
            self.grant('SET',identifier)
            self.db.admin.execute(fixture.infra.sql.SQL('GRANT {} TO {} WITH INHERIT TRUE').format(identifier,self.role))
            self.assertTrue(_parameter_capabilities(self.db.runtime)['can_set'])
            value=self.case.denied('SOURCE_GUARD_PARAMETER_CAPABILITY')
            member=next(r for r in value['facts']['memberships'] if r['rolname']==helper)
            self.assertTrue(member['usable_without_set']);self.assertTrue(member['can_set_replication_mode'])
        finally:
            self.db.admin.execute(fixture.infra.sql.SQL('REVOKE {} FROM {}').format(identifier,self.role))
            self.revoke('SET',identifier)
            self.db.admin.execute(fixture.infra.sql.SQL('DROP ROLE {}').format(identifier))
        self.case.matched()

    def test_noinherit_set_role_channel_and_no_set_option_use_actual_pg17_semantics(self):
        helper=self.db.role+'_setpath';identifier=fixture.infra.sql.Identifier(helper)
        self.db.admin.execute(fixture.infra.sql.SQL('CREATE ROLE {} NOLOGIN').format(identifier))
        try:
            self.grant('SET',identifier)
            self.db.admin.execute(fixture.infra.sql.SQL('GRANT {} TO {} WITH INHERIT FALSE').format(identifier,self.role))
            self.assertFalse(_parameter_capabilities(self.db.runtime)['can_set'])
            value=self.case.denied('SOURCE_GUARD_PARAMETER_CAPABILITY_VIA_SET_ROLE',helper)
            member=next(r for r in value['facts']['memberships'] if r['rolname']==helper)
            self.assertFalse(member['usable_without_set']);self.assertTrue(member['can_set_role'])
            # A role need not own/read wb tables to set a backend GUC, then
            # RESET ROLE and carry that GUC back to the real runtime role.
            self.db.runtime.execute(fixture.infra.sql.SQL('SET ROLE {}').format(identifier))
            self.db.runtime.execute('SET session_replication_role=replica');self.db.runtime.execute('RESET ROLE')
            self.case.denied('SOURCE_GUARDS_REPLICATION_MODE_NOT_ORIGIN')
            self.db.runtime.execute(fixture.infra.sql.SQL('SET ROLE {}').format(identifier))
            self.db.runtime.execute('SET session_replication_role=origin');self.db.runtime.execute('RESET ROLE')
            self.db.admin.execute(fixture.infra.sql.SQL('GRANT {} TO {} WITH SET FALSE').format(identifier,self.role))
            value=self.case.denied('UNAPPROVED_ROLE_MEMBERSHIP')
            member=next(r for r in value['facts']['memberships'] if r['rolname']==helper)
            self.assertFalse(member['can_set_role'])
            self.assertFalse(any(r['code']=='SOURCE_GUARD_PARAMETER_CAPABILITY_VIA_SET_ROLE' for r in value['reasons']))
        finally:
            self.db.runtime.execute('RESET ROLE')
            if self.db.runtime.execute('SHOW session_replication_role').fetchone()[0]!='origin':
                self.db.admin.execute(fixture.infra.sql.SQL('GRANT {} TO {} WITH SET TRUE').format(identifier,self.role))
                self.db.runtime.execute(fixture.infra.sql.SQL('SET ROLE {}').format(identifier))
                self.db.runtime.execute('SET session_replication_role=origin');self.db.runtime.execute('RESET ROLE')
            self.db.admin.execute(fixture.infra.sql.SQL('REVOKE {} FROM {}').format(identifier,self.role))
            self.revoke('SET',identifier)
            self.db.admin.execute(fixture.infra.sql.SQL('DROP ROLE {}').format(identifier))
        self.case.matched()

    def test_f220_internal_ri_check_and_parent_action_modes_fail_even_with_valid_fk(self):
        rows=self.db.owner.execute("SELECT tgname FROM pg_trigger WHERE tgrelid='wb.batch_requirement_version'::regclass AND tgisinternal ORDER BY tgname").fetchall()
        names=[next(r[0] for r in rows if '_c_' in r[0]),next(r[0] for r in rows if '_a_' in r[0])]
        for name in names:
            trigger=fixture.infra.sql.Identifier(name)
            for action in ['DISABLE','ENABLE REPLICA','ENABLE ALWAYS']:
                self.db.owner.execute(fixture.infra.sql.SQL('ALTER TABLE wb.batch_requirement_version '+action+' TRIGGER {}').format(trigger))
                try:
                    self.assertTrue(self.db.owner.execute("SELECT bool_and(convalidated) FROM pg_constraint WHERE conrelid='wb.batch_requirement_version'::regclass AND contype='f'").fetchone()[0])
                    self.case.denied('SOURCE_RI_TRIGGER_EXECUTION_PROFILE_DRIFT')
                finally:self.db.owner.execute(fixture.infra.sql.SQL('ALTER TABLE wb.batch_requirement_version ENABLE TRIGGER {}').format(trigger))
        self.case.matched()

    def test_ri_normalization_matches_fresh_database_despite_different_physical_names(self):
        first=self.case.matched()['facts']['ri_triggers']
        physical=self.db.owner.execute("SELECT tgname FROM pg_trigger WHERE tgrelid='wb.batch_requirement_version'::regclass AND tgisinternal ORDER BY tgname").fetchall()
        other=fixture.ScopeSourcePolicyQualification(methodName='test_migrated_standard_runtime_matches_frozen_profile_without_business_reads');other.setUp()
        try:
            second=other.matched()['facts']['ri_triggers']
            self.assertEqual(first,second)
            actual=other.db.owner.execute("SELECT tgname FROM pg_trigger WHERE tgrelid='wb.batch_requirement_version'::regclass AND tgisinternal ORDER BY tgname").fetchall()
            self.assertNotEqual(physical,actual)
        finally:other.doCleanups()

    def test_unknown_function_body_is_hash_only_and_returned_facts_hash_is_reproducible(self):
        original=self.db.owner.execute("SELECT prosrc FROM pg_proc WHERE oid='wb.allowed(text,boolean)'::regprocedure").fetchone()[0]
        sentinel='F_NON_SECRET_BODY_SENTINEL_FOR_HASH_ONLY'
        changed="SELECT true /* "+sentinel+" */"
        self.db.owner.execute(fixture.infra.sql.SQL('CREATE OR REPLACE FUNCTION wb.allowed(p text,writing boolean) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,wb AS {}').format(fixture.infra.sql.Literal(changed)))
        try:
            value=self.case.denied('ALLOWED_FUNCTION_DEFINITION_DRIFT')
            self.assertNotIn(sentinel,json.dumps(value))
            for key in ('allowed_functions','support_functions'):
                for row in value['facts'][key]:self.assertNotIn('prosrc',row)
            self.assertEqual(value['facts']['allowed_functions'][0]['body_sha256'],hashlib.sha256(changed.encode()).hexdigest())
            facts=json.loads(json.dumps(value['facts']));facts['session'].pop('as_of')
            self.assertEqual(value['facts_hash'],_hash(facts))
        finally:self.db.owner.execute(fixture.infra.sql.SQL('CREATE OR REPLACE FUNCTION wb.allowed(p text,writing boolean) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,wb AS {}').format(fixture.infra.sql.Literal(original)))
        self.case.matched()
