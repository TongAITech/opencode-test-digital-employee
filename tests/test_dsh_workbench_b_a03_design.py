"""WB-A03 B-group design feasibility witness (SQLite only, NOT W1 implementation).

This tests the proposed compound keys and SQL join invariants on a disposable
in-memory SQLite database. It is neither PostgreSQL/HTTP/R1 qualification nor
the real WB-B01..B06 service. F must independently validate W1 later.
"""
import sqlite3
import unittest


DDL = """
PRAGMA foreign_keys = ON;
CREATE TABLE project(project_id TEXT PRIMARY KEY);
CREATE TABLE batch(
    project_id TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    release_date TEXT NOT NULL,
    relation_revision INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY(project_id,batch_id),
    UNIQUE(project_id,release_date),
    FOREIGN KEY(project_id) REFERENCES project(project_id)
);
CREATE TABLE batch_date_history(
    project_id TEXT NOT NULL, batch_id TEXT NOT NULL,
    revision INTEGER NOT NULL, old_date TEXT NOT NULL,
    new_date TEXT NOT NULL, reason TEXT NOT NULL,
    PRIMARY KEY(project_id,batch_id,revision),
    FOREIGN KEY(project_id,batch_id) REFERENCES batch(project_id,batch_id)
);
CREATE TABLE requirement(
    project_id TEXT NOT NULL, requirement_id TEXT NOT NULL,
    source_system TEXT NOT NULL, source_key TEXT NOT NULL,
    PRIMARY KEY(project_id,requirement_id),
    UNIQUE(project_id,source_system,source_key)
);
CREATE TABLE system_version(
    project_id TEXT NOT NULL, version_id TEXT NOT NULL,
    system_id TEXT NOT NULL, display_label TEXT NOT NULL,
    source_system TEXT NOT NULL, source_key TEXT NOT NULL,
    PRIMARY KEY(project_id,version_id),
    UNIQUE(project_id,source_system,source_key)
);
CREATE TABLE sst(
    project_id TEXT NOT NULL, version_id TEXT NOT NULL,
    sst_id TEXT NOT NULL, source_system TEXT NOT NULL,
    source_key TEXT NOT NULL,
    PRIMARY KEY(project_id,version_id,sst_id),
    UNIQUE(project_id,sst_id),
    UNIQUE(project_id,version_id,source_system,source_key),
    FOREIGN KEY(project_id,version_id)
      REFERENCES system_version(project_id,version_id)
);
CREATE TABLE sst_source_trace(
    project_id TEXT NOT NULL, version_id TEXT NOT NULL, sst_id TEXT NOT NULL,
    source_namespace TEXT NOT NULL, source_revision TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    PRIMARY KEY(project_id,version_id,sst_id),
    UNIQUE(project_id,version_id,source_ref),
    FOREIGN KEY(project_id,version_id,sst_id) REFERENCES sst(project_id,version_id,sst_id)
);
CREATE TABLE br(
    project_id TEXT NOT NULL, batch_id TEXT NOT NULL,
    requirement_id TEXT NOT NULL,
    PRIMARY KEY(project_id,batch_id,requirement_id),
    FOREIGN KEY(project_id,batch_id) REFERENCES batch(project_id,batch_id),
    FOREIGN KEY(project_id,requirement_id)
      REFERENCES requirement(project_id,requirement_id)
);
CREATE TABLE bv(
    project_id TEXT NOT NULL, batch_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    PRIMARY KEY(project_id,batch_id,version_id),
    FOREIGN KEY(project_id,batch_id) REFERENCES batch(project_id,batch_id),
    FOREIGN KEY(project_id,version_id)
      REFERENCES system_version(project_id,version_id)
);
CREATE TABLE authoritative_req_version(
    project_id TEXT NOT NULL, batch_id TEXT NOT NULL,
    requirement_id TEXT NOT NULL, version_id TEXT NOT NULL,
    source_link_ref TEXT NOT NULL,
    PRIMARY KEY(project_id,batch_id,requirement_id,version_id),
    UNIQUE(project_id,batch_id,source_link_ref),
    FOREIGN KEY(project_id,batch_id,requirement_id)
      REFERENCES br(project_id,batch_id,requirement_id),
    FOREIGN KEY(project_id,batch_id,version_id)
      REFERENCES bv(project_id,batch_id,version_id)
);
CREATE TABLE brv(
    project_id TEXT NOT NULL, batch_id TEXT NOT NULL,
    requirement_id TEXT NOT NULL, version_id TEXT NOT NULL,
    split_state TEXT NOT NULL DEFAULT 'UNSPLIT'
        CHECK(split_state IN ('UNSPLIT','SPLIT')),
    PRIMARY KEY(project_id,batch_id,requirement_id,version_id),
    FOREIGN KEY(project_id,batch_id,requirement_id)
      REFERENCES br(project_id,batch_id,requirement_id),
    FOREIGN KEY(project_id,batch_id,version_id)
      REFERENCES bv(project_id,batch_id,version_id),
    FOREIGN KEY(project_id,batch_id,requirement_id,version_id)
      REFERENCES authoritative_req_version(
        project_id,batch_id,requirement_id,version_id)
);
CREATE TABLE authoritative_link(
    project_id TEXT NOT NULL, batch_id TEXT NOT NULL,
    requirement_id TEXT NOT NULL, version_id TEXT NOT NULL,
    sst_id TEXT NOT NULL, source_link_ref TEXT NOT NULL,
    PRIMARY KEY(project_id,batch_id,requirement_id,version_id,sst_id),
    UNIQUE(project_id,batch_id,source_link_ref),
    FOREIGN KEY(project_id,batch_id,requirement_id,version_id)
      REFERENCES brv(project_id,batch_id,requirement_id,version_id),
    FOREIGN KEY(project_id,version_id,sst_id)
      REFERENCES sst(project_id,version_id,sst_id)
);
CREATE TABLE brvs(
    project_id TEXT NOT NULL, batch_id TEXT NOT NULL,
    requirement_id TEXT NOT NULL, version_id TEXT NOT NULL,
    sst_id TEXT NOT NULL,
    PRIMARY KEY(project_id,batch_id,requirement_id,version_id,sst_id),
    FOREIGN KEY(project_id,batch_id,requirement_id,version_id)
      REFERENCES brv(project_id,batch_id,requirement_id,version_id),
    FOREIGN KEY(project_id,batch_id,requirement_id,version_id,sst_id)
      REFERENCES authoritative_link(
        project_id,batch_id,requirement_id,version_id,sst_id)
);
"""

SCOPE_SQL = """
SELECT x.requirement_id,x.version_id,z.sst_id
FROM brv AS x
LEFT JOIN brvs AS z
  ON z.project_id=x.project_id AND z.batch_id=x.batch_id
 AND z.requirement_id=x.requirement_id AND z.version_id=x.version_id
WHERE x.project_id=? AND x.batch_id=?
ORDER BY x.requirement_id,x.version_id,z.sst_id
"""


class DomainError(Exception):
    def __init__(self, status, code):
        super().__init__(code)
        self.status = status
        self.code = code


def scope_rows(db, authorized_projects, project_id, batch_id):
    # Permission first: intentionally indistinguishable absent/foreign batches.
    if project_id not in authorized_projects:
        raise DomainError(403, "FORBIDDEN")
    if db.execute("SELECT 1 FROM batch WHERE project_id=? AND batch_id=?",
                  (project_id,batch_id)).fetchone() is None:
        raise DomainError(404, "RESOURCE_NOT_FOUND")
    return db.execute(SCOPE_SQL, (project_id,batch_id)).fetchall()


def attach_sst(db, authorized_projects, project_id, batch_id, requirement_id,
               version_id, sst_id, expected_revision, source_link_ref):
    if project_id not in authorized_projects:
        raise DomainError(403, "FORBIDDEN")
    batch = db.execute(
        "SELECT relation_revision FROM batch WHERE project_id=? AND batch_id=?",
        (project_id,batch_id)).fetchone()
    if batch is None:
        raise DomainError(404, "RESOURCE_NOT_FOUND")
    if batch[0] != expected_revision:
        raise DomainError(409, "STATE_REVISION_CONFLICT")
    link = (project_id,batch_id,requirement_id,version_id,sst_id)
    if db.execute("""SELECT 1 FROM authoritative_link
                     WHERE project_id=? AND batch_id=? AND requirement_id=?
                       AND version_id=? AND sst_id=? AND source_link_ref=?""",
                  link+(source_link_ref,)).fetchone() is None:
        raise DomainError(422, "ILLEGAL_ASSOCIATION")
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute("INSERT INTO brvs VALUES (?,?,?,?,?)", link)
        updated = db.execute(
            """UPDATE batch SET relation_revision=relation_revision+1
               WHERE project_id=? AND batch_id=? AND relation_revision=?""",
            (project_id,batch_id,expected_revision))
        if updated.rowcount != 1:
            raise DomainError(409, "STATE_REVISION_CONFLICT")
        db.commit()
    except BaseException:
        db.rollback()
        raise


class TestBA03SqlDesignWitness(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        self.addCleanup(self.db.close)
        self.db.executescript(DDL)
        self.db.executemany("INSERT INTO project VALUES (?)", [("P1",),("P2",)])
        self.db.executemany(
            "INSERT INTO batch(project_id,batch_id,release_date) VALUES (?,?,?)",
            [("P1","B1","2026-11-12"),("P1","B2","2026-11-19"),
             ("P2","B3","2026-11-12")])
        self.db.executemany("INSERT INTO requirement VALUES (?,?,?,?)",
                            [("P1","R1","Starlink","R1"),
                             ("P1","R2","Starlink","R2")])
        self.db.executemany("INSERT INTO system_version VALUES (?,?,?,?,?,?)",
                            [("P1","VA","SYS-A","PF1.2.0","Starlink","a-120"),
                             ("P1","VB","SYS-B","PF1.2.0","Starlink","b-120"),
                             ("P1","VC","SYS-C","PF3.1.0","Starlink","c-310")])
        self.db.executemany("INSERT INTO sst VALUES (?,?,?,?,?)",
                            [("P1",v,s,"Starlink",s) for v,s in
                             [("VA","S1"),("VA","S2"),("VB","S3"),
                              ("VA","S4"),("VC","S5"),("VC","S6"),("VC","S7")]])
        for b,r,v in [("B1","R1","VA"),("B1","R1","VB"),("B1","R1","VC"),
                      ("B1","R2","VA"),("B1","R2","VC"),
                      ("B2","R1","VA")]:
            self.db.execute("INSERT OR IGNORE INTO br VALUES (?,?,?)",("P1",b,r))
            self.db.execute("INSERT OR IGNORE INTO bv VALUES (?,?,?)",("P1",b,v))
            self.db.execute("INSERT INTO authoritative_req_version VALUES (?,?,?,?,?)",
                            ("P1",b,r,v,"verified-"+b+"-"+r+"-"+v))
            self.db.execute("INSERT INTO brv VALUES (?,?,?,?,?)",
                            ("P1",b,r,v,"UNSPLIT"))
        for b,r,v,s in [("B1","R1","VA","S1"),("B1","R1","VA","S2"),
                        ("B1","R1","VB","S3"),("B1","R1","VC","S6"),
                        ("B1","R1","VC","S7"),("B1","R2","VA","S4")]:
            self.db.execute("INSERT INTO authoritative_link VALUES (?,?,?,?,?,?)",
                            ("P1",b,r,v,s,"link-"+b+"-"+r+"-"+s))
            self.db.execute("INSERT INTO brvs VALUES (?,?,?,?,?)",
                            ("P1",b,r,v,s))

    def test_t1_t2_t3_real_join_no_cartesian(self):
        rows = scope_rows(self.db, {"P1"}, "P1", "B1")
        self.assertEqual(len(rows), 7)  # six verified links + one UNSPLIT row
        self.assertEqual(
            {(r,v,s) for r,v,s in rows},
            {("R1","VA","S1"),("R1","VA","S2"),
             ("R1","VB","S3"),("R1","VC","S6"),("R1","VC","S7"),
             ("R2","VA","S4"),("R2","VC",None)})
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM system_version WHERE display_label='PF1.2.0'"
        ).fetchone()[0], 2)

    def test_t4_cross_date_and_cross_project_not_leaking(self):
        self.assertEqual(scope_rows(self.db, {"P1"}, "P1", "B2"),
                         [("R1","VA",None)])
        self.assertEqual(scope_rows(self.db, {"P2"}, "P2", "B3"), [])
        with self.assertRaises(DomainError) as error:
            scope_rows(self.db, {"P2"}, "P1", "B1")
        self.assertEqual(error.exception.status, 403)

    def test_t5_unsplit_relation_not_fabricated_sst(self):
        self.assertIn(("R2","VC",None), scope_rows(self.db, {"P1"}, "P1", "B1"))

    def test_t6_foreign_keys_reject_unapproved_link_and_cross_batch(self):
        for link in [("P1","B1","R2","VB","S3"),
                     ("P1","B2","R1","VA","S1"),
                     ("P1","B1","R1","VA","S4")]:
            with self.subTest(link=link):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.db.execute("INSERT INTO brvs VALUES (?,?,?,?,?)", link)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM brvs").fetchone()[0], 6)

    def test_t8_release_date_unique_across_project_not_within(self):
        # P2 may share P1's date; P1 cannot move B1 onto B2's date.
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                "UPDATE batch SET release_date='2026-11-19' WHERE project_id='P1' AND batch_id='B1'")
        self.assertEqual(self.db.execute(
            "SELECT release_date FROM batch WHERE project_id='P1' AND batch_id='B1'"
        ).fetchone()[0], "2026-11-12")
        self.db.execute("BEGIN IMMEDIATE")
        self.db.execute(
            "UPDATE batch SET release_date='2026-11-13' WHERE project_id='P1' AND batch_id='B1'")
        self.db.execute(
            """INSERT INTO batch_date_history VALUES
               ('P1','B1',2,'2026-11-12','2026-11-13','approved change')""")
        self.db.commit()
        self.assertEqual(self.db.execute(
            "SELECT batch_id FROM batch WHERE project_id='P1' AND release_date='2026-11-13'"
        ).fetchone()[0], "B1")
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM batch_date_history WHERE batch_id='B1'"
        ).fetchone()[0], 1)

    def test_403_priority_and_409_422_no_partial_side_effects(self):
        for args,status in [
            (("P2", "P1", "B1","R1","VA","S1",1,"link-B1-R1-S1"),403),
            (("P1", "P1", "B1","R1","VA","S1",99,"link-B1-R1-S1"),409),
            (("P1", "P1", "B1","R2","VA","S1",1,"wrong-link"),422),
            (("P1", "P1", "B2","R1","VA","S1",1,"link-B1-R1-S1"),422),
        ]:
            grants,project,batch,req,ver,sst,rev,ref=args
            with self.subTest(status=status,batch=batch):
                before = self.db.total_changes
                with self.assertRaises(DomainError) as err:
                    attach_sst(self.db, {grants}, project,batch,req,ver,sst,rev,ref)
                self.assertEqual(err.exception.status,status)
                self.assertEqual(self.db.total_changes,before)

    def test_concurrent_revision_mismatch_is_409(self):
        self.db.execute(
            "INSERT INTO authoritative_link VALUES (?,?,?,?,?,?)",
            ("P1","B1","R2","VC","S5","link-B1-R2-S5"))
        attach_sst(self.db, {"P1"}, "P1","B1","R2","VC","S5",1,"link-B1-R2-S5")
        with self.assertRaises(DomainError) as error:
            attach_sst(self.db, {"P1"}, "P1","B1","R2","VC","S5",1,"link-B1-R2-S5")
        self.assertEqual(error.exception.status,409)

    def test_composite_fk_blocks_orphan_requiring_version(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO brv VALUES (?,?,?,?,?)",
                            ("P1","B1","R2","VB","UNSPLIT"))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO authoritative_link VALUES (?,?,?,?,?,?)",
                            ("P1","B1","R1","VB","S1","invalid-version-sst"))


    def test_multi_link_transaction_reverts_first_success_if_second_invalid(self):
        """Witness real FK rollback at the SQL transaction boundary."""
        self.db.execute(
            "INSERT INTO authoritative_link VALUES (?,?,?,?,?,?)",
            ("P1","B1","R2","VC","S5","verified-r2-vc-s5"))
        before = self.db.execute("SELECT COUNT(*) FROM brvs").fetchone()[0]
        self.db.execute("BEGIN IMMEDIATE")
        with self.assertRaises(sqlite3.IntegrityError):
            try:
                self.db.execute("INSERT INTO brvs VALUES (?,?,?,?,?)",
                                ("P1","B1","R2","VC","S5"))
                # B2 has R1/VA, but has no source-verified SST relation.
                self.db.execute("INSERT INTO brvs VALUES (?,?,?,?,?)",
                                ("P1","B2","R1","VA","S1"))
                self.db.commit()
            except sqlite3.IntegrityError:
                self.db.rollback()
                raise
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM brvs").fetchone()[0], before)
        self.assertIsNone(self.db.execute(
            """SELECT 1 FROM brvs WHERE project_id='P1' AND batch_id='B1'
               AND requirement_id='R2' AND version_id='VC' AND sst_id='S5'"""
        ).fetchone())

    def test_date_update_reverted_if_audit_insert_fails(self):
        before = self.db.execute(
            "SELECT release_date FROM batch WHERE project_id='P1' AND batch_id='B1'"
        ).fetchone()[0]
        self.db.execute("BEGIN IMMEDIATE")
        with self.assertRaises(sqlite3.IntegrityError):
            try:
                self.db.execute(
                    "UPDATE batch SET release_date='2026-11-15' WHERE project_id='P1' AND batch_id='B1'")
                self.db.execute(
                    """INSERT INTO batch_date_history VALUES
                       ('P1','INVALID_BATCH',2,'2026-11-12','2026-11-15','failed audit')""")
                self.db.commit()
            except sqlite3.IntegrityError:
                self.db.rollback()
                raise
        self.assertEqual(self.db.execute(
            "SELECT release_date FROM batch WHERE project_id='P1' AND batch_id='B1'"
        ).fetchone()[0], before)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM batch_date_history").fetchone()[0], 0)



    def _fg18_reused_source_ids(self):
        for v,s,revision in (("VA","SST-A-100","8"),("VB","SST-B-100","9")):
            self.db.execute("INSERT INTO sst VALUES (?,?,?,?,?)",
                            ("P1",v,s,"Starlink","SST-100"))
            self.db.execute("INSERT INTO sst_source_trace VALUES (?,?,?,?,?,?)",
                            ("P1",v,s,"tenant-FAT1",revision,"Starlink/SST-100/"+v))

    def test_fg18_same_raw_source_id_in_two_versions_distinct(self):
        self._fg18_reused_source_ids()
        self.assertEqual(
            self.db.execute("SELECT version_id,sst_id FROM sst WHERE project_id=? AND source_key=? ORDER BY version_id",
                            ("P1","SST-100")).fetchall(),
            [("VA","SST-A-100"),("VB","SST-B-100")])
        for v,s in (("VA","SST-A-100"),("VB","SST-B-100")):
            self.db.execute("INSERT INTO authoritative_link VALUES (?,?,?,?,?,?)",
                            ("P1","B1","R1",v,s,"verified-B1-R1-"+v))
            self.db.execute("INSERT INTO brvs VALUES (?,?,?,?,?)",("P1","B1","R1",v,s))
        rows=scope_rows(self.db,{"P1"},"P1","B1")
        self.assertIn(("R1","VA","SST-A-100"),rows)
        self.assertIn(("R1","VB","SST-B-100"),rows)
        self.assertNotIn(("R1","VA","SST-B-100"),rows)
        self.assertNotIn(("R1","VB","SST-A-100"),rows)
        self.assertEqual(
            self.db.execute("SELECT version_id,source_revision,source_ref FROM sst_source_trace ORDER BY version_id").fetchall(),
            [("VA","8","Starlink/SST-100/VA"),("VB","9","Starlink/SST-100/VB")])

    def test_fg18_wrong_version_req_batch_links_rejected(self):
        self._fg18_reused_source_ids()
        for bad in [("P1","B1","R1","VA","SST-B-100","wrong-version"),
                    ("P1","B1","R2","VB","SST-B-100","wrong-requirement"),
                    ("P1","B2","R1","VA","SST-B-100","wrong-batch")]:
            with self.subTest(link=bad):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.db.execute("INSERT INTO authoritative_link VALUES (?,?,?,?,?,?)",bad)
        for bad in [("P1","B1","R1","VA","SST-B-100"),
                    ("P1","B1","R1","VB","SST-A-100"),
                    ("P1","B2","R1","VA","SST-A-100")]:
            with self.subTest(link=bad):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.db.execute("INSERT INTO brvs VALUES (?,?,?,?,?)",bad)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM brvs").fetchone()[0],6)

    def test_fg18_same_version_source_duplicate_and_internal_id_reuse_rejected(self):
        self._fg18_reused_source_ids()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO sst VALUES (?,?,?,?,?)",
                            ("P1","VA","SST-C-100","Starlink","SST-100"))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO sst VALUES (?,?,?,?,?)",
                            ("P1","VC","SST-A-100","Starlink","different-raw"))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM sst WHERE source_key='SST-100'").fetchone()[0],2)

    def test_fg18_same_raw_source_id_across_projects_allowed(self):
        self._fg18_reused_source_ids()
        self.db.execute("INSERT INTO system_version VALUES (?,?,?,?,?,?)",
                        ("P2","VP2","SYS-A","PF1.2.0","Starlink","a-120"))
        self.db.execute("INSERT INTO sst VALUES (?,?,?,?,?)",
                        ("P2","VP2","SST-P2","Starlink","SST-100"))
        self.assertEqual(
            self.db.execute("SELECT project_id,version_id,sst_id FROM sst WHERE source_key='SST-100' ORDER BY project_id,version_id").fetchall(),
            [("P1","VA","SST-A-100"),("P1","VB","SST-B-100"),("P2","VP2","SST-P2")])

if __name__ == "__main__":
    unittest.main()
