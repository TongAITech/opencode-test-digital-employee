"""F independent B design negative: a raw upstream SST ID can be reused by versions.

This test reads the exact B-group DDL from its source checkout, not a copied
fixture. Set WB_B_CHECKOUT to the checked-out PR #89 source SHA for execution.
No production SQL/HTTP or bank field qualification is inferred.
"""
import ast
import os
import sqlite3
import unittest
from pathlib import Path


class TestSstIdentityAcrossVersionsF(unittest.TestCase):
    def setUp(self):
        source = Path(os.environ.get("WB_B_CHECKOUT", "."))
        path = source / "tests" / "test_dsh_workbench_b_a03_design.py"
        if not path.exists():
            self.skipTest("B PR source is not checked out; run via F B independent workflow")
        doc = ast.parse(path.read_text(encoding="utf-8"))
        ddl = next((
            ast.literal_eval(node.value)
            for node in doc.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "DDL"
                    for target in node.targets)
        ), None)
        self.assertIsInstance(ddl, str, "B executable SQL contract DDL missing")
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.executescript(ddl)
        self.db.execute("INSERT INTO project VALUES (?)", ("P1",))
        self.db.executemany(
            "INSERT INTO system_version VALUES (?,?,?,?,?,?)",
            [("P1", "V1", "SYS-A", "PF1.2.1", "Starlink", "A-121"),
             ("P1", "V2", "SYS-B", "PF1.2.1", "Starlink", "B-121")]
        )

    def test_same_raw_sst_id_different_system_versions_are_distinct(self):
        # Per B SIGNOFF §2: when source ID is reused by different versions,
        # keep version-specific internal identities and original source_ref.
        # A project-level UNIQUE(project,source_system,raw_source_key)
        # incorrectly forbids the second version-scoped occurrence.
        self.db.execute(
            "INSERT INTO sst VALUES (?,?,?,?,?)",
            ("P1", "V1", "SST-A", "Starlink", "SST-100")
        )
        self.db.execute(
            "INSERT INTO sst VALUES (?,?,?,?,?)",
            ("P1", "V2", "SST-B", "Starlink", "SST-100")
        )
        rows = self.db.execute(
            "SELECT version_id,sst_id FROM sst WHERE project_id=? AND source_key=? ORDER BY version_id",
            ("P1", "SST-100")
        ).fetchall()
        self.assertEqual(rows, [("V1", "SST-A"), ("V2", "SST-B")])


if __name__ == "__main__":
    unittest.main()
