"""Explicit test-only 008 candidate on a disposable genuine PostgreSQL database."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import random
import threading
import time
import unittest

import test_dsh_workbench_b_scope_postgres as scope_fixture
from tools.dsh_workbench.business_migrations import migrate
from tools.dsh_workbench.business_scope_preview import ReadOnlyScopeSnapshotPreview
from tools.dsh_workbench.project_metadata_migrations import migrate_project_metadata
from tools.dsh_workbench.scope_snapshot_codec import canonical_scope_bytes, scope_digest

infra = scope_fixture.prior.prior
SQL_DIR = Path(__file__).parent / "fixtures" / "workbench_scope_008"
TABLES = ("scope_snapshot", "mission_create_intent", "mission_create_journal", "mission_create_receipt")
KEY_COLUMNS = "formal_authority_ref, actor_ref, project_id, creation_key"
KEY_MATCH = "(formal_authority_ref, actor_ref, project_id, creation_key) = (%s, %s, %s, %s)"
POLICY = "ALLOCATE_NEW_RELEASE_V1"


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def apply_candidate(connection, direction):
    with connection.transaction():
        connection.execute("SELECT pg_advisory_xact_lock(684091210)")
        connection.execute((SQL_DIR / (direction + ".sql")).read_text())


def prepare_fixture(connection, key, snapshot, reservation, context="original", *, fail_before_journal=False):
    """Exercise PG atomicity with preselected test inputs, without any allocator."""
    if not connection.autocommit or connection.info.transaction_status != infra.psycopg.pq.TransactionStatus.IDLE:
        raise ValueError("SCOPE_008_IDLE_CONNECTION_REQUIRED")
    authority, actor, project, creation_key = key
    batch = snapshot["batch_id"]
    if project != snapshot["project_id"]:
        raise ValueError("SCOPE_008_PROJECT_MISMATCH")
    selection = json_bytes(dict(schema_version=1, formal_authority_ref=authority, actor_ref=actor,
                                project_id=project, creation_key=creation_key, batch_id=batch,
                                filters=snapshot["filters"], mapping_policy=POLICY))
    selection_digest = sha256(b"dsh.mission-prepare-selection.v1\n" + selection).hexdigest()
    canonical = canonical_scope_bytes(snapshot)
    digest = scope_digest(snapshot)
    mapping, release, runtime_batch, mission, binding, operation = reservation
    # This digest has only a test domain. It cannot identify a formal creation request.
    request = json_bytes(["PG_FIXTURE_ONLY", selection_digest, digest, *reservation])
    with connection.transaction():
        connection.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED READ WRITE")
        connection.execute("SET LOCAL synchronous_commit = on")
        connection.execute("SELECT set_config('wb.principal', %s, true)", (actor,))
        if not connection.execute("SELECT wb.allowed(%s, true)", (project,)).fetchone()[0]:
            raise PermissionError("SCOPE_008_FORBIDDEN")
        connection.execute("SELECT pg_advisory_xact_lock(8008, hashtext(%s))", (json_bytes(key).decode(),))
        existing = connection.execute(
            "SELECT selection_bytes, selection_digest, original_context_ref, runtime_release_batch_id "
            "FROM wb.mission_create_intent WHERE " + KEY_MATCH, key
        ).fetchone()
        if existing:
            if existing[:3] != (selection, selection_digest, context):
                raise ValueError("SCOPE_008_SELECTION_CONFLICT")
            return existing[3]
        connection.execute(
            """INSERT INTO wb.scope_snapshot
               (project_id,batch_id,snapshot_ref,schema_version,canonical_bytes,scope_digest,
                release_date,date_revision,relation_revision,access_scope_revision,edge_count)
               VALUES (%s,%s,%s,1,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (project_id,batch_id,scope_digest) DO NOTHING""",
            (project, batch, digest, canonical, digest, snapshot["release_date"], snapshot["date_revision"],
             snapshot["relation_revision"], snapshot["access_scope_revision"], len(snapshot["edges"])),
        )
        stored = connection.execute(
            """SELECT snapshot_ref,canonical_bytes,release_date::text,date_revision,relation_revision,
                      access_scope_revision,edge_count FROM wb.scope_snapshot
               WHERE (project_id,batch_id,scope_digest)=(%s,%s,%s)""", (project,batch,digest)
        ).fetchone()
        if stored != (digest,canonical,snapshot["release_date"],snapshot["date_revision"],snapshot["relation_revision"],
                      snapshot["access_scope_revision"],len(snapshot["edges"])):
            raise ValueError("SCOPE_008_SNAPSHOT_CONFLICT")
        connection.execute(
            """INSERT INTO wb.mission_create_intent
               (formal_authority_ref,actor_ref,project_id,creation_key,batch_id,snapshot_ref,scope_digest,
                selection_bytes,selection_digest,request_schema_version,request_bytes,request_digest,
                original_context_ref,mapping_schema_version,mapping_policy,mapping_ref,runtime_release_id,
                runtime_release_batch_id,mission_id,binding_ref,creation_operation_ref)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s,%s,1,%s,%s,%s,%s,%s,%s,%s)""",
            (*key,batch,digest,digest,selection,selection_digest,request,sha256(request).hexdigest(),
             context,POLICY,mapping,release,runtime_batch,mission,binding,operation),
        )
        if not fail_before_journal:
            connection.execute(
                """INSERT INTO wb.mission_create_journal
                   (formal_authority_ref,actor_ref,project_id,creation_key,journal_event_ref,phase,observed_result)
                   VALUES (%s,%s,%s,%s,'prepare','PREPARE','PERSISTED')""", key
            )
        return runtime_batch


@unittest.skipUnless(infra.DSN and infra.psycopg, "real PostgreSQL required")
class Scope008Prepare(unittest.TestCase):
    def setUp(self):
        self.db = scope_fixture.Scope(methodName="test_scope_pages_real_join_unsplit_sources_and_bound_cursors")
        self.db.setUp()
        self.addCleanup(self.db.doCleanups)
        migrate(self.db.owner, target=7)
        self.db.scope_seed()
        self.snapshot = ReadOnlyScopeSnapshotPreview(self.db.runtime).preview("alice", "P1", "B1")["snapshot"]
        self.key = ("fixture-authority", "alice", "P1", "K1")
        self.reservation = self.refs("1")
        self.prepare_role = self.db.role + "_008"
        role = infra.sql.Identifier(self.prepare_role)
        self.db.admin.execute(infra.sql.SQL(
            "CREATE ROLE {} NOLOGIN NOINHERIT NOBYPASSRLS"
        ).format(role))
        # The isolated DB is dropped before the role. Test sessions switch using the admin connection.
        self.addCleanup(self.cleanup_prepare_role)
        apply_candidate(self.db.owner, "up")
        for grant in (
            "GRANT USAGE ON SCHEMA wb TO {}",
            "GRANT EXECUTE ON FUNCTION wb.allowed(text,boolean) TO {}",
            "GRANT SELECT,INSERT ON wb.scope_snapshot,wb.mission_create_intent,wb.mission_create_journal TO {}",
        ):
            self.db.owner.execute(infra.sql.SQL(grant).format(role))

    def cleanup_prepare_role(self):
        self.db.doCleanups()
        with infra.psycopg.connect(infra.DSN, autocommit=True) as admin:
            admin.execute(infra.sql.SQL("DROP ROLE {}").format(infra.sql.Identifier(self.prepare_role)))

    @staticmethod
    def refs(suffix):
        return tuple(prefix + suffix for prefix in ("map-", "rel-", "runtime-batch-", "mission-", "bind-", "op-"))

    def connect_prepare(self):
        params = dict(infra.psycopg.conninfo.conninfo_to_dict(infra.DSN), dbname=self.db.name)
        connection = infra.psycopg.connect(**params, autocommit=True)
        connection.execute(infra.sql.SQL("SET ROLE {}").format(infra.sql.Identifier(self.prepare_role)))
        return connection

    def counts(self):
        return tuple(self.db.owner.execute("SELECT count(*) FROM wb." + name).fetchone()[0] for name in TABLES)

    def assert_sqlstate(self, code, action):
        with self.assertRaises(infra.psycopg.Error) as error:
            action()
        self.assertEqual(error.exception.sqlstate, code)

    def test_first_commit_cold_replay_and_changed_selection(self):
        with self.connect_prepare() as connection:
            result = prepare_fixture(connection, self.key, self.snapshot, self.reservation)
        with self.connect_prepare() as fresh:
            self.assertEqual(prepare_fixture(fresh, self.key, self.snapshot, self.refs("discarded")), result)
            with self.assertRaisesRegex(ValueError, "SELECTION_CONFLICT"):
                prepare_fixture(fresh, self.key, self.snapshot, self.reservation, "other-context")
            narrower = ReadOnlyScopeSnapshotPreview(self.db.runtime).preview(
                "alice", "P1", "B1", requirement_ids=["R1"]
            )["snapshot"]
            with self.assertRaisesRegex(ValueError, "SELECTION_CONFLICT"):
                prepare_fixture(fresh, self.key, narrower, self.reservation)
            with self.assertRaisesRegex(ValueError, "SELECTION_CONFLICT"):
                prepare_fixture(fresh, self.key, dict(self.snapshot, batch_id="B2"), self.reservation)
        self.assertEqual(self.counts(), (1, 1, 1, 0))
        self.assertEqual(self.db.owner.execute(
            "SELECT batch_id,runtime_release_id,runtime_release_batch_id FROM wb.mission_create_intent"
        ).fetchone(), ("B1", "rel-1", "runtime-batch-1"))

    def test_prepare_refuses_an_existing_transaction(self):
        with self.connect_prepare() as connection:
            with connection.transaction():
                with self.assertRaisesRegex(ValueError, "IDLE_CONNECTION_REQUIRED"):
                    prepare_fixture(connection, self.key, self.snapshot, self.reservation)
        self.assertEqual(self.counts(), (0, 0, 0, 0))

    def test_rollback_missing_journal_and_recover(self):
        with self.connect_prepare() as connection:
            self.assert_sqlstate("23514", lambda: prepare_fixture(
                connection, self.key, self.snapshot, self.reservation, fail_before_journal=True
            ))
            self.assertEqual(self.counts(), (0, 0, 0, 0))
            self.assertEqual(prepare_fixture(connection, self.key, self.snapshot, self.reservation), "runtime-batch-1")
        self.assertEqual(self.counts(), (1, 1, 1, 0))

    def test_competing_same_key_commit_once_and_authority_uniqueness(self):
        barrier = threading.Barrier(2)

        def contend(suffix):
            with self.connect_prepare() as connection:
                barrier.wait(5)
                return prepare_fixture(connection, self.key, self.snapshot, self.refs(suffix))

        with ThreadPoolExecutor(max_workers=2) as executor:
            with self.db.owner.transaction():
                lock_key = json_bytes(self.key).decode()
                self.db.owner.execute("SELECT pg_advisory_xact_lock(8008, hashtext(%s))", (lock_key,))
                requests = [executor.submit(contend, suffix) for suffix in ("one", "two")]
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    waiters = self.db.owner.execute(
                        """SELECT count(*) FROM pg_locks WHERE database=(SELECT oid FROM pg_database
                           WHERE datname=current_database()) AND locktype='advisory'
                           AND classid=8008 AND NOT granted"""
                    ).fetchone()[0]
                    if waiters == 2:
                        break
                    time.sleep(.01)
                self.assertEqual(waiters, 2)
            results = [request.result(10) for request in requests]
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.counts(), (1, 1, 1, 0))
        duplicate = list(self.refs("new"))
        duplicate[2] = results[0]
        with self.connect_prepare() as connection:
            self.assert_sqlstate("23505", lambda: prepare_fixture(
                connection, (*self.key[:3], "K2"), self.snapshot, duplicate
            ))
            prepare_fixture(connection, ("other-authority", *self.key[1:]), self.snapshot, duplicate)
        self.assertEqual(self.counts(), (1, 2, 2, 0))

    def test_roles_and_revocation(self):
        with self.connect_prepare() as connection:
            prepare_fixture(connection, self.key, self.snapshot, self.reservation)
            self.assert_sqlstate("42501", lambda: connection.execute("SELECT * FROM wb.mission_create_receipt"))
            self.assert_sqlstate("42501", lambda: connection.execute("UPDATE wb.mission_create_intent SET batch_id='X'"))
            self.assert_sqlstate("42501", lambda: connection.execute("TRUNCATE wb.mission_create_journal"))
        self.assert_sqlstate("42501", lambda: self.db.runtime.execute("SELECT * FROM wb.scope_snapshot"))
        self.db.owner.execute("UPDATE wb.project_acl SET can_write=false WHERE principal='alice'")
        with self.connect_prepare() as connection:
            with self.assertRaisesRegex(PermissionError, "FORBIDDEN"):
                prepare_fixture(connection, self.key, self.snapshot, self.reservation)
        self.assertEqual(self.counts(), (1, 1, 1, 0))

    def test_append_only_and_nonempty_down(self):
        with self.connect_prepare() as connection:
            prepare_fixture(connection, self.key, self.snapshot, self.reservation)
        for command in ("DELETE FROM wb.scope_snapshot", "UPDATE wb.mission_create_intent SET batch_id='X'",
                        "TRUNCATE wb.mission_create_journal"):
            self.assert_sqlstate("55000", lambda: self.db.owner.execute(command))
        self.assert_sqlstate("55000", lambda: apply_candidate(self.db.owner, "down"))
        self.assertEqual(self.counts(), (1, 1, 1, 0))

    def test_empty_down_up_and_base_migration_unchanged(self):
        apply_candidate(self.db.owner, "down")
        self.assertIsNone(self.db.owner.execute("SELECT to_regclass('wb.scope_snapshot')").fetchone()[0])
        self.assertEqual(self.db.owner.execute("SELECT max(version) FROM public.wb_schema_migration").fetchone()[0], 7)
        apply_candidate(self.db.owner, "up")
        self.assertEqual(self.counts(), (0, 0, 0, 0))

    def test_explicit_008_and_009_fixture_ddl_in_both_orders(self):
        # 008 is deliberately not registered in the production migration history.
        # This tests coexistence and leaf removal, not a production graph runner.
        executor = self.db.role + "_metadata"
        role = infra.sql.Identifier(executor)
        self.db.admin.execute(infra.sql.SQL("CREATE ROLE {} NOLOGIN NOINHERIT NOBYPASSRLS").format(role))
        self.addCleanup(self.drop_metadata_role, executor)
        self.assertTrue(migrate_project_metadata(self.db.owner, executor))
        tables = (*TABLES, "project_namespace")

        def catalog():
            return self.db.owner.execute(
                """SELECT c.relname, c.relrowsecurity,c.relforcerowsecurity,
                          p.polname,p.polcmd, pg_get_expr(p.polqual,p.polrelid),
                          pg_get_expr(p.polwithcheck,p.polrelid)
                     FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                     LEFT JOIN pg_policy p ON p.polrelid=c.oid
                    WHERE n.nspname='wb' AND c.relname=ANY(%s)
                    ORDER BY c.relname,p.polname""", (list(tables),)
            ).fetchall()

        before = catalog()
        self.assertEqual({row[0] for row in before}, set(tables))
        apply_candidate(self.db.owner, "down")
        self.assertIsNotNone(self.db.owner.execute("SELECT to_regclass('wb.project_namespace')").fetchone()[0])
        apply_candidate(self.db.owner, "up")
        self.assertEqual(catalog(), before)

    def drop_metadata_role(self, executor):
        self.db.doCleanups()
        with infra.psycopg.connect(infra.DSN, autocommit=True) as admin:
            admin.execute(infra.sql.SQL("DROP ROLE {}").format(infra.sql.Identifier(executor)))

    def test_receipt_and_journal_cannot_cross_keys(self):
        other_key = (*self.key[:3], "K2")
        with self.connect_prepare() as connection:
            prepare_fixture(connection, self.key, self.snapshot, self.reservation)
            prepare_fixture(connection, other_key, self.snapshot, self.refs("2"))
            self.assert_sqlstate("42501", lambda: connection.execute(
                """INSERT INTO wb.mission_create_receipt
                   (formal_authority_ref,actor_ref,project_id,creation_key,receipt_ref,event_ref,receipt_hash)
                   VALUES (%s,%s,%s,%s,'r','e',%s)""", (*self.key,"a"*64)
            ))
        owner = self.db.owner
        owner.execute(
            """INSERT INTO wb.mission_create_receipt
               (formal_authority_ref,actor_ref,project_id,creation_key,receipt_ref,event_ref,receipt_hash)
               VALUES (%s,%s,%s,%s,'fixture-r','fixture-e',%s)""", (*self.key,"a"*64)
        )
        self.assert_sqlstate("23503", lambda: owner.execute(
            """INSERT INTO wb.mission_create_journal
               (formal_authority_ref,actor_ref,project_id,creation_key,journal_event_ref,phase,observed_result,receipt_ref)
               VALUES (%s,%s,%s,%s,'linked','RECONCILE','RECEIPT_LINKED','fixture-r')""", other_key
        ))
        self.assertEqual(self.counts(), (1, 2, 2, 1))

    def test_maximum_multibyte_key_and_overlength_rejection(self):
        randomizer = random.Random(8)
        authority, actor, project, creation_key = (
            "".join(chr(randomizer.randrange(0x10000, 0x20000)) for _ in range(96)) for _ in range(4)
        )
        with self.connect_prepare() as connection:
            self.db.owner.execute("INSERT INTO wb.project(project_id,name) VALUES(%s,'multibyte')", (project,))
            self.db.owner.execute("INSERT INTO wb.project_acl VALUES(%s,%s,true)", (project, actor))
            self.db.owner.execute(
                "INSERT INTO wb.release_batch(project_id,batch_id,release_date) VALUES(%s,'B1','2026-11-12')",
                (project,),
            )
            key = (authority, actor, project, creation_key)
            snapshot = dict(self.snapshot, project_id=project)
            prepare_fixture(connection, key, snapshot, self.reservation)
            self.assert_sqlstate("23514", lambda: prepare_fixture(
                connection, (*key[:3], creation_key + "x"), snapshot, self.refs("overlong")
            ))
        self.assertEqual(self.counts(), (1, 1, 1, 0))
