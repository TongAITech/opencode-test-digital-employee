"""Cross-store recovery proof with real PostgreSQL and temporary POSIX R1 files."""

import json
import os
import unittest

from rc6_runtime.truth import TruthRuntime
import test_dsh_workbench_b_scope_versioned_gate_postgres as pg_fixture
import test_dsh_workbench_physical_ledger_writer as physical_fixture


@unittest.skipUnless(os.name == "posix" and pg_fixture.DSN and pg_fixture.psycopg,
                     "real PostgreSQL and POSIX flock are required")
class CrossStoreRecoveryPostgres(unittest.TestCase):
    def setUp(self):
        self.pg = pg_fixture.VersionedGatePostgres()
        self.addCleanup(self.pg.doCleanups)
        self.pg.setUp()
        self.physical = physical_fixture.PhysicalLedgerWriterTest()
        self.addCleanup(self.physical.doCleanups)
        self.physical.setUp()
        self.original = self.physical.row.read_bytes()

    def begin(self):
        writer = self.physical.owner(self.physical.path, 1)
        with self.pg.connection() as connection, connection.transaction():
            self.assertEqual(self.pg.acquire(connection), (1,))
        self.assertEqual(self.marker(), (1, "operation"))
        return writer

    def marker(self):
        return self.pg.owner.execute(
            "SELECT generation, operation FROM wb.test_admission_gate WHERE project_id='P1'"
        ).fetchone()

    def assert_fenced(self):
        self.assertEqual(self.physical.candidate(self.physical.path, 2), ["LOCK_BUSY"])
        with self.pg.owner.transaction():
            self.assertEqual(self.pg.revoke(self.pg.owner), "CONFLICT")
        self.assertEqual(self.marker(), (1, "operation"))

    def recover(self, generation):
        # The physical fixture owner holds the lock until this whole attempt ends.
        owner = self.physical.owner(self.physical.path, 2)
        try:
            snapshot = self.physical.path.read_bytes()
            if snapshot not in (b"", self.original):
                return "UNRESOLVED"
            if snapshot:
                ledger = TruthRuntime(self.physical.path)
                self.assertEqual(len(ledger.query("rc7_mission", mission_id="M1")), 1)
            if self.pg.reconcile_fixture(generation) is None:
                return "STALE"
            return "ORIGINAL_EVENT" if snapshot else "ABSENT"
        finally:
            self.physical.close_owner(owner)

    def test_owner_exit_before_append_then_absence_recovery(self):
        writer = self.begin()
        self.assert_fenced()
        writer.kill()
        self.assertNotEqual(writer.wait(timeout=10), 0)
        self.assertEqual(self.recover(0), "STALE")
        self.assertEqual(self.marker(), (1, "operation"))
        self.assertEqual(self.recover(1), "ABSENT")
        self.assertEqual(self.recover(1), "STALE")
        self.assertEqual(self.marker(), (2, None))
        self.assertEqual(self.physical.path.read_bytes(), b"")

    def test_owner_exit_after_fsync_before_reply_then_original_recovery(self):
        writer = self.begin()
        self.assert_fenced()
        command = {"epoch": 1, "row": self.original.hex(), "exit_after_sync": True}
        writer.stdin.write(json.dumps(command) + "\n")
        writer.stdin.flush()
        self.assertEqual(writer.wait(timeout=10), 79)
        self.assertEqual(writer.stdout.read(), "")
        self.assertEqual(self.marker(), (1, "operation"))
        self.assertEqual(self.recover(1), "ORIGINAL_EVENT")
        self.assertEqual(self.recover(1), "STALE")
        self.assertEqual(self.marker(), (2, None))
        self.assertEqual(self.physical.path.read_bytes(), self.original)

    def assert_unresolved(self, extra):
        writer = self.begin()
        self.assertEqual(self.physical.request(writer, 1), "SYNCED")
        self.physical.row.write_bytes(extra)
        self.assertEqual(self.physical.request(writer, 1), "SYNCED")
        writer.stdin.close()
        self.assertEqual(writer.wait(timeout=10), 0)
        self.assertEqual(self.recover(1), "UNRESOLVED")
        self.assertEqual(self.marker(), (1, "operation"))
        self.assertEqual(self.physical.path.read_bytes(), self.original + extra)

    def test_duplicate_source_does_not_clear_marker(self):
        self.assert_unresolved(self.original)

    def test_torn_source_does_not_clear_marker(self):
        self.assert_unresolved(b'{"event_id":')
