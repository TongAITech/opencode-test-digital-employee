"""Real PostgreSQL proof for a fixture-only explicit 008/009 graph."""

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

from test_dsh_workbench_b_scope_008_prepare_postgres import (
    SQL_DIR, infra, prepare_fixture, scope_fixture,
)
from tools.dsh_workbench.business_migrations import migrate
from tools.dsh_workbench.business_scope_preview import ReadOnlyScopeSnapshotPreview
from tools.dsh_workbench import project_metadata_migrations as metadata


BASE = frozenset(range(1, 8))
OPTIONAL = frozenset((8, 9))
SCOPE_CHECKSUMS = {
    "up": "84aefe3ed5480295b4951d6633d469c275921571155ff3f1734b8723c2c0a529",
    "down": "1ba17c824e4f1932e65dc4f4f77c5eb86d65696e9851488a49410b400d9ed374",
}
HISTORY = "wb.test_optional_graph_history"


def fixture_sources(scope_directory):
    metadata_plan = metadata._manifest()
    scope_sources = {}
    for direction, checksum in SCOPE_CHECKSUMS.items():
        source = (scope_directory / (direction + ".sql")).read_bytes()
        if sha256(source).hexdigest() != checksum:
            raise ValueError("FIXTURE_SOURCE_CHECKSUM_CONFLICT")
        scope_sources[direction] = source.decode("utf-8")
    metadata_node = metadata_plan[-1]
    metadata_sources = {}
    for direction in ("up", "down"):
        source = (metadata.ROOT / metadata_node[direction]).read_bytes()
        if sha256(source).hexdigest() != metadata_node[direction + "_sha256"]:
            raise ValueError("FIXTURE_SOURCE_CHECKSUM_CONFLICT")
        metadata_sources[direction] = source.decode("utf-8")
    base = {node["version"]: node["up_sha256"] for node in metadata_plan[:-1]}
    return base, {8: (SCOPE_CHECKSUMS["up"], scope_sources),
                  9: (metadata_node["up_sha256"], metadata_sources)}


def fixture_transition(connection, node, direction, executor, *, scope_directory=SQL_DIR):
    if type(node) is not int or node not in OPTIONAL or direction not in ("up", "down"):
        raise ValueError("FIXTURE_OPTIONAL_LEAF_REQUIRED")
    if not connection.autocommit or connection.info.transaction_status != infra.psycopg.pq.TransactionStatus.IDLE:
        raise ValueError("FIXTURE_IDLE_ADMIN_REQUIRED")
    base, sources = fixture_sources(scope_directory)
    with connection.transaction():
        connection.execute("SELECT pg_advisory_xact_lock(684091210)")
        if dict(connection.execute("SELECT version, checksum FROM public.wb_schema_migration")) != base:
            raise ValueError("FIXTURE_BASE_HISTORY_CONFLICT")
        applied = dict(connection.execute("SELECT version, checksum FROM " + HISTORY))
        if set(applied) - OPTIONAL or any(applied[v] != sources[v][0] for v in applied):
            raise ValueError("FIXTURE_OPTIONAL_HISTORY_CONFLICT")
        if (direction == "up") == (node in applied):
            return False
        checksum, sql = sources[node]
        if node == 9:
            quoted = metadata._executor(connection, executor)
            if direction == "down":
                owner = connection.execute("""
                    SELECT pg_get_userbyid(proowner) FROM pg_proc
                    WHERE oid='wb.rename_project_metadata(text,text,text,text,text,bytea,bytea)'::regprocedure
                """).fetchone()[0]
                if owner != executor:
                    raise ValueError("FIXTURE_EXECUTOR_CHANGED")
            sql = sql[direction].replace("__M1_EXECUTOR__", quoted)
        else:
            sql = sql[direction]
        connection.execute(sql)
        if direction == "up":
            connection.execute("INSERT INTO " + HISTORY + " VALUES (%s,%s)", (node, checksum))
        else:
            connection.execute("DELETE FROM " + HISTORY + " WHERE version=%s", (node,))
        return True


CATALOG = (
    """SELECT c.relname,c.relkind,c.relrowsecurity,c.relforcerowsecurity,
              pg_get_userbyid(c.relowner), c.relacl::text
         FROM pg_class c JOIN pg_namespace n ON c.relnamespace=n.oid
        WHERE n.nspname='wb' ORDER BY c.relname""",
    """SELECT c.relname,a.attname,format_type(a.atttypid,a.atttypmod),
              a.attnotnull,a.attidentity,a.attacl::text,co.collname,pg_get_expr(d.adbin,d.adrelid)
         FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
         JOIN pg_namespace n ON n.oid=c.relnamespace
         LEFT JOIN pg_collation co ON co.oid=a.attcollation
         LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum
        WHERE n.nspname='wb' AND a.attnum>0 AND NOT a.attisdropped
        ORDER BY c.relname,a.attnum""",
    """SELECT conname,pg_get_constraintdef(oid),condeferrable,condeferred FROM pg_constraint
        WHERE connamespace='wb'::regnamespace ORDER BY 1,2""",
    """SELECT c.relname,p.polname,p.polcmd,p.polpermissive,p.polroles::text,
              pg_get_expr(p.polqual,p.polrelid),pg_get_expr(p.polwithcheck,p.polrelid)
         FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid
        WHERE c.relnamespace='wb'::regnamespace ORDER BY 1,2""",
    """SELECT c.relname,t.tgname,pg_get_triggerdef(t.oid),t.tgenabled
         FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
        WHERE c.relnamespace='wb'::regnamespace AND NOT t.tgisinternal ORDER BY 1,2""",
    """SELECT p.proname,pg_get_function_identity_arguments(p.oid),
              pg_get_functiondef(p.oid),pg_get_userbyid(p.proowner),p.proacl::text
         FROM pg_proc p WHERE p.pronamespace='wb'::regnamespace ORDER BY 1,2""",
    """SELECT indexname,indexdef FROM pg_indexes WHERE schemaname='wb' ORDER BY indexname""",
    """SELECT c.relname,s.seqtypid::regtype::text,s.seqstart,s.seqincrement,
              s.seqmax,s.seqmin,s.seqcache,s.seqcycle
         FROM pg_sequence s JOIN pg_class c ON c.oid=s.seqrelid
        WHERE c.relnamespace='wb'::regnamespace ORDER BY 1""",
    """SELECT typname,format_type(typbasetype,typtypmod),typnotnull,typdefault
         FROM pg_type WHERE typnamespace='wb'::regnamespace AND typtype='d' ORDER BY 1""",
)


@unittest.skipUnless(infra.DSN and infra.psycopg, "real PostgreSQL required")
class OptionalGraphPostgres(unittest.TestCase):
    def setUp(self):
        self.db = scope_fixture.Scope()
        self.db.setUp()
        self.addCleanup(self.db.doCleanups)
        self.connection = self.db.owner
        migrate(self.connection, target=7)
        self.db.scope_seed()
        self.executor = self.db.role + "_graph"
        self.db.admin.execute(infra.sql.SQL("CREATE ROLE {} NOLOGIN NOINHERIT NOBYPASSRLS")
                              .format(infra.sql.Identifier(self.executor)))
        self.addCleanup(self.drop_executor)
        self.connection.execute("CREATE TABLE " + HISTORY + " (version integer PRIMARY KEY, checksum text NOT NULL)")

    def drop_executor(self):
        self.db.doCleanups()
        with infra.psycopg.connect(infra.DSN, autocommit=True) as admin:
            admin.execute(infra.sql.SQL("DROP ROLE {}").format(infra.sql.Identifier(self.executor)))

    def transition(self, node, direction, **kwargs):
        return fixture_transition(self.connection, node, direction, self.executor, **kwargs)

    def catalog(self):
        return tuple(tuple(self.connection.execute(query)) for query in CATALOG)

    def leaves(self):
        return [row[0] for row in self.connection.execute("SELECT version FROM " + HISTORY + " ORDER BY version")]

    def test_both_orders_match_catalog_and_explicit_empty_leaf_down(self):
        for node in (8, 9):
            self.assertTrue(self.transition(node, "up"))
            self.assertFalse(self.transition(node, "up"))
        first = self.catalog()
        self.assertEqual(self.leaves(), [8, 9])
        self.assertEqual([row[0] for row in self.connection.execute(
            "SELECT version FROM public.wb_schema_migration ORDER BY version")], list(range(1, 8)))
        self.assertFalse(migrate(self.connection, target=7))
        self.assertFalse(metadata.downgrade_project_metadata(self.connection))
        self.assertEqual(self.connection.execute(
            "SELECT has_table_privilege(%s,'wb.mission_create_intent','INSERT')", (self.db.role,)
        ).fetchone(), (False,))
        with self.assertRaisesRegex(ValueError, "OPTIONAL_LEAF_REQUIRED"):
            self.transition(7, "down")
        self.assertTrue(self.transition(8, "down"))
        self.assertIsNotNone(self.connection.execute("SELECT to_regclass('wb.project_namespace')").fetchone()[0])
        self.assertIsNone(self.connection.execute("SELECT to_regclass('wb.scope_snapshot')").fetchone()[0])
        self.assertTrue(self.transition(9, "down"))
        self.assertEqual(self.leaves(), [])
        for node in (9, 8):
            self.assertTrue(self.transition(node, "up"))
        self.assertEqual(self.catalog(), first)
        self.assertTrue(self.transition(9, "down"))
        self.assertEqual(self.leaves(), [8])
        self.assertFalse(self.transition(9, "down"))
        self.assertIsNotNone(self.connection.execute("SELECT to_regclass('wb.scope_snapshot')").fetchone()[0])

    def test_checksum_mismatch_and_unknown_applied_fail_before_ddl(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "up.sql").write_bytes((SQL_DIR / "up.sql").read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "SOURCE_CHECKSUM_CONFLICT"):
                self.transition(8, "up", scope_directory=directory)
        self.connection.execute("INSERT INTO " + HISTORY + " VALUES (8,'wrong')")
        with self.assertRaisesRegex(ValueError, "OPTIONAL_HISTORY_CONFLICT"):
            self.transition(9, "up")
        self.connection.execute("UPDATE " + HISTORY + " SET version=10")
        with self.assertRaisesRegex(ValueError, "OPTIONAL_HISTORY_CONFLICT"):
            self.transition(9, "up")
        self.connection.execute("DELETE FROM " + HISTORY)
        self.connection.execute("UPDATE public.wb_schema_migration SET checksum='wrong' WHERE version=7")
        with self.assertRaisesRegex(ValueError, "BASE_HISTORY_CONFLICT"):
            self.transition(8, "up")
        self.assertEqual(self.leaves(), [])
        self.assertEqual(self.connection.execute(
            "SELECT to_regclass('wb.scope_snapshot'), to_regclass('wb.project_namespace')").fetchone(),
            (None, None))

    def test_nonempty_008_rolls_back_down_and_retains_other_leaf(self):
        for node in (8, 9):
            self.transition(node, "up")
        snapshot = ReadOnlyScopeSnapshotPreview(self.db.runtime).preview("alice", "P1", "B1")["snapshot"]
        prepare_fixture(self.connection, ("authority", "alice", "P1", "key"), snapshot,
                        ("mapping", "release", "runtime-batch", "mission", "binding", "operation"))
        before = self.catalog()
        with self.assertRaises(infra.psycopg.Error) as failure:
            self.transition(8, "down")
        self.assertEqual(failure.exception.sqlstate, "55000")
        self.assertEqual(self.leaves(), [8, 9])
        self.assertEqual(self.catalog(), before)
        self.assertEqual(self.connection.execute("SELECT count(*) FROM wb.mission_create_intent").fetchone(), (1,))

    def test_nonempty_009_rolls_back_down_and_retains_other_leaf(self):
        for node in (9, 8):
            self.transition(node, "up")
        self.connection.execute("""
            INSERT INTO wb.project_namespace
            VALUES ('NS','GOVERNANCE_HOLD','project-name/utf8-exact-v1','admin:fixture','1',%s,1,true)
        """, ("a" * 64,))
        before = self.catalog()
        with self.assertRaisesRegex(infra.psycopg.Error, "ROLLBACK_REQUIRES_BACKUP_AND_RECONCILIATION"):
            self.transition(9, "down")
        self.assertEqual(self.leaves(), [8, 9])
        self.assertEqual(self.catalog(), before)
        self.assertEqual(self.connection.execute("SELECT count(*) FROM wb.project_namespace").fetchone(), (1,))

    def test_graph_honors_the_existing_migration_advisory_lock(self):
        parameters = dict(infra.psycopg.conninfo.conninfo_to_dict(infra.DSN), dbname=self.db.name)
        with infra.psycopg.connect(**parameters, autocommit=True) as waiter:
            pid = waiter.info.backend_pid

            def attempt():
                waiter.execute("SET statement_timeout='6s'")
                return fixture_transition(waiter, 8, "up", self.executor)

            with ThreadPoolExecutor(max_workers=1) as worker:
                with self.connection.transaction():
                    self.connection.execute("SELECT pg_advisory_xact_lock(684091210)")
                    pending = worker.submit(attempt)
                    deadline = time.monotonic() + 4
                    while time.monotonic() < deadline:
                        waiting = self.connection.execute(
                            "SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=%s AND locktype='advisory' AND NOT granted)",
                            (pid,),
                        ).fetchone()[0]
                        if waiting:
                            break
                        time.sleep(0.01)
                    else:
                        self.fail("the graph did not wait on the migration lock")
                    self.assertEqual(self.leaves(), [])
                self.assertTrue(pending.result(timeout=7))
        self.assertEqual(self.leaves(), [8])
