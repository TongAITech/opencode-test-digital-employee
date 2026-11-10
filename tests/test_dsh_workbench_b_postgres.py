"""Real PostgreSQL only. Set WB_PG_TEST_DSN to disposable admin database.

Each test owns a unique database and login role. Never uses SQLite.
"""
import os
import pathlib
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor

try:
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict
except ImportError:
    psycopg = None
from tools.dsh_workbench.business_store import BusinessStore, BusinessError, provision_project
from tools.dsh_workbench.business_migrations import migrate, rollback

DSN = os.environ.get('WB_PG_TEST_DSN')
MIGRATION = pathlib.Path(__file__).resolve().parents[1]/'tools/dsh_workbench/migrations'

@unittest.skipUnless(DSN and psycopg, 'real PostgreSQL DSN and psycopg required')
class PostgresIdentity(unittest.TestCase):
    def setUp(self):
        self.admin = psycopg.connect(DSN,autocommit=True)
        self.name = 'wb_test_'+uuid.uuid4().hex[:16]
        self.role = self.name+'_runtime'
        self.password=uuid.uuid4().hex
        self.admin.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD {}').format(sql.Identifier(self.role),sql.Literal(self.password)))
        self.admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(self.name)))
        params = dict(conninfo_to_dict(DSN),dbname=self.name)
        self.owner = psycopg.connect(**params,autocommit=True)
        migrate(self.owner)
        self.owner.execute("INSERT INTO wb.project VALUES('P1','first'),('P2','second')")
        self.owner.execute("INSERT INTO wb.project_acl VALUES('P1','alice',true),('P1','reader',false),('P2','bob',true)")
        role = sql.Identifier(self.role)
        self.owner.execute(sql.SQL('GRANT USAGE ON SCHEMA wb TO {}').format(role))
        self.owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION wb.allowed(text,boolean) TO {}').format(role))
        self.owner.execute(sql.SQL('GRANT SELECT ON ALL TABLES IN SCHEMA wb TO {}').format(role))
        self.owner.execute(sql.SQL('REVOKE SELECT ON wb.project_acl FROM {}').format(role))
        self.owner.execute(sql.SQL('GRANT INSERT ON wb.release_batch,wb.system_identity,wb.system_version,wb.audit,wb.batch_date_history,wb.request_log TO {}').format(role))
        self.owner.execute(sql.SQL('GRANT UPDATE ON wb.release_batch TO {}').format(role))
        self.owner.execute(sql.SQL('GRANT USAGE ON ALL SEQUENCES IN SCHEMA wb TO {}').format(role))
        self.params = dict(params,user=self.role,password=self.password)
        self.runtime = psycopg.connect(**self.params,autocommit=True)
        self.store = BusinessStore(self.runtime)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.runtime.close(); self.owner.close()
        self.admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(self.name)))
        self.admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(self.role)))
        self.admin.close()

    def error(self,status,fn):
        with self.assertRaises(BusinessError) as caught: fn()
        self.assertEqual(caught.exception.status,status)

    def batch(self,b='B1',date='2026-11-12',request='c1'):
        self.store.create_batch('alice','P1',b,date,request)

    def test_date_unique_cross_project_leap_and_invalid_dates(self):
        self.batch(); self.error(409,lambda:self.batch('B2',request='c2'))
        self.store.create_batch('bob','P2','B2','2026-11-12','b2')
        self.batch('leap','2028-02-29','leap')
        for date in ['2026-02-29','2026-11-12T00:00:00Z','infinity','2026-1-01']:
            self.error(400,lambda:self.batch('bad',date,'bad'))

    def test_reschedule_history_idempotency_and_conflicts(self):
        self.batch(); self.batch('B2','2026-11-19','c2')
        args=('alice','P1','B1','2026-11-13',1,'move','reason','CHG-1')
        self.assertEqual(self.store.reschedule(*args),2)
        self.assertEqual(self.store.reschedule(*args),2)
        self.error(409,lambda:self.store.reschedule('alice','P1','B1','2026-11-14',2,'move','reason','CHG-1'))
        self.error(409,lambda:self.store.reschedule('alice','P1','B1','2026-11-19',2,'conflict','reason','CHG-1'))
        self.error(409,lambda:self.store.reschedule('alice','P1','B1','2026-11-14',1,'stale','reason','CHG-1'))
        self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.batch_date_history').fetchone()[0],1)
        self.assertEqual(str(self.store.batches('alice','P1')[0][1]),'2026-11-13')

    def test_audit_failure_rolls_back_all_and_retry_recovers(self):
        self.batch()
        self.owner.execute("CREATE FUNCTION wb.fail_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected'; END $$")
        self.owner.execute('CREATE TRIGGER fail BEFORE INSERT ON wb.audit FOR EACH ROW EXECUTE FUNCTION wb.fail_audit()')
        with self.assertRaises(psycopg.Error): self.store.reschedule('alice','P1','B1','2026-11-13',1,'move','reason','CHG')
        self.assertEqual(self.owner.execute('SELECT revision FROM wb.release_batch').fetchone()[0],1)
        self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.batch_date_history').fetchone()[0],0)
        self.owner.execute('DROP TRIGGER fail ON wb.audit')
        self.assertEqual(self.store.reschedule('alice','P1','B1','2026-11-13',1,'move','reason','CHG'),2)

    def test_acl_pool_reset_revoke_and_direct_sql_no_scope(self):
        self.batch()
        self.assertEqual(self.runtime.execute("SELECT current_setting('wb.principal',true)").fetchone()[0],'')
        self.assertEqual(self.runtime.execute('SELECT count(*) FROM wb.release_batch').fetchone()[0],0)
        self.error(403,lambda:self.store.batches('bob','P1'))
        self.error(403,lambda:self.store.create_batch('reader','P1','B2','2026-11-14','read'))
        self.owner.execute("DELETE FROM wb.project_acl WHERE principal='alice'")
        self.error(403,lambda:self.store.batches('alice','P1'))
        with self.assertRaises(psycopg.Error): self.runtime.execute('CREATE TABLE wb.unauthorized(id int)')
        with self.assertRaises(psycopg.Error): self.runtime.execute('UPDATE wb.audit SET actor=\'bob\'')

    def test_versions_shared_label_namespace_and_cross_project_fk(self):
        for system,namespace,obj in [('S1','prod','raw'),('S2','uat','raw')]:
            self.store.create_system('alice','P1',system,'source',namespace,obj,'r1','sys'+system)
            self.store.create_version('alice','P1','V'+system,system,'same','source',namespace,'vraw','r1','ver'+system)
        self.error(409,lambda:self.store.create_system('alice','P1','S3','source','prod','raw','r2','dupe'))
        self.error(422,lambda:self.store.create_version('bob','P2','V','S1','same','source','prod','v','r1','cross'))
        self.error(422,lambda:self.store.create_system('alice','P1','blank','source',' ','obj','r1','blank'))
        self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.system_version').fetchone()[0],2)

    def test_concurrent_cas_one_winner_and_connection_recovery(self):
        self.batch()
        def move(index):
            with psycopg.connect(**self.params,autocommit=True) as conn:
                try: return BusinessStore(conn).reschedule('alice','P1','B1','2026-11-1'+str(index),1,'m'+str(index),'reason','CHG')
                except BusinessError as error: return error.status
        with ThreadPoolExecutor(2) as pool: results=list(pool.map(move,[3,4]))
        self.assertEqual(sorted(results),[2,409])
        self.runtime.close()
        self.runtime=psycopg.connect(**self.params,autocommit=True)
        self.assertEqual(BusinessStore(self.runtime).batches('alice','P1')[0][2],2)

    def test_history_append_only_and_migration_rollback(self):
        self.batch(); self.store.reschedule('alice','P1','B1','2026-11-13',1,'m','reason','CHG')
        for table in ['audit','batch_date_history']:
            with self.assertRaises(psycopg.Error): self.owner.execute('DELETE FROM wb.'+table)
        # Disposable test DB rollback only; no accepted production data is dropped.
        with self.assertRaisesRegex(RuntimeError,'ROLLBACK_REQUIRES_BACKUP'):
            rollback(self.owner)
        self.owner.execute((MIGRATION/'001_identity.down.sql').read_text())
        self.owner.execute('DELETE FROM public.wb_schema_migration')
        self.assertIsNone(self.owner.execute("SELECT to_regnamespace('wb')").fetchone()[0])
        self.assertTrue(migrate(self.owner))
        self.assertFalse(migrate(self.owner))
        rollback(self.owner)
        self.assertTrue(migrate(self.owner))
        self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.release_batch').fetchone()[0],0)

    def test_migration_checksum_conflict_is_fail_closed(self):
        self.owner.execute("UPDATE public.wb_schema_migration SET checksum='tampered'")
        with self.assertRaisesRegex(RuntimeError,'MIGRATION_CHECKSUM_CONFLICT'):
            migrate(self.owner)
        self.assertIsNotNone(self.owner.execute("SELECT to_regnamespace('wb')").fetchone()[0])

    def test_backend_loss_rolls_back_uncommitted_write(self):
        self.runtime.execute('BEGIN')
        self.runtime.execute("SELECT set_config('wb.principal','alice',true)")
        self.runtime.execute("INSERT INTO wb.release_batch VALUES('P1','interrupted','2026-11-12',1)")
        self.owner.execute('SELECT pg_terminate_backend(%s)',(self.runtime.info.backend_pid,))
        self.runtime.close()
        self.runtime=psycopg.connect(**self.params,autocommit=True)
        self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.release_batch').fetchone()[0],0)
        BusinessStore(self.runtime).create_batch('alice','P1','recovered','2026-11-12','recover')
        self.assertEqual(self.owner.execute('SELECT count(*) FROM wb.release_batch').fetchone()[0],1)

    def test_runtime_cannot_change_date_without_matching_history(self):
        self.batch()
        with self.assertRaises(psycopg.Error):
            with self.runtime.transaction():
                self.runtime.execute("SELECT set_config('wb.principal','alice',true)")
                self.runtime.execute("UPDATE wb.release_batch SET release_date='2026-11-13',revision=2")
        self.assertEqual(self.owner.execute('SELECT revision FROM wb.release_batch').fetchone()[0],1)

    def test_project_provision_is_atomic_and_runtime_cannot_provision(self):
        provision_project(self.owner,'P3','third','carol','project-create')
        self.assertEqual(self.store.batches('carol','P3'),[])
        self.assertEqual(self.owner.execute("SELECT count(*) FROM wb.audit WHERE project_id='P3'").fetchone()[0],1)
        with self.assertRaises(psycopg.Error):
            provision_project(self.runtime,'P4','fourth','dave','forged')
        self.assertEqual(self.owner.execute("SELECT count(*) FROM wb.project WHERE project_id='P4'").fetchone()[0],0)
        self.assertEqual(self.store.batches('reader','P1'),[])

    def test_outer_transaction_context_and_unavailable_connection_rejected(self):
        with psycopg.connect(**self.params) as nested:
            with self.assertRaisesRegex(ValueError,'AUTOCOMMIT_CONNECTION_REQUIRED'):
                BusinessStore(nested)
        self.runtime.close()
        self.error(503,lambda:self.store.batches('alice','P1'))

    def test_explicit_begin_on_autocommit_connection_is_rejected_without_context_leak(self):
        self.batch()
        self.runtime.execute('BEGIN')
        with self.assertRaisesRegex(ValueError,'IDLE_CONNECTION_REQUIRED'):
            self.store.batches('alice','P1')
        self.assertEqual(self.runtime.execute("SELECT current_setting('wb.principal',true)").fetchone()[0],'')
        self.assertEqual(self.runtime.execute('SELECT count(*) FROM wb.release_batch').fetchone()[0],0)
        self.runtime.execute('ROLLBACK')
        self.assertEqual(len(self.store.batches('alice','P1')),1)
