from __future__ import annotations

import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = WORKSPACE_ROOT / "ai-test" / "runtime"
sys.path.insert(0, str(RUNTIME_ROOT))

from aitest_runtime.canonical_runtime import create_canonical_runtime


class RuntimeSteadyStateInitConcurrencyTests(unittest.TestCase):
    def test_fresh_runtime_initializes_wal_and_extensions(self):
        with tempfile.TemporaryDirectory(prefix="aitest-runtime-init-") as td:
            db = Path(td) / "state" / "runtime-spine.db"
            runtime = create_canonical_runtime(WORKSPACE_ROOT, db_path=db)
            self.assertTrue(db.is_file())
            conn = sqlite3.connect(str(db))
            try:
                self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
                self.assertIsNotNone(conn.execute("SELECT 1 FROM schema_migrations WHERE version=1").fetchone())
                self.assertGreater(conn.execute("SELECT count(*) FROM extension_migrations").fetchone()[0], 0)
            finally:
                conn.close()
            self.assertEqual(runtime.get_head_seq("missing-mission"), 0)

    def test_steady_state_runtime_attach_is_read_only_while_writer_slot_is_owned(self):
        with tempfile.TemporaryDirectory(prefix="aitest-runtime-contention-") as td:
            db = Path(td) / "state" / "runtime-spine.db"
            first = create_canonical_runtime(WORKSPACE_ROOT, db_path=db)
            self.assertEqual(first.get_head_seq("missing-mission"), 0)

            writer = sqlite3.connect(str(db), timeout=0.1, isolation_level=None)
            try:
                writer.execute("PRAGMA busy_timeout=100")
                writer.execute("BEGIN IMMEDIATE")
                started = time.monotonic()
                second = create_canonical_runtime(WORKSPACE_ROOT, db_path=db)
                elapsed = time.monotonic() - started
                self.assertLess(
                    elapsed,
                    2.0,
                    f"steady-state RuntimeService construction waited for SQLite writer lock: {elapsed:.3f}s",
                )
                self.assertEqual(second.get_head_seq("missing-mission"), 0)
            finally:
                writer.rollback()
                writer.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
