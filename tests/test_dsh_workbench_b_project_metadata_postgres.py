"""Optional 009 genuine PG tests, never default-profile or Host acceptance."""
import copy
import json
import os
import pathlib
import threading
import tempfile
import time
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import test_dsh_workbench_b_postgres as infra
from tools.dsh_workbench.business_migrations import migrate
from tools.dsh_workbench.project_metadata_codec import parse_rename_request
from tools.dsh_workbench.project_metadata_migrations import migrate_project_metadata, downgrade_project_metadata, grant_project_metadata_runtime, _manifest, _plan
from tools.dsh_workbench.project_metadata_store import ProjectMetadataStore
from tools.dsh_workbench.business_store import BusinessError, BusinessStore


@unittest.skipUnless(infra.DSN and infra.psycopg, 'real PostgreSQL required')
class MetadataPG(unittest.TestCase):
    def setUp(self):
        self.db = infra.PostgresIdentity(methodName='test_date_unique_cross_project_leap_and_invalid_dates')
        self.db.setUp(); self.db._cleanups=[]
        migrate(self.db.owner, target=7)
        for version in [2,3,4,6,7]:
            runtime=list(infra.MIGRATION.glob('%03d_*.runtime.sql' % version))[0]
            self.db.owner.execute(runtime.read_text().replace('wb_runtime', '"'+self.db.role+'"'))
        self.executor = self.db.role + '_metadata'
        self.db.admin.execute(infra.sql.SQL('CREATE ROLE {} NOLOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB NOREPLICATION').format(infra.sql.Identifier(self.executor)))
        # LIFO: fixture drops DB before dedicated cluster role cleanup.
        self.addCleanup(self.drop_executor)
        self.assertTrue(migrate_project_metadata(self.db.owner, self.executor))
        grant_project_metadata_runtime(self.db.owner, self.db.role)
        self.store = ProjectMetadataStore(self.db.runtime)

    def drop_executor(self):
        self.db.cleanup()
        self.db.admin = infra.psycopg.connect(infra.DSN, autocommit=True)
        self.db.admin.execute(infra.sql.SQL('DROP ROLE {}').format(infra.sql.Identifier(self.executor)))
        self.db.admin.close()

    def govern(self):
        with self.db.owner.transaction():
            self.db.owner.execute("INSERT INTO wb.project_namespace VALUES('NS','GOVERNANCE_HOLD','project-name/utf8-exact-v1','admin:complete','1',%s,1,true)", ('a'*64,))
            self.db.owner.execute("INSERT INTO wb.project_name_binding SELECT project_id,'NS','PROJECT',convert_to(name,'UTF8'),1,'admin:complete' FROM wb.project")
            self.db.owner.execute("INSERT INTO wb.project_namespace_population SELECT 'NS',project_id,'MEMBER','admin:complete',NULL FROM wb.project")
            self.db.owner.execute("UPDATE wb.project_namespace SET state='NAMING_ACTIVE'")

    def request(self, name='renamed', key='r1', metadata='1', access=None, reason='approved', project='P1'):
        if access is None:
            access = str(self.db.owner.execute('SELECT access_scope_revision FROM wb.project WHERE project_id=%s', (project,)).fetchone()[0])
        return parse_rename_request(json.dumps(dict(request_id=key, expected_metadata_revision=metadata,
            expected_access_scope_revision=access, changes={'name':name}, reason=reason), ensure_ascii=False).encode(), project)

    def error(self, code, fn):
        with self.assertRaises(BusinessError) as caught: fn()
        self.assertEqual(code, caught.exception.code)

    def wait_blocked(self, connection):
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            if self.db.owner.execute('SELECT cardinality(pg_blocking_pids(%s))', (connection.info.backend_pid,)).fetchone()[0]:return
            time.sleep(.01)
        self.fail('expected actual PostgreSQL lock wait was not observed')

    def scalar(self, query, args=()):
        return self.db.owner.execute(query,args).fetchone()[0]

    def test_rename_single_fact_receipt_and_zero_batch_effect(self):
        self.govern(); self.db.store.create_batch('alice','P1','B','2027-01-01','b')
        before=self.db.owner.execute('SELECT * FROM wb.release_batch').fetchall()
        receipt=self.store.rename('alice',self.request())
        self.assertEqual(receipt['outcome'],'APPLIED');self.assertEqual(receipt['applied_metadata_revision'],'2')
        self.assertEqual(self.scalar("SELECT name FROM wb.project WHERE project_id='P1'"),'renamed')
        self.assertEqual(self.scalar("SELECT name_key FROM wb.project_name_binding WHERE project_id='P1'"),b'renamed')
        self.assertEqual(self.db.owner.execute('SELECT * FROM wb.release_batch').fetchall(),before)
        self.assertEqual(self.scalar('SELECT count(*) FROM wb.project_metadata_history'),1)
        self.assertEqual(self.scalar('SELECT count(*) FROM wb.project_metadata_outbox'),1)

    def test_no_change_replay_and_old_receipt_not_latest(self):
        self.govern(); r=self.request('first'); first=self.store.rename('alice',r)
        self.assertEqual(first['outcome'],'NO_CHANGE');self.assertIsNone(first['history_revision'])
        self.assertEqual(self.scalar('SELECT count(*) FROM wb.project_metadata_history'),0)
        self.store.rename('alice',self.request('next','r2'))
        self.assertEqual(self.store.rename('alice',r),first)
        self.assertEqual(self.store.get_metadata('alice','P1')['name'],'next')
        self.assertEqual(self.scalar('SELECT count(*) FROM wb.project_metadata_result'),2)

    def test_commit_response_unknown_replay_on_new_connection(self):
        self.govern();r=self.request()
        def lose_reply():
            self.store.rename('alice',r)  # actual commit, reply discarded at caller boundary
            raise ConnectionError('TEST_REPLY_LOST_AFTER_COMMIT')
        with self.assertRaisesRegex(ConnectionError,'TEST_REPLY_LOST'):lose_reply()
        original=self.scalar('SELECT receipt FROM wb.project_metadata_result')
        with infra.psycopg.connect(**self.db.params,autocommit=True) as fresh:
            self.assertEqual(ProjectMetadataStore(fresh).rename('alice',r),original)
        self.assertEqual(self.scalar('SELECT count(*) FROM wb.project_metadata_outbox'),1)

    def test_hidden_duplicate_and_exact_byte_names(self):
        self.govern();self.error('NAME_UNAVAILABLE',lambda:self.store.rename('alice',self.request('second')))
        self.assertEqual(self.scalar('SELECT count(*) FROM wb.project_metadata_result'),0)
        self.store.rename('alice',self.request('Second'))
        self.assertEqual(self.store.get_metadata('bob','P2')['name'],'second')

    def test_unbound_unknown_governance_complete_and_new_project_stops_domain(self):
        self.error('METADATA_NOT_GOVERNED',lambda:self.store.rename('alice',self.request()))
        with self.assertRaises(infra.psycopg.Error):
            with self.db.owner.transaction():
                self.db.owner.execute("INSERT INTO wb.project_namespace VALUES('bad','NAMING_ACTIVE','project-name/utf8-exact-v1','x','1',%s,1,true)",('a'*64,))
        self.govern();self.db.owner.execute("INSERT INTO wb.project(project_id,name) VALUES('P3','third')")
        self.assertEqual(self.scalar('SELECT state FROM wb.project_namespace'),'GOVERNANCE_HOLD')
        self.error('GOVERNANCE_HOLD',lambda:self.store.rename('alice',self.request()))

    def admin_connection(self):
        connection=infra.psycopg.connect(**dict(infra.conninfo_to_dict(infra.DSN),dbname=self.db.name),autocommit=True)
        connection.execute("SET lock_timeout='3s'")
        connection.execute("SET statement_timeout='6s'")
        return connection

    def activate_original_two_members(self, connection):
        connection.execute("INSERT INTO wb.project_namespace VALUES('race','NAMING_ACTIVE','project-name/utf8-exact-v1','admin:original-two','1',%s,1,true)",('a'*64,))
        connection.execute("INSERT INTO wb.project_name_binding SELECT project_id,'race','PROJECT',convert_to(name,'UTF8'),1,'admin:original-two' FROM wb.project WHERE project_id IN ('P1','P2')")
        connection.execute("INSERT INTO wb.project_namespace_population VALUES('race','P1','MEMBER','admin:original-two',NULL),('race','P2','MEMBER','admin:original-two',NULL)")
        connection.execute('SET CONSTRAINTS ALL IMMEDIATE')

    def blocked_or_finished(self, connection, future):
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            if self.db.admin.execute('SELECT cardinality(pg_blocking_pids(%s))',(connection.info.backend_pid,)).fetchone()[0]:return True
            if future.done():return False
            time.sleep(.01)
        self.fail('neither PostgreSQL blocking nor operation completion observed')

    def test_governance_activation_then_project_insert_serializes_and_stops(self):
        with self.admin_connection() as activation,self.admin_connection() as provision:
            activation.execute('BEGIN');self.activate_original_two_members(activation)
            provision.execute('BEGIN')
            def insert():
                provision.execute("INSERT INTO wb.project(project_id,name) VALUES('P3','third')")
                provision.execute('SET CONSTRAINTS ALL IMMEDIATE')
            with ThreadPoolExecutor(1) as pool:
                future=pool.submit(insert)
                blocked=self.blocked_or_finished(provision,future)
                activation.execute('COMMIT');future.result(3);provision.execute('COMMIT')
        self.assertEqual(self.scalar("SELECT state FROM wb.project_namespace WHERE namespace_ref='race'"),'GOVERNANCE_HOLD')
        self.assertTrue(blocked)
        self.error('GOVERNANCE_HOLD',lambda:self.store.rename('alice',self.request('first')))
        self.assertEqual(self.scalar('SELECT count(*) FROM wb.project_metadata_result'),0)

    def test_governance_project_insert_then_activation_rejects_incomplete_snapshot(self):
        with self.admin_connection() as provision,self.admin_connection() as activation:
            provision.execute('BEGIN')
            provision.execute("INSERT INTO wb.project(project_id,name) VALUES('P3','third')")
            provision.execute('SET CONSTRAINTS ALL IMMEDIATE')
            def activate():
                with activation.transaction():self.activate_original_two_members(activation)
            with ThreadPoolExecutor(1) as pool:
                future=pool.submit(activate)
                blocked=self.blocked_or_finished(activation,future)
                provision.execute('COMMIT')
                with self.assertRaises(infra.psycopg.Error) as caught:future.result(3)
            self.assertEqual(caught.exception.diag.message_primary,'GOVERNANCE_POPULATION_INCOMPLETE')
        self.assertTrue(blocked)
        self.assertEqual(self.scalar('SELECT count(*) FROM wb.project_namespace'),0)
        self.assertEqual(self.scalar('SELECT count(*) FROM wb.project_name_binding'),0)
        self.assertEqual(self.scalar('SELECT count(*) FROM wb.project'),3)

    def test_governance_repeatable_read_stale_writer_aborts_after_wait(self):
        with self.admin_connection() as provision,self.admin_connection() as stale:
            stale.execute('BEGIN ISOLATION LEVEL REPEATABLE READ')
            self.assertEqual(stale.execute('SELECT count(*) FROM wb.project').fetchone()[0],2)
            provision.execute('BEGIN')
            provision.execute("INSERT INTO wb.project(project_id,name) VALUES('P3','third')")
            provision.execute('SET CONSTRAINTS ALL IMMEDIATE')
            with ThreadPoolExecutor(1) as pool:
                future=pool.submit(self.activate_original_two_members,stale)
                blocked=self.blocked_or_finished(stale,future)
                provision.execute('COMMIT')
                try:
                    with self.assertRaises(infra.psycopg.Error) as caught:future.result(3)
                finally:stale.execute('ROLLBACK')
            self.assertEqual(caught.exception.sqlstate,'40001')
        self.assertTrue(blocked)
        self.assertEqual(self.scalar('SELECT count(*) FROM wb.project_namespace'),0)
        self.assertEqual(self.scalar('SELECT count(*) FROM wb.project'),3)

    def test_governance_provision_rollback_releases_fence_and_allows_activation(self):
        with self.admin_connection() as provision,self.admin_connection() as activation:
            provision.execute('BEGIN')
            provision.execute("INSERT INTO wb.project(project_id,name) VALUES('P3','third')")
            def activate():
                with activation.transaction():self.activate_original_two_members(activation)
            with ThreadPoolExecutor(1) as pool:
                future=pool.submit(activate)
                self.wait_blocked(activation);provision.execute('ROLLBACK');future.result(3)
        self.assertEqual(self.scalar('SELECT count(*) FROM wb.project'),2)
        self.assertEqual(self.scalar('SELECT state FROM wb.project_namespace'),'NAMING_ACTIVE')
        self.assertEqual(self.store.rename('alice',self.request())['outcome'],'APPLIED')

    def test_governance_activation_rollback_releases_waiting_provision(self):
        with self.admin_connection() as activation,self.admin_connection() as provision:
            activation.execute('BEGIN');self.activate_original_two_members(activation)
            with ThreadPoolExecutor(1) as pool:
                future=pool.submit(provision.execute,"INSERT INTO wb.project(project_id,name) VALUES('P3','third')")
                self.wait_blocked(provision);activation.execute('ROLLBACK');future.result(3)
        self.assertEqual(self.scalar('SELECT count(*) FROM wb.project_namespace'),0)
        self.assertEqual(self.scalar('SELECT count(*) FROM wb.project_name_binding'),0)
        self.assertEqual(self.scalar('SELECT count(*) FROM wb.project'),3)

    def test_governance_active_rename_then_provision_holds_domain_after_commit(self):
        self.govern();r=self.request()
        with infra.psycopg.connect(**self.db.params,autocommit=True) as rename,self.admin_connection() as provision:
            rename.execute('BEGIN');rename.execute("SELECT set_config('wb.principal','alice',true)")
            receipt=rename.execute('SELECT wb.rename_project_metadata(%s,%s,%s,%s,%s,%s,%s)',('P1','r1',r.expected_metadata_revision,r.expected_access_scope_revision,r.name,r.reason.encode(),r.canonical_bytes)).fetchone()[0]
            with ThreadPoolExecutor(1) as pool:
                future=pool.submit(provision.execute,"INSERT INTO wb.project(project_id,name) VALUES('P3','third')")
                self.wait_blocked(provision);rename.execute('COMMIT');future.result(3)
        self.assertEqual(receipt,self.store.rename('alice',r))
        self.assertEqual(self.scalar('SELECT state FROM wb.project_namespace'),'GOVERNANCE_HOLD')
        self.assertEqual(self.scalar('SELECT count(*) FROM wb.project_metadata_history'),1)
        self.error('GOVERNANCE_HOLD',lambda:self.store.rename('alice',self.request('new','r2','2')))

    def test_governance_fence_not_taken_by_ordinary_rename_or_acl_write(self):
        self.govern()
        epoch=self.scalar('SELECT epoch FROM wb.project_metadata_governance_fence')
        with self.admin_connection() as hold:
            hold.execute('BEGIN');hold.execute('UPDATE wb.project_metadata_governance_fence SET epoch=epoch+1')
            try:
                self.assertEqual(self.store.rename('alice',self.request())['outcome'],'APPLIED')
                self.db.owner.execute("UPDATE wb.project_acl SET can_write=false WHERE principal='bob' AND project_id='P2'")
            finally:hold.execute('ROLLBACK')
        self.assertEqual(self.scalar('SELECT epoch FROM wb.project_metadata_governance_fence'),epoch)
        self.error('FORBIDDEN',lambda:self.store.rename('bob',self.request(project='P2')))
        self.assertIs(self.store.get_metadata('bob','P2')['can_rename'],False)

    def test_nondeterministic_icu_name_columns_and_argument_still_compare_bytes(self):
        self.govern(); owner=self.db.owner
        try:
            owner.execute("CREATE COLLATION wb.m1_casefold (provider=icu,locale='und-u-ks-level2',deterministic=false)")
        except infra.psycopg.errors.FeatureNotSupported:
            if os.environ.get('WB_PG_REQUIRE_ICU') == '1':raise
            self.skipTest('PostgreSQL server was built without ICU')
        self.assertTrue(self.scalar("SELECT 'first' COLLATE wb.m1_casefold = 'FIRST'"))
        self.assertNotEqual(self.scalar("SELECT convert_to('first','UTF8')"),self.scalar("SELECT convert_to('FIRST','UTF8')"))
        owner.execute('ALTER TABLE wb.project ALTER COLUMN name TYPE text COLLATE wb.m1_casefold')
        owner.execute('ALTER TABLE wb.project_metadata_history ALTER COLUMN old_name TYPE text COLLATE wb.m1_casefold, ALTER COLUMN new_name TYPE text COLLATE wb.m1_casefold')
        self.assertEqual(self.store.rename('alice',self.request('FIRST'))['outcome'],'APPLIED')
        r=self.request('first','r2','2')
        with self.db.runtime.transaction():
            self.db.runtime.execute("SELECT set_config('wb.principal','alice',true)")
            receipt=self.db.runtime.execute('SELECT wb.rename_project_metadata(%s,%s,%s,%s,%s COLLATE wb.m1_casefold,%s,%s)',('P1','r2',r.expected_metadata_revision,r.expected_access_scope_revision,r.name,r.reason.encode(),r.canonical_bytes)).fetchone()[0]
        self.assertEqual(receipt['outcome'],'APPLIED')
        self.assertEqual(self.scalar('SELECT count(*) FROM wb.project_metadata_history'),2)
        self.assertEqual(self.store.rename('alice',self.request('first','r3','3'))['outcome'],'NO_CHANGE')

    def test_reason_nul_controls_2048_and_audit_reversible(self):
        self.govern(); reason='\x00\n\r\t\b\f\\"'+''.join(chr(i) for i in range(32))+'😀'
        r=self.request(reason=reason);self.store.rename('alice',r)
        self.assertEqual(self.scalar('SELECT reason_utf8 FROM wb.project_metadata_history'),reason.encode())
        self.assertEqual(bytes.fromhex(self.scalar("SELECT detail->>'reason_utf8_hex' FROM wb.audit WHERE action='project.metadata.update/v1'")),reason.encode())
        self.store.rename('alice',self.request('last','r2','2',reason='😀'*512))
        self.assertEqual(len(self.scalar('SELECT reason_utf8 FROM wb.project_metadata_history WHERE revision=3')),2048)

    def test_direct_table_dml_and_function_forged_canonical_rejected(self):
        self.govern()
        with self.assertRaises(infra.psycopg.Error):self.db.runtime.execute("UPDATE wb.project SET name='bypass'")
        with self.assertRaises(infra.psycopg.Error):self.db.runtime.execute("UPDATE wb.project_name_binding SET name_key='x'")
        with self.assertRaises(infra.psycopg.Error):self.db.runtime.execute('UPDATE wb.project_metadata_governance_fence SET epoch=1')
        r=self.request()
        with self.assertRaises(infra.psycopg.Error):
            with self.db.runtime.transaction():
                self.db.runtime.execute("SELECT set_config('wb.principal','alice',true)")
                self.db.runtime.execute('SELECT wb.rename_project_metadata(%s,%s,%s,%s,%s,%s,%s)',('P1','r1',r.expected_metadata_revision,r.expected_access_scope_revision,r.name,b'approved',b'forged'))
        self.assertEqual(self.scalar('SELECT count(*) FROM wb.project_metadata_result'),0)

    def test_cas_access_revoke_restore_and_original_subject(self):
        self.govern();r=self.request();receipt=self.store.rename('alice',r)
        self.error('REVISION_CONFLICT',lambda:self.store.rename('alice',self.request('next','r2','1')))
        self.error('FORBIDDEN',lambda:self.store.rename('bob',r))
        self.db.owner.execute("DELETE FROM wb.project_acl WHERE project_id='P1' AND principal='alice'")
        self.error('FORBIDDEN',lambda:self.store.rename('alice',r))
        self.db.owner.execute("INSERT INTO wb.project_acl VALUES('P1','alice',true)")
        self.assertEqual(self.store.rename('alice',r),receipt)
        self.error('REVISION_CONFLICT',lambda:self.store.rename('alice',self.request('next','r2','2',r.expected_access_scope_revision)))
        self.store.rename('alice',self.request('next','r3','2'))

    def test_domain_stop_prevents_new_but_historical_receipt_survives(self):
        self.govern();r=self.request();receipt=self.store.rename('alice',r)
        self.db.owner.execute("UPDATE wb.project_namespace SET state='GOVERNANCE_HOLD',namespace_revision=namespace_revision+1")
        self.assertEqual(self.store.rename('alice',r),receipt)
        self.assertIs(self.store.get_metadata('alice','P1')['can_rename'],False)
        self.error('GOVERNANCE_HOLD',lambda:self.store.rename('alice',self.request('other','r2','2')))

    def test_audit_and_outbox_faults_rollback_all_then_recover(self):
        self.govern()
        for table in ['audit','project_metadata_history','project_metadata_outbox']:
            self.db.owner.execute("CREATE OR REPLACE FUNCTION wb.inject_metadata_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'fault'; END $$")
            self.db.owner.execute('CREATE TRIGGER injected BEFORE INSERT ON wb.'+table+' FOR EACH ROW EXECUTE FUNCTION wb.inject_metadata_fault()')
            with self.assertRaises(infra.psycopg.Error):self.store.rename('alice',self.request())
            self.assertEqual(self.scalar("SELECT name FROM wb.project WHERE project_id='P1'"),'first')
            for target in ['request_log','audit','project_metadata_result','project_metadata_history','project_metadata_outbox']:
                self.assertEqual(self.scalar('SELECT count(*) FROM wb.'+target),0,target)
            self.assertEqual(self.scalar("SELECT name_key FROM wb.project_name_binding WHERE project_id='P1'"),b'first')
            self.db.owner.execute('DROP TRIGGER injected ON wb.'+table)
        self.store.rename('alice',self.request())

    def test_outer_transaction_refused_without_subject_contamination(self):
        self.govern()
        with self.db.runtime.transaction():
            self.db.runtime.execute("SELECT set_config('wb.principal','bob',true)")
            with self.assertRaises(ValueError):self.store.rename('alice',self.request())
            self.assertEqual(self.db.runtime.execute("SELECT current_setting('wb.principal')").fetchone()[0],'bob')
        self.store.rename('alice',self.request())
        self.assertEqual(self.db.runtime.execute("SELECT current_setting('wb.principal',true)").fetchone()[0],'')

    def test_executor_login_membership_and_parameter_capability_rejected(self):
        ident=infra.sql.Identifier(self.executor)
        admin=self.db.admin
        admin.execute(infra.sql.SQL('ALTER ROLE {} LOGIN').format(ident))
        try:
            with self.assertRaisesRegex(ValueError,'NOT_DEDICATED'):migrate_project_metadata(self.db.owner,self.executor)
        finally:admin.execute(infra.sql.SQL('ALTER ROLE {} NOLOGIN').format(ident))
        admin.execute(infra.sql.SQL('GRANT {} TO {}').format(ident,infra.sql.Identifier(self.db.role)))
        try:
            with self.assertRaisesRegex(ValueError,'HAS_MEMBERSHIP'):migrate_project_metadata(self.db.owner,self.executor)
        finally:admin.execute(infra.sql.SQL('REVOKE {} FROM {}').format(ident,infra.sql.Identifier(self.db.role)))
        admin.execute(infra.sql.SQL('GRANT SET ON PARAMETER session_replication_role TO {}').format(ident))
        try:
            with self.assertRaisesRegex(ValueError,'DANGEROUS_PARAMETER_RIGHTS'):migrate_project_metadata(self.db.owner,self.executor)
        finally:admin.execute(infra.sql.SQL('REVOKE SET ON PARAMETER session_replication_role FROM {}').format(ident))
        self.assertFalse(migrate_project_metadata(self.db.owner,self.executor))

    def test_audit_history_receipt_outbox_append_only(self):
        self.govern();self.store.rename('alice',self.request())
        for table in ['project_metadata_result','project_metadata_history','project_metadata_outbox']:
            with self.assertRaises(infra.psycopg.Error) as caught:self.db.owner.execute('DELETE FROM wb.'+table)
            self.assertEqual(caught.exception.diag.message_primary,'APPEND_ONLY')
        self.assertEqual(self.scalar('SELECT count(*) FROM wb.project_metadata_result'),1)

    def test_schema_graph_no_008_empty_down_up_and_nonempty_reject(self):
        self.assertEqual(self.scalar('SELECT array_agg(version ORDER BY version) FROM public.wb_schema_migration'),[1,2,3,4,5,6,7,9])
        self.assertFalse(migrate_project_metadata(self.db.owner,self.executor))
        self.assertTrue(downgrade_project_metadata(self.db.owner))
        self.assertTrue(migrate_project_metadata(self.db.owner,self.executor))
        grant_project_metadata_runtime(self.db.owner,self.db.role)
        self.govern(); self.store.rename('alice',self.request())
        with self.assertRaises(infra.psycopg.Error):downgrade_project_metadata(self.db.owner)
        self.assertEqual(self.scalar('SELECT count(*) FROM wb.project_metadata_history'),1)

    def test_same_key_batch_first_commits_or_rolls_back_no_deadlock(self):
        self.govern()
        for commit in [True,False]:
            key='commit' if commit else 'rollback'
            with infra.psycopg.connect(**self.db.params,autocommit=True) as old, infra.psycopg.connect(**self.db.params,autocommit=True) as new:
                old.execute('BEGIN');old.execute("SELECT set_config('wb.principal','alice',true)")
                BusinessStore(old)._claim('P1','alice',key,['batch','B','2027-01-01'])
                with ThreadPoolExecutor(1) as pool:
                    future=pool.submit(ProjectMetadataStore(new).rename,'alice',self.request('new-'+key,key))
                    self.wait_blocked(new);self.assertFalse(future.done())
                    old.execute('COMMIT' if commit else 'ROLLBACK')
                    if commit:
                        with self.assertRaises(BusinessError) as caught:future.result(3)
                        self.assertEqual(caught.exception.code,'IDEMPOTENCY_CONFLICT')
                    else:self.assertEqual(future.result(3)['outcome'],'APPLIED')

    def test_same_key_metadata_first_batch_loses_and_timeout_recovery(self):
        self.govern();r=self.request(); db=self.db
        with infra.psycopg.connect(**db.params,autocommit=True) as first, infra.psycopg.connect(**db.params,autocommit=True) as second:
            first.execute('BEGIN');first.execute("SELECT set_config('wb.principal','alice',true)")
            first.execute('SELECT wb.rename_project_metadata(%s,%s,%s,%s,%s,%s,%s)',('P1','r1',r.expected_metadata_revision,r.expected_access_scope_revision,r.name,r.reason.encode(),r.canonical_bytes))
            second.execute("SET lock_timeout='100ms'")
            with self.assertRaises(infra.psycopg.Error):BusinessStore(second).create_batch('alice','P1','B','2027-01-01','r1')
            first.execute('COMMIT');second.execute('RESET lock_timeout')
            with self.assertRaises(BusinessError):BusinessStore(second).create_batch('alice','P1','B','2027-01-01','r1')
            self.assertEqual(ProjectMetadataStore(second).rename('alice',r)['outcome'],'APPLIED')
        self.assertEqual(self.scalar('SELECT count(*) FROM wb.release_batch'),0)

    def test_metadata_first_rollback_batch_wins_and_different_key_no_key_share_block(self):
        self.govern();r=self.request();db=self.db
        with infra.psycopg.connect(**db.params,autocommit=True) as first, infra.psycopg.connect(**db.params,autocommit=True) as second:
            first.execute('BEGIN');first.execute("SELECT set_config('wb.principal','alice',true)")
            first.execute('SELECT wb.rename_project_metadata(%s,%s,%s,%s,%s,%s,%s)',('P1','r1',r.expected_metadata_revision,r.expected_access_scope_revision,r.name,r.reason.encode(),r.canonical_bytes))
            second.execute("SET lock_timeout='500ms'")
            # Different K succeeds before first commits: FK KEY SHARE is truly
            # compatible, not merely eventual success after releasing the lock.
            BusinessStore(second).create_batch('alice','P1','other','2027-01-02','different')
            second.execute('RESET lock_timeout')
            with ThreadPoolExecutor(1) as pool:
                future=pool.submit(BusinessStore(second).create_batch,'alice','P1','B','2027-01-01','r1')
                self.wait_blocked(second);first.execute('ROLLBACK');future.result(3)
        self.assertEqual(self.scalar("SELECT name FROM wb.project WHERE project_id='P1'"),'first')
        self.assertEqual(self.scalar('SELECT count(*) FROM wb.project_metadata_result'),0)
        self.assertEqual(self.scalar('SELECT count(*) FROM wb.release_batch'),2)

    def test_concurrent_metadata_cas_one_winner(self):
        self.govern()
        def run(key):
            with infra.psycopg.connect(**self.db.params,autocommit=True) as connection:
                try:return ProjectMetadataStore(connection).rename('alice',self.request('name-'+key,key))['outcome']
                except BusinessError as error:return error.code
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(run,['a','b']))
        self.assertCountEqual(results,['APPLIED','REVISION_CONFLICT'])


    def test_asset_same_k_both_orders_actual_store_and_different_key(self):
        from tools.dsh_workbench.business_assets import AssetStore
        self.govern(); self.db.store.create_batch('alice','P1','B','2027-01-01','batch')
        payload={'request_id':'shared','expected_relation_revision':1,'kind':'milestone','title':'M',
                 'payload':{'due_date':'2027-01-01','description':'d','owner_display':'o'},'scope_level':'BATCH_WIDE'}
        # Claim-first actual AssetStore holds its transaction after a result is
        # formed, using a separate connection and an explicit outer test wrapper.
        with infra.psycopg.connect(**self.db.params,autocommit=True) as asset_conn, infra.psycopg.connect(**self.db.params,autocommit=True) as metadata_conn:
            asset_conn.execute('BEGIN');asset_conn.execute("SELECT set_config('wb.principal','alice',true)")
            asset=AssetStore(asset_conn,b'c'*32)
            # Same actual claim payload and actual subsequent batch row lock as
            # mutate; outer business _scope correctly refuses nested callers.
            asset._claim('P1','alice','shared',['asset','B',None,'create',payload])
            asset._batch('P1','B',True)
            with ThreadPoolExecutor(1) as pool:
                future=pool.submit(ProjectMetadataStore(metadata_conn).rename,'alice',self.request('new','shared'))
                self.wait_blocked(metadata_conn);self.assertFalse(future.done());asset_conn.execute('ROLLBACK')
                self.assertEqual(future.result(3)['outcome'],'APPLIED')
            with self.assertRaises(BusinessError):AssetStore(asset_conn,b'c'*32).mutate('alice','P1','B','create',payload)
            payload['request_id']='distinct'
            self.assertEqual(AssetStore(asset_conn,b'c'*32).mutate('alice','P1','B','create',payload)['record']['title'],'M')
        self.assertEqual(self.scalar('SELECT count(*) FROM wb.asset_root'),1)

    def test_actual_asset_store_claim_pause_commit_and_rollback(self):
        from tools.dsh_workbench.business_assets import AssetStore
        self.govern();self.db.store.create_batch('alice','P1','B','2027-01-01','batch')
        for rollback in [False,True]:
            key='asset-rollback' if rollback else 'asset-commit'
            reached=threading.Event();release=threading.Event()
            class PausedAsset(AssetStore):
                def _claim(inner,*args):
                    value=super(PausedAsset,inner)._claim(*args)
                    reached.set()
                    if not release.wait(3):raise RuntimeError('TEST_PAUSE_TIMEOUT')
                    return value
                def _audit(inner,*args):
                    if rollback:raise RuntimeError('TEST_ROLLBACK_ASSET')
                    return super(PausedAsset,inner)._audit(*args)
            payload={'request_id':key,'expected_relation_revision':1,'kind':'milestone','title':'M',
                     'payload':{'due_date':'2027-01-01','description':'d','owner_display':'o'},'scope_level':'BATCH_WIDE'}
            with infra.psycopg.connect(**self.db.params,autocommit=True) as ac, infra.psycopg.connect(**self.db.params,autocommit=True) as mc:
                with ThreadPoolExecutor(2) as pool:
                    asset=pool.submit(PausedAsset(ac,b'c'*32).mutate,'alice','P1','B','create',payload)
                    self.assertTrue(reached.wait(2))
                    rename=pool.submit(ProjectMetadataStore(mc).rename,'alice',self.request(key=key))
                    self.wait_blocked(mc);self.assertFalse(rename.done());release.set()
                    if rollback:
                        with self.assertRaisesRegex(RuntimeError,'TEST_ROLLBACK_ASSET'):asset.result(3)
                        self.assertEqual(rename.result(3)['outcome'],'APPLIED')
                    else:
                        self.assertEqual(asset.result(3)['record']['title'],'M')
                        with self.assertRaises(BusinessError) as caught:rename.result(3)
                        self.assertEqual(caught.exception.code,'IDEMPOTENCY_CONFLICT')
        self.assertEqual(self.scalar('SELECT count(*) FROM wb.asset_root'),1)
        self.assertEqual(self.scalar('SELECT count(*) FROM wb.project_metadata_history'),1)

    def test_concurrent_hidden_name_uniqueness_one_winner(self):
        self.govern()
        def run(target):
            actor='alice' if target=='P1' else 'bob'
            with infra.psycopg.connect(**self.db.params,autocommit=True) as connection:
                try:return ProjectMetadataStore(connection).rename(actor,self.request('same','unique',project=target))['outcome']
                except BusinessError as error:return error.code
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(run,['P1','P2']))
        self.assertCountEqual(results,['APPLIED','NAME_UNAVAILABLE'])
        self.assertEqual(self.scalar('SELECT count(*) FROM wb.project_metadata_history'),1)

    def test_acl_and_namespace_stop_commit_before_waiting_rename(self):
        self.govern()
        for target in ['namespace','acl']:
            with self.db.owner.transaction():
                if target=='namespace':self.db.owner.execute("UPDATE wb.project_namespace SET state='GOVERNANCE_HOLD'")
                else:self.db.owner.execute("DELETE FROM wb.project_acl WHERE principal='alice' AND project_id='P1'")
                with infra.psycopg.connect(**self.db.params,autocommit=True) as conn:
                    conn.execute("SET lock_timeout='100ms'")
                    self.error('METADATA_RETRY_REQUIRED',lambda:ProjectMetadataStore(conn).rename('alice',self.request(key=target)))
            if target=='namespace':
                self.error('GOVERNANCE_HOLD',lambda:self.store.rename('alice',self.request(key=target)))
                self.db.owner.execute("UPDATE wb.project_namespace SET state='NAMING_ACTIVE'")
            else:
                self.error('FORBIDDEN',lambda:self.store.rename('alice',self.request(key=target)))
        self.assertEqual(self.scalar('SELECT count(*) FROM wb.project_metadata_result'),0)

    def test_009_profile_v2_explicit_unqualified_not_learned(self):
        from tools.dsh_workbench.scope_source_policy_profile import ReadOnlyScopeSourcePolicyQualification
        value=ReadOnlyScopeSourcePolicyQualification(self.db.runtime).probe()
        self.assertEqual(value['status'],'UNQUALIFIED');self.assertFalse(value['admission_authorized'])
        self.assertEqual({r['code'] for r in value['reasons']},{'SOURCE_SCHEMA_OR_SELECT_POLICY_DRIFT','SOURCE_RI_TRIGGER_EXECUTION_PROFILE_DRIFT'})
        self.assertTrue(downgrade_project_metadata(self.db.owner))
        self.assertFalse(self.scalar("SELECT has_schema_privilege(%s,'wb','USAGE')",(self.executor,)))
        self.assertEqual(ReadOnlyScopeSourcePolicyQualification(self.db.runtime).probe()['status'],'MATCHED_AS_OF')

    def test_directory_aba_internal_revision_old_v1_wire_batch_unchanged(self):
        from tools.dsh_workbench.project_metadata_directory import MetadataDirectoryStore
        from tools.dsh_workbench.business_directory import DirectoryStore
        self.govern();self.db.owner.execute("INSERT INTO wb.project_acl VALUES('P2','alice',false)")
        self.db.store.create_batch('alice','P1','B','2027-01-01','b')
        directory=MetadataDirectoryStore(self.db.runtime,b'c'*32)
        before=directory.directory('alice',page_size=1)
        batch=directory.directory('alice','P1')
        old=DirectoryStore(self.db.runtime,b'c'*32).directory('alice',page_size=1)
        self.error('STALE_CURSOR',lambda:directory.directory('alice',page_size=1,page_cursor=old['next_page_cursor']))
        self.store.rename('alice',self.request('B','r1'))
        self.store.rename('alice',self.request('first','r2','2'))
        after=directory.directory('alice',page_size=1)
        self.assertEqual(before['records'],after['records'])
        self.assertNotEqual(before['directory_revision'],after['directory_revision'])
        self.error('STALE_CURSOR',lambda:directory.directory('alice',page_size=1,page_cursor=before['next_page_cursor']))
        self.assertEqual(batch,directory.directory('alice','P1'))
        self.assertEqual(set(after['records'][0]),{'project_id','name','access_scope_revision'})
        self.assertIs(type(after['records'][0]['access_scope_revision']),int)
        self.assertEqual(after['schema'],'dsh-workbench/business-directory/v1')

    def test_manifest_applied_hash_missing_dependency_and_old_down_fail_closed(self):
        from tools.dsh_workbench.business_migrations import downgrade, rollback
        for fn in [lambda:downgrade(self.db.owner,6),lambda:rollback(self.db.owner)]:
            with self.assertRaisesRegex(RuntimeError,'OPTIONAL_MIGRATION'):fn()
        self.db.owner.execute("UPDATE public.wb_schema_migration SET checksum='bad' WHERE version=7")
        with self.assertRaisesRegex(ValueError,'CHECKSUM_CONFLICT'):migrate_project_metadata(self.db.owner,self.executor)
        self.db.owner.execute('UPDATE public.wb_schema_migration SET checksum=%s WHERE version=7',(_manifest()[6]['up_sha256'],))
        self.assertTrue(downgrade_project_metadata(self.db.owner))
        self.db.owner.execute('DELETE FROM public.wb_schema_migration WHERE version=7')
        with self.assertRaisesRegex(ValueError,'DEPENDENCY_NOT_APPLIED'):migrate_project_metadata(self.db.owner,self.executor)

    def test_reader_get_no_edit_and_database_byte_canonical_boundaries(self):
        self.assertIs(self.store.get_metadata('alice','P1')['can_rename'],False)
        self.govern();self.assertEqual(self.store.get_metadata('reader','P1')['governance_state'],'GOVERNED_ROOT_ACTIVE')
        self.assertIs(self.store.get_metadata('reader','P1')['can_rename'],False)
        self.assertIs(self.store.get_metadata('alice','P1')['can_rename'],True)
        self.error('FORBIDDEN',lambda:self.store.rename('reader',self.request()))
        names=['😀'*128,'é','e\u0301','NBSP\u00a0']
        for index,name in enumerate(names):
            revision=str(index+1)
            self.store.rename('alice',self.request(name,'unicode-'+str(index),revision,reason='\x00'))
        self.assertEqual(self.scalar('SELECT count(*) FROM wb.project_metadata_history'),4)

    def test_key_and_change_history_integrity_administrative_bypass_rejected(self):
        self.govern()
        for sql in ["UPDATE wb.project_name_binding SET name_key='bad' WHERE project_id='P1'",
                    "UPDATE wb.project SET name='bad',metadata_revision=2 WHERE project_id='P1'"]:
            with self.assertRaises(infra.psycopg.Error):self.db.owner.execute(sql)
        self.assertEqual(self.scalar("SELECT name FROM wb.project WHERE project_id='P1'"),'first')


class MetadataManifestTests(unittest.TestCase):
    def test_pinned_files_and_graph_reject_unknown_cycle_missing_duplicate(self):
        self.assertEqual([r['version'] for r in _manifest()],[1,2,3,4,5,6,7,9])
        original=json.loads((pathlib.Path(__file__).resolve().parents[1]/'tools/dsh_workbench/migrations/optional/project_metadata_manifest.json').read_text())
        for change in ['cycle','missing','duplicate','unknown']:
            data=copy.deepcopy(original)
            if change=='cycle':data['migrations'][0]['dependencies']=[9]
            if change=='missing':data['migrations'][-1]['dependencies']=[8]
            if change=='duplicate':data['migrations'].append(data['migrations'][0])
            if change=='unknown':data['migrations'][-1]['dependencies']=[]
            with self.subTest(change=change),self.assertRaises(ValueError):_plan(data)

    def test_manifest_content_hash_is_pinned(self):
        with tempfile.TemporaryDirectory() as folder:
            path=pathlib.Path(folder)/'manifest.json';path.write_text('{}')
            with patch('tools.dsh_workbench.project_metadata_migrations.MANIFEST',path):
                with self.assertRaisesRegex(ValueError,'MANIFEST_CHECKSUM_CONFLICT'):_manifest()
