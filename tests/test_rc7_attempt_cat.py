from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import rc6_runtime.execution_overlay  # noqa: F401
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.attempt_cat import ATTEMPT_CAT_QUERY_KIND, AttemptCatError, AttemptCatQueryService
from rc7_runtime.models import Mission, Task, TaskStatus
from rc7_runtime.truth_overlay import append_entity, install_rc7_truth_overlay


MISSION = "MISSION-CAT"
RELEASE = "REL-CAT"
TASK = "TASK-EXECUTION"
ATTEMPT = "ATTEMPT-CAT-1"
TARGET = "TARGET-PFC"


def _truth(tmp_path: Path, *, layer: str = "L3") -> tuple[TruthRuntime, Path]:
    install_rc7_truth_overlay()
    path = tmp_path / "runtime-state" / "r1" / "event-stream.jsonl"
    truth = TruthRuntime(path)
    append_entity(truth, Mission(mission_id=MISSION, release_id=RELEASE, goal="CAT diagnosis"), release_id=RELEASE)
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
            "requirement_id": "REQ-1",
            "tc_id": "TC-1",
            "case_version": 1,
            "target_id": TARGET,
            "layer": layer,
            "status": "FAIL",
            "actual_result": {"http_status": 500},
            "tool_call_refs": ["api-runtime://APIREC-CAT-1"],
            "evidence_refs": ["evidence://runner/cat"],
        },
    )
    return truth, path


def _provider(tmp_path: Path, *, secret: bool = False) -> Path:
    script = tmp_path / "cat_provider.py"
    script.write_text(
        """
import json, sys
request = json.load(sys.stdin)
response = {
  "success": True,
  "target_verified": True,
  "tool_call_ref": "cat-tool://attempt-1",
  "evidence_ref": "cat-evidence://attempt-1",
  "cat_evidence_ref": "cat-log://attempt-1",
  "correlation_ref": "cat-correlation://request-1",
  "signals": {"ERROR": 3, "request_id": "REQ-CAT-1"}
}
if %s:
  response["token"] = "must-never-persist"
json.dump(response, sys.stdout)
""" % ("True" if secret else "False"),
        encoding="utf-8",
    )
    config = tmp_path / "bank-field-providers.json"
    config.write_text(
        json.dumps({"providers": {"BANK_CAT_QUERY": {"provider_id": "bank-cat-fixture", "command": [sys.executable, str(script)], "timeout_seconds": 30}}}),
        encoding="utf-8",
    )
    return config


def _scope() -> dict:
    return {"applications": ["cfg-center", "cfg-data"], "window_start": 100, "window_end": 160, "request_id": "REQ-CAT-1"}


def _failure(layer: str = "L3") -> dict:
    return {
        "attempt_id": ATTEMPT,
        "target_id": TARGET,
        "layer": layer,
        "real_action_executed": True,
        "remote_integration": False,
        "business_action_state": "DISPATCH_CONFIRMED",
        "correlation": _scope(),
    }


def test_attempt_cat_query_is_real_idempotent_and_attempt_scoped(tmp_path: Path, monkeypatch) -> None:
    truth, _ = _truth(tmp_path)
    monkeypatch.setenv("PFC_RC7_BANK_SERVICE_PROVIDER_CONFIG", str(_provider(tmp_path)))
    service = AttemptCatQueryService(truth, tmp_path / "state")
    first = service.query(
        mission_id=MISSION, task_id=TASK, worker_id="WORKER-DIAGNOSTIC", attempt_id=ATTEMPT,
        target_id=TARGET, correlation=_scope(), failure_context=_failure(),
    )
    assert first["status"] == "PASS"
    assert first["replayed"] is False
    assert first["signals"]["ERROR"] == 3
    second = service.query(
        mission_id=MISSION, task_id=TASK, worker_id="WORKER-DIAGNOSTIC-ROTATED", attempt_id=ATTEMPT,
        target_id=TARGET, correlation=_scope(), failure_context=_failure(),
    )
    assert second["status"] == "PASS"
    assert second["replayed"] is True
    assert second["evidence_id"] == first["evidence_id"]
    durable = service.require_for_failure_context(
        mission_id=MISSION, task_id=TASK, worker_id="WORKER-DIAGNOSTIC-ROTATED", failure_context=_failure(),
    )
    assert durable is not None
    assert durable["cat_required"] is True
    assert durable["cat_queried"] is True
    assert durable["cat_query_evidence_id"] == first["evidence_id"]
    rows = truth.query("rc7_evidence", evidence_id=first["evidence_id"])
    assert len(rows) == 1
    assert rows[0]["kind"] == ATTEMPT_CAT_QUERY_KIND
    assert ATTEMPT in rows[0]["subject_refs"]


def test_cat_scope_over_900_seconds_fails_closed_before_provider_call(tmp_path: Path, monkeypatch) -> None:
    truth, _ = _truth(tmp_path)
    monkeypatch.setenv("PFC_RC7_BANK_SERVICE_PROVIDER_CONFIG", str(_provider(tmp_path)))
    service = AttemptCatQueryService(truth, tmp_path / "state")
    scope = _scope()
    scope["window_end"] = 1200
    failure = _failure()
    failure["correlation"] = scope
    with pytest.raises(Exception, match="CAT_TIME_WINDOW_TOO_WIDE"):
        service.query(
            mission_id=MISSION, task_id=TASK, worker_id="WORKER-DIAGNOSTIC", attempt_id=ATTEMPT,
            target_id=TARGET, correlation=scope, failure_context=failure,
        )
    assert not [row for row in truth.query("rc7_evidence", mission_id=MISSION) if row.get("kind") == ATTEMPT_CAT_QUERY_KIND]


def test_cat_provider_secret_is_rejected_before_state_or_r1_persistence(tmp_path: Path, monkeypatch) -> None:
    truth, _ = _truth(tmp_path)
    monkeypatch.setenv("PFC_RC7_BANK_SERVICE_PROVIDER_CONFIG", str(_provider(tmp_path, secret=True)))
    state = tmp_path / "state"
    service = AttemptCatQueryService(truth, state)
    with pytest.raises(AttemptCatError, match="SECRET_FIELD_FORBIDDEN"):
        service.query(
            mission_id=MISSION, task_id=TASK, worker_id="WORKER-DIAGNOSTIC", attempt_id=ATTEMPT,
            target_id=TARGET, correlation=_scope(), failure_context=_failure(),
        )
    assert not [row for row in truth.query("rc7_evidence", mission_id=MISSION) if row.get("kind") == ATTEMPT_CAT_QUERY_KIND]
    assert not list((state / "attempt-cat").rglob("*.json")) if (state / "attempt-cat").exists() else True
