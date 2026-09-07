"""Narrow envelope regression using an isolated, real R1 store."""
from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

WORKSPACE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE / "ai-test/runtime"))
from aitest_runtime import product_entry as entry
from aitest_runtime.canonical_runtime import bootstrap_mission


def main() -> int:
    checks = {}
    targets = ("status", "mission", "orchestration", "all", "requirement", "coverage", "cases", "human_actions", "project", "execution", "defects", "invalid")
    seen_returns = set()
    source = Path(entry.__file__).read_text()
    function = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == "_interactive_truth_result")
    expected_returns = {node.lineno for node in ast.walk(function) if isinstance(node, ast.Return)}

    def trace(frame, event, arg):
        if event == "return" and frame.f_code.co_name == "_interactive_truth_result":
            seen_returns.add(frame.f_lineno)
        return trace

    with tempfile.TemporaryDirectory(prefix="mac2r-truth-") as td:
        root = Path(td)
        legacy = root / "ai-test/state/aitest.db"
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b"READ_ONLY_LEGACY_SENTINEL")
        env = {"AITEST_WORKSPACE_ROOT": str(root), "AITEST_RUNTIME_SPINE_DB": str(root / "durable/runtime-spine.db")}
        with patch.dict(os.environ, env):
            for populated in (False, True):
                if populated:
                    bootstrap_mission(root, mission_id="envelope-mission", goal_id="envelope-goal", goal={"objective": "verify truth envelope"}, attributes={"project": "construction"})
                for target in targets:
                    sys.settrace(trace)
                    try:
                        actual = entry.interactive_truth(target)
                    finally:
                        sys.settrace(None)
                    assert actual["truth_source"] == "R1_EVENT_STREAM"
                    assert actual["conversation_is_not_truth"] is True
                    expected_status = {"project": "PENDING_PRODUCTIZATION", "defects": "HOLD", "invalid": "INVALID_TARGET"}.get(target, "PASS")
                    if target in {"requirement", "coverage", "cases", "human_actions"} and not populated:
                        expected_status = "NO_MISSION"
                    assert actual["status"] == expected_status, (target, actual)
                    if target in {"requirement", "coverage", "cases", "human_actions"} and populated:
                        assert actual["mission_id"] == "envelope-mission"
                        assert actual["facts"] == []
                    # Only the envelope is changed: the entire target payload must survive.
                    original = entry._interactive_truth_result(target)
                    assert actual == {**original, "truth_source": "R1_EVENT_STREAM", "conversation_is_not_truth": True}
                    checks[f"{target}_{'mission' if populated else 'empty'}"] = True
            assert entry.interactive_truth("")["status"] == "PASS"
            assert entry.interactive_truth(" PROJECT ")["status"] == "PENDING_PRODUCTIZATION"
            for target in ("requirement", "coverage", "cases", "human_actions"):
                assert entry.interactive_truth(target, "missing-requirement", "missing-case")["facts"] == []
            assert legacy.read_bytes() == b"READ_ONLY_LEGACY_SENTINEL"
            assert not (root / "ai-test/state/runtime-spine.db").exists()
            checks["legacy_unchanged_no_alternate_spine"] = True
            with patch.object(entry, "runtime_status", side_effect=RuntimeError("R1_UNAVAILABLE")):
                for target in targets:
                    try:
                        entry.interactive_truth(target)
                    except RuntimeError as exc:
                        assert str(exc) == "R1_UNAVAILABLE"
                    else:
                        raise AssertionError("Exception converted to output")
            checks["all_target_exceptions_propagate"] = True
    # Multiline return events may report the opening expression line; CPython
    # reports the return statement line for these dict-return branches.
    assert expected_returns <= seen_returns, (expected_returns, seen_returns)
    checks["every_target_return_path_exercised"] = True
    print(json.dumps({"status": "PASS", "checks": checks}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
