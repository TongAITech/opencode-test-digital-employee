"""Isolated versioned admission gate proof using the actual B06 PostgreSQL schema."""

from concurrent.futures import ThreadPoolExecutor
import time
import unittest

from test_dsh_workbench_b_postgres import DSN, psycopg
import test_dsh_workbench_b_scope_postgres as scope_fixture


@unittest.skipUnless(DSN and psycopg, "real PostgreSQL DSN and psycopg required")
class VersionedGatePostgres(unittest.TestCase):
    def setUp(self):
        self.db = scope_fixture.Scope()
        self.addCleanup(self.db.doCleanups)
        self.db.setUp()
        self.db.scope_seed()
        self.owner = self.db.owner
        self.owner.execute("""
            CREATE TABLE wb.test_admission_gate (
                project_id text PRIMARY KEY REFERENCES wb.project(project_id),
                generation bigint NOT NULL DEFAULT 0,
                operation text
            )
        """)
        self.owner.execute("INSERT INTO wb.test_admission_gate(project_id) SELECT project_id FROM wb.project")
        self.params = dict(psycopg.conninfo.conninfo_to_dict(DSN), dbname=self.db.name)

    def connection(self):
        return psycopg.connect(**self.params, autocommit=True)

    def acquire(self, connection):
        return connection.execute("""
            UPDATE wb.test_admission_gate SET generation=generation+1, operation='operation'
            WHERE project_id='P1' AND operation IS NULL RETURNING generation
        """).fetchone()

    def reconcile_fixture(self, generation):
        return self.owner.execute("""
            UPDATE wb.test_admission_gate SET generation=generation+1, operation=NULL
            WHERE project_id='P1' AND operation='operation' AND generation=%s RETURNING generation
        """, (generation,)).fetchone()

    @staticmethod
    def participate(connection, project):
        # A guarded UPDATE both observes and advances the same visible row version.
        return connection.execute("""
            UPDATE wb.test_admission_gate SET generation=generation+1
            WHERE project_id=%s AND operation IS NULL RETURNING generation
        """, (project,)).fetchone()

    def revoke(self, connection, project="P1", principal="alice"):
        if not self.participate(connection, project):
            return "CONFLICT"
        connection.execute("DELETE FROM wb.project_acl WHERE project_id=%s AND principal=%s",
                           (project, principal))
        return "COMMITTED"

    def wait_for_lock(self, pid):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            row = self.owner.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s",
                                     (pid,)).fetchone()
            if row == ("Lock",):
                return
            time.sleep(0.01)
        self.fail("source mutation did not wait on the serialization row")

    def test_committed_marker_fences_read_committed_and_repeatable_read_waiters(self):
        with self.connection() as admission, self.connection() as stale, self.connection() as fresh:
            stale.execute("BEGIN ISOLATION LEVEL REPEATABLE READ")
            self.assertEqual(stale.execute(
                "SELECT operation FROM wb.test_admission_gate WHERE project_id='P1'").fetchone(), (None,))
            admission.execute("BEGIN")
            self.assertEqual(self.acquire(admission), (1,))

            def attempt(connection):
                connection.execute("SET LOCAL statement_timeout = '5s'")
                return self.revoke(connection)

            fresh.execute("BEGIN")
            with ThreadPoolExecutor(max_workers=2) as pool:
                old_result = pool.submit(attempt, stale)
                fresh_result = pool.submit(attempt, fresh)
                try:
                    self.wait_for_lock(stale.info.backend_pid)
                    self.wait_for_lock(fresh.info.backend_pid)
                finally:
                    admission.execute("COMMIT")
                with self.assertRaises(psycopg.errors.SerializationFailure):
                    old_result.result(timeout=6)
                self.assertEqual(fresh_result.result(timeout=6), "CONFLICT")
            stale.execute("ROLLBACK")
            fresh.execute("COMMIT")

        self.assertTrue(self.db.scope.scope("alice", "P1", "B1")["records"])
        self.assertIsNone(self.reconcile_fixture(0))
        self.assertEqual(self.reconcile_fixture(1), (2,))
        with self.owner.transaction():
            self.assertEqual(self.revoke(self.owner), "COMMITTED")
        self.db.error(403, lambda: self.db.scope.scope("alice", "P1", "B1"))

    def test_killed_acquirer_keeps_marker_and_guards_date_and_relation_audit(self):
        with self.connection() as admission:
            with admission.transaction():
                self.assertEqual(self.acquire(admission), (1,))
            pid = admission.info.backend_pid
            self.assertEqual(self.owner.execute("SELECT pg_terminate_backend(%s)", (pid,)).fetchone(), (True,))
            with self.assertRaises(psycopg.OperationalError):
                admission.execute("SELECT 1")
        self.db.relations.create_requirement("alice", "P1", "R3", "src", "prod",
                                             "r3", "r1", "source:r3", "create-r3")
        date_args = ("alice", "P1", "B1", "2026-11-13", 1, "move", "reason", "fixture-date")
        self.owner.execute(
            psycopg.sql.SQL("GRANT SELECT, UPDATE ON wb.test_admission_gate TO {}")
            .format(psycopg.sql.Identifier(self.db.role))
        )
        # BusinessStore owns its transaction. A fixture-only trigger enforces the
        # row operation inside that transaction, including history and audit.
        self.owner.execute("""
            CREATE FUNCTION wb.test_batch_gate() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                UPDATE wb.test_admission_gate SET generation=generation+1
                WHERE project_id=NEW.project_id AND operation IS NULL;
                IF NOT FOUND THEN RAISE EXCEPTION 'TEST_ADMISSION_CONFLICT' USING ERRCODE='55000'; END IF;
                RETURN NEW;
            END;
            $$;
            CREATE TRIGGER test_batch_gate BEFORE UPDATE OF release_date, relation_revision ON wb.release_batch
            FOR EACH ROW EXECUTE FUNCTION wb.test_batch_gate()
        """)
        before = self.owner.execute(
            "SELECT release_date,revision,relation_revision FROM wb.release_batch WHERE project_id='P1'"
        ).fetchone()
        audit_count = self.owner.execute("SELECT count(*) FROM wb.audit").fetchone()
        relation_args = ("alice", "P1", "B1", "requirement", "R3", before[2], "attach-r3")
        with self.assertRaisesRegex(psycopg.Error, "TEST_ADMISSION_CONFLICT"):
            self.db.store.reschedule(*date_args)
        with self.assertRaisesRegex(psycopg.Error, "TEST_ADMISSION_CONFLICT"):
            self.db.relations.attach_member(*relation_args)
        self.assertEqual(self.owner.execute(
            "SELECT count(*) FROM wb.batch_requirement WHERE requirement_id='R3'"
        ).fetchone(), (0,))
        self.assertEqual(self.owner.execute(
            "SELECT release_date,revision,relation_revision FROM wb.release_batch WHERE project_id='P1'"
        ).fetchone(), before)
        self.assertEqual(self.owner.execute("SELECT count(*) FROM wb.audit").fetchone(), audit_count)
        self.assertEqual(self.owner.execute("SELECT count(*) FROM wb.batch_date_history").fetchone(), (0,))
        self.assertEqual(self.owner.execute(
            "SELECT generation, operation FROM wb.test_admission_gate WHERE project_id='P1'"
        ).fetchone(), (1, "operation"))
        with self.owner.transaction():
            self.assertEqual(self.revoke(self.owner, "P2", "bob"), "COMMITTED")
        self.assertEqual(self.reconcile_fixture(1), (2,))
        self.assertEqual(self.db.relations.attach_member(*relation_args), before[2] + 1)
        self.assertEqual(self.db.store.reschedule(*date_args), 2)
        self.assertEqual(self.owner.execute("SELECT count(*) FROM wb.batch_date_history").fetchone(), (1,))

    def test_revocation_commits_first_and_is_visible_before_marker(self):
        with self.owner.transaction():
            self.assertEqual(self.revoke(self.owner), "COMMITTED")
        with self.connection() as admission, admission.transaction():
            self.assertEqual(self.acquire(admission), (2,))
            # The gate ordering exposes committed source state. The test
            # acquirer deliberately does not implement authorization.
            self.assertIsNone(admission.execute("""
                SELECT 1 FROM wb.project_acl WHERE project_id='P1' AND principal='alice'
            """).fetchone())
        self.db.error(403, lambda: self.db.scope.scope("alice", "P1", "B1"))
