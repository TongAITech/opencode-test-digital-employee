from __future__ import annotations

import importlib.util
from pathlib import Path

from rc7_release.real_mission_qualification import evaluate_real_mission
from rc7_release.real_mission_qualification_strict import evaluate_real_mission_strict


_HELPER_PATH = Path(__file__).with_name("test_rc7_real_mission_qualification.py")
_SPEC = importlib.util.spec_from_file_location("rc7_real_mission_fixture", str(_HELPER_PATH))
assert _SPEC is not None and _SPEC.loader is not None
_FIXTURE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FIXTURE)


def test_strict_gate_rejects_worker_whose_pass_task_has_no_task_scoped_tool_receipt(tmp_path, monkeypatch):
    original = _FIXTURE._append_tool_call

    def append_except_repair(truth, *, worker, task_id, number):
        if worker == "worker-repair":
            return None
        return original(truth, worker=worker, task_id=task_id, number=number)

    monkeypatch.setattr(_FIXTURE, "_append_tool_call", append_except_repair)
    r1_path = _FIXTURE._build_r1(tmp_path)

    base = evaluate_real_mission(
        r1_path=str(r1_path),
        mission_id=_FIXTURE.MISSION,
        source_commit=_FIXTURE.COMMIT,
    )
    strict = evaluate_real_mission_strict(
        r1_path=str(r1_path),
        mission_id=_FIXTURE.MISSION,
        source_commit=_FIXTURE.COMMIT,
    )

    # The historical/global proof was vulnerable here: source worker's receipt
    # is enough to keep a non-empty Mission receipt set.
    assert base["status"] == "PASS"
    assert base["worker_proof"]["tool_receipts"]

    # Strict proof binds every PASS domain Task to its own lease owner and exact
    # task:<task_id> WORKER_TOOL_CALLED scope.
    assert strict["status"] == "HOLD"
    expected = "DOMAIN_TASK_REAL_TOOL_CALL_MISSING:%s" % _FIXTURE.REPAIR_TASK
    assert expected in strict["blocking_reasons"]
    repair = strict["task_scoped_worker_proof"][_FIXTURE.REPAIR_TASK]
    assert repair["lease_owner"] == "worker-repair"
    assert repair["tool_receipts"] == []
    assert repair["proven"] is False


def test_strict_gate_passes_when_each_domain_task_has_owner_scoped_receipt(tmp_path):
    r1_path = _FIXTURE._build_r1(tmp_path)
    result = evaluate_real_mission_strict(
        r1_path=str(r1_path),
        mission_id=_FIXTURE.MISSION,
        source_commit=_FIXTURE.COMMIT,
    )

    assert result["status"] == "PASS"
    for task_id in (_FIXTURE.SOURCE_TASK, _FIXTURE.REPAIR_TASK):
        proof = result["task_scoped_worker_proof"][task_id]
        assert proof["proven"] is True
        assert proof["tool_receipts"]
        assert proof["task_scope"] == "task:%s" % task_id
