from __future__ import annotations

import ast
import unittest
from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "center"
    / "migrations"
    / "versions"
    / "0017_mission_node_state.py"
)


def _literal(name):
    tree = ast.parse(MIGRATION.read_text(encoding="utf-8"), filename=str(MIGRATION))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("%s assignment missing" % name)


class MissionNodeMigrationContractTest(unittest.TestCase):
    def test_mission_node_revision_extends_current_n9_head(self):
        self.assertEqual("0017_mission_node_state", _literal("revision"))
        self.assertEqual("0016_n9_n7_result_auth", _literal("down_revision"))

    def test_mission_node_revision_declares_durable_current_truth_table(self):
        source = MIGRATION.read_text(encoding="utf-8")
        for token in (
            '"rc8_mission_node"',
            '"mission_node_id"',
            '"test_run_id"',
            '"node_type"',
            '"state"',
            '"output_refs"',
            '"updated_at"',
            "uq_rc8_mission_node_test_run_type",
        ):
            self.assertIn(token, source)


if __name__ == "__main__":
    unittest.main()
