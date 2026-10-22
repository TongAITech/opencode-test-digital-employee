from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, Optional, Tuple


VERSION_NUM_MAX_LENGTH = 32
VERSIONS_DIR = Path(__file__).resolve().parents[1] / "center" / "migrations" / "versions"


def _literal_assignment(tree: ast.Module, name: str):
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        return ast.literal_eval(node.value)
    raise AssertionError("%s assignment missing" % name)


def _load_revisions() -> Dict[str, Tuple[Optional[str], Path]]:
    revisions: Dict[str, Tuple[Optional[str], Path]] = {}
    files = sorted(VERSIONS_DIR.glob("*.py"))
    assert files, "no Alembic revisions found"
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        revision = _literal_assignment(tree, "revision")
        down_revision = _literal_assignment(tree, "down_revision")
        assert isinstance(revision, str) and revision, "%s revision must be a non-empty string" % path.name
        assert len(revision) <= VERSION_NUM_MAX_LENGTH, (
            "%s revision %r has %s chars; Alembic version_num defaults to VARCHAR(%s)"
            % (path.name, revision, len(revision), VERSION_NUM_MAX_LENGTH)
        )
        assert revision not in revisions, "duplicate Alembic revision: %s" % revision
        assert down_revision is None or isinstance(down_revision, str), (
            "%s uses an unsupported non-linear down_revision" % path.name
        )
        if isinstance(down_revision, str):
            assert len(down_revision) <= VERSION_NUM_MAX_LENGTH, (
                "%s down_revision %r exceeds version_num VARCHAR(%s)"
                % (path.name, down_revision, VERSION_NUM_MAX_LENGTH)
            )
        revisions[revision] = (down_revision, path)
    return revisions


def test_alembic_revision_ids_fit_version_table_and_form_one_closed_chain() -> None:
    revisions = _load_revisions()
    roots = [revision for revision, (parent, _) in revisions.items() if parent is None]
    assert len(roots) == 1, "expected exactly one Alembic root, got %s" % roots

    children: Dict[str, list] = {revision: [] for revision in revisions}
    for revision, (parent, path) in revisions.items():
        if parent is None:
            continue
        assert parent in revisions, "%s references missing down_revision %s" % (path.name, parent)
        children[parent].append(revision)

    heads = [revision for revision, values in children.items() if not values]
    assert len(heads) == 1, "expected exactly one Alembic head, got %s" % heads
    assert all(len(values) <= 1 for values in children.values()), "unexpected Alembic branch detected"

    visited = set()
    current = roots[0]
    while current is not None:
        assert current not in visited, "Alembic revision cycle at %s" % current
        visited.add(current)
        next_values = children[current]
        current = next_values[0] if next_values else None
    assert visited == set(revisions), "disconnected Alembic revisions: %s" % sorted(set(revisions) - visited)


def test_requirement_delivery_revision_remains_schema_compatible() -> None:
    revisions = _load_revisions()
    assert "0007_req_delivery" in revisions
    assert revisions["0007_req_delivery"][0] == "0006_lease_recovery"


def test_test_round_runtime_and_stage_work_item_revisions_are_linear() -> None:
    revisions = _load_revisions()
    assert revisions["0008_test_rounds"][0] == "0007_req_delivery"
    assert revisions["0009_run_round"][0] == "0008_test_rounds"
    assert revisions["0010_stage_workitem"][0] == "0009_run_round"


if __name__ == "__main__":
    test_alembic_revision_ids_fit_version_table_and_form_one_closed_chain()
    test_requirement_delivery_revision_remains_schema_compatible()
    test_test_round_runtime_and_stage_work_item_revisions_are_linear()
    print("RC8_ALEMBIC_REVISION_CONTRACT_PASS")
