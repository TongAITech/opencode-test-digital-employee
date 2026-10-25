from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import rc6_runtime.execution_overlay  # noqa: F401
from rc6_runtime.diagnosis import CorrelationScope
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.attempt_cat import ATTEMPT_CAT_QUERY_KIND, AttemptCatError, AttemptCatQueryService, cat_required_for_context
from rc7_runtime.bank_attempt_cat_execution import BankAttemptCatRuntimeExecutionService
from rc7_runtime.models import Mission, Task, TaskStatus
from rc7_runtime.truth_overlay import append_entity, install_rc7_truth_overlay


MISSION = "MISSION-CAT-HARD"
RELEASE = "REL-CAT-HARD"
TASK = "TASK-CAT-HARD"
ATTEMPT = "ATT-CAT-HARD"
TARGET = "TARGET-PFC"


def _truth(tmp_path: Path, *, layer: str = "L4") -> TruthRuntime:
    install_rc7_truth_overlay()
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    append_entity(truth, Mission(mission_id=MISSION, release_id=RELEASE, goal="CAT hardening"), release_id=RELEASE)
    append_entity(
        truth,
        Task(task_id=TASK, mission_id=MISSION, node="EXECUTION", task_type="PRODUCE", objective="execute", state=TaskStatus.RUNNING, lease_owner="WORKER-EXEC"),
        release_id=RELEASE,
    )
    truth.append_atomic(
        "EXECUTION_ATTEMPT_UPSERTED",
        {
            "attempt_id": ATTEMPT,
            "release_id": RELEASE,
            "requirement_id": "REQ-CAT-HARD",
            "tc_id": "TC-CAT-HARD",
            "case_version": 1,
            "target_id": TARGET,
            "layer": layer,
            "status": "FAIL",
            "actual_result": {"http_status": 500},
            "tool_call_refs": ["browser-mcp://real-invocation"],
            "evidence_refs": ["EVD-REAL-EXECUTION"],
        },
    )
    return truth


def _provider(tmp_path: Path) -> Path:
    script = tmp_path / "cat_provider.py"
    script.write_text(
        """
import json, sys
request = json.load(sys.stdin)
assert request["attempt_id"] == "ATT-CAT-HARD"
assert request["request"]["policy"]["real_action_executed"] is True
response = {
  "success": True,
  "target_verified": True,
  "tool_call_ref": "cat-tool://ATT-CAT-HARD",
  "evidence_ref": "cat-provider-evidence://ATT-CAT-HARD",
  "cat_evidence_ref": "cat-log://ATT-CAT-HARD",
  "correlation_ref": "cat-correlation://TRACE-CAT-HARD",
  "signals": {"ERROR": 3, "trace_id": "TRACE-CAT-HARD"}
}
json.dump(response, sys.stdout)
""",
        encoding="utf-8",
    )
    config = tmp_path / "bank-field-providers.json"
    config.write_text(
        json.dumps({"providers": {"BANK_CAT_QUERY": {"provider_id": "engineering-cat-provider", "command": [sys.executable, str(script)], "timeout_seconds": 30}}}),
        encoding="utf-8",
    )
    return config


def _scope() -> dict:
    return {"applications": ["cfg-center", "cfg-data"], "window_start": 100, "window_end": 160, "trace_id": "TRACE-CAT-HARD"}


def _failure(*, layer: str = "L4", state: str = "UNKNOWN") -> dict:
    return {
        "attempt_id": ATTEMPT,
        "target_id": TARGET,
        "layer": layer,
        "real_action_executed": True,
        "remote_integration": False,
        "business_action_state": state,
        "correlation": _scope(),
    }


def test_dynamic_cat_policy_is_fail_closed_for_unknown_dispatch() -> None:
    assert cat_required_for_context({"layer": "L3", "real_action_executed": True})
    for layer in ("L4", "L5", "L6", "L7"):
        assert cat_required_for_context({"layer": layer, "real_action_executed": True, "business_action_state": "UNKNOWN"})
        assert not cat_required_for_context({"layer": layer, "real_action_executed": True, "business_action_state": "NOT_DISPATCHED"})
    assert not cat_required_for_context({"layer": "L7", "real_action_executed": False, "business_action_state": "UNKNOWN"})
    assert cat_required_for_context({"layer": "L2", "real_action_executed": True, "remote_integration": True})


def test_cat_query_is_current_attempt_bound_and_r1_replayed(tmp_path: Path, monkeypatch) -> None:
    truth = _truth(tmp_path)
    monkeypatch.setenv("PFC_RC7_BANK_SERVICE_PROVIDER_CONFIG", str(_provider(tmp_path)))
    service = AttemptCatQueryService(truth, tmp_path / "state")
    result = service.query(
        mission_id=MISSION, task_id=TASK, worker_id="WORKER-EXEC", attempt_id=ATTEMPT,
        target_id=TARGET, correlation=_scope(), failure_context=_failure(),
    )
    assert result["status"] == "PASS"
    verified = service.require_for_failure_context(
        mission_id=MISSION, task_id=TASK, worker_id="WORKER-EXEC", failure_context=_failure(),
    )
    assert verified is not None
    assert verified["cat_query_evidence_id"] == result["evidence_id"]
    rows = truth.query("rc7_evidence", evidence_id=result["evidence_id"])
    assert len(rows) == 1
    assert rows[0]["kind"] == ATTEMPT_CAT_QUERY_KIND
    assert ATTEMPT in rows[0]["subject_refs"]
    assert "cat-log://ATT-CAT-HARD" in rows[0]["subject_refs"]

    replay = service.query(
        mission_id=MISSION, task_id=TASK, worker_id="WORKER-ROTATED", attempt_id=ATTEMPT,
        target_id=TARGET, correlation=_scope(), failure_context=_failure(),
    )
    assert replay["replayed"] is True
    assert replay["evidence_id"] == result["evidence_id"]

    with pytest.raises(AttemptCatError, match="ATTEMPT_CAT_FAILURE_CONTEXT_LAYER_MISMATCH"):
        service.require_for_failure_context(
            mission_id=MISSION, task_id=TASK, worker_id="WORKER-EXEC", failure_context=_failure(layer="L5"),
        )


def test_not_dispatched_cannot_be_promoted_to_cat_required(tmp_path: Path, monkeypatch) -> None:
    truth = _truth(tmp_path)
    monkeypatch.setenv("PFC_RC7_BANK_SERVICE_PROVIDER_CONFIG", str(_provider(tmp_path)))
    service = AttemptCatQueryService(truth, tmp_path / "state")
    assert service.require_for_failure_context(
        mission_id=MISSION, task_id=TASK, worker_id="WORKER-EXEC", failure_context=_failure(state="NOT_DISPATCHED"),
    ) is None
    with pytest.raises(AttemptCatError, match="ATTEMPT_CAT_NOT_REQUIRED_FOR_CURRENT_FAILURE"):
        service.query(
            mission_id=MISSION, task_id=TASK, worker_id="WORKER-EXEC", attempt_id=ATTEMPT,
            target_id=TARGET, correlation=_scope(), failure_context=_failure(state="NOT_DISPATCHED"),
        )


def test_bank_execution_records_attempt_in_r1_before_diagnosis(tmp_path: Path) -> None:
    truth = TruthRuntime(tmp_path / "attempt-r1.jsonl")
    control = SimpleNamespace(truth=truth)
    bundle = SimpleNamespace(spec=SimpleNamespace(release_id=RELEASE, requirement_id="REQ-CAT-HARD"))
    record = SimpleNamespace(
        attempt_id=ATTEMPT, tc_id="TC-CAT-HARD", case_version=1, target_id=TARGET,
        layer="L4", status="FAIL", actual_result={"business_code": "BAD"},
        tool_call_refs=("browser-mcp://real-invocation",), evidence_refs=("EVD-REAL-EXECUTION",),
    )
    service = BankAttemptCatRuntimeExecutionService(evidence_root=str(tmp_path / "evidence"), state_root=str(tmp_path / "state"))
    service._record_current_attempt(control, bundle, record)
    rows = truth.query("execution_attempt", attempt_id=ATTEMPT)
    assert len(rows) == 1
    assert rows[0]["status"] == "FAIL"
    assert rows[0]["target_id"] == TARGET
    assert rows[0]["tool_call_refs"] == ["browser-mcp://real-invocation"]
    service._record_current_attempt(control, bundle, record)
    conflict = SimpleNamespace(**record.__dict__)
    conflict.actual_result = {"business_code": "DIFFERENT"}
    with pytest.raises(Exception, match="EXECUTION_ATTEMPT_R1_CONFLICT"):
        service._record_current_attempt(control, bundle, conflict)


def test_bank_cat_adapter_returns_r1_evidence_not_provider_self_report(tmp_path: Path, monkeypatch) -> None:
    truth = _truth(tmp_path)
    monkeypatch.setenv("PFC_RC7_BANK_SERVICE_PROVIDER_CONFIG", str(_provider(tmp_path)))
    control = SimpleNamespace(truth=truth, mission_id=MISSION)
    service = BankAttemptCatRuntimeExecutionService(evidence_root=str(tmp_path / "evidence"), state_root=str(tmp_path / "state"))
    callback = service._trusted_cat_query(control, task_id=TASK, runtime_worker_id="WORKER-EXEC")
    scope = CorrelationScope(applications=("cfg-center", "cfg-data"), window_start=100, window_end=160, trace_id="TRACE-CAT-HARD")
    context = SimpleNamespace(
        attempt_id=ATTEMPT, target_id=TARGET, layer="L4", real_action_executed=True,
        remote_integration=False, business_action_state="UNKNOWN",
    )
    result = callback(scope, context)
    assert result["tool_call_ref"] == "cat-tool://ATT-CAT-HARD"
    assert result["evidence_ref"].startswith("EVD-CATQ-")
    assert result["evidence_ref"] != "cat-provider-evidence://ATT-CAT-HARD"
