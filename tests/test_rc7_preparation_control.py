from __future__ import annotations

from pathlib import Path

import pytest

from rc6_runtime.preparation import PreparationContractError
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.models import Mission, Task, TaskStatus
from rc7_runtime.preparation_control import RuntimePreparationError, RuntimePreparationService


MISSION = "MISSION-PREP-R1"
TASK = "TASK-EXEC-PREP-R1"
TARGET = "TARGET-PREP-R1"


def _case():
    return {
        "tc_id": "TC-PREP-R1",
        "case_version": 3,
        "layer": "L3",
        "status": "FROZEN",
        "preconditions": [
            {"id": "PRE-ENV", "type": "ENVIRONMENT", "requirement": "target environment reachable"},
            {"id": "PRE-AUTH", "type": "AUTH", "requirement": "4A session valid"},
        ],
        "test_data": {
            "initial_state": [
                {
                    "id": "STATE-LOAN",
                    "selectors": {"loan_status": "DRAFT"},
                    "allowed_strategies": ["REUSE_EXISTING", "API_CREATE"],
                }
            ],
            "input_data": [
                {
                    "id": "INPUT-AMOUNT",
                    "selectors": {"amount": 1000},
                    "allowed_strategies": ["DERIVE"],
                }
            ],
            "cleanup_policy": {"mode": "ROLLBACK", "scope": "created-only"},
        },
        "oracle": {
            "checks": [
                {
                    "id": "CHK-1",
                    "type": "BUSINESS_RULE",
                    "actual_path": "business_code",
                    "operator": "EQ",
                    "expected": "OK",
                }
            ]
        },
    }


def _control(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=MISSION,
            release_id="RC7-PREP-R1",
            goal="prove preparation is runtime-owned durable truth",
        ),
    )
    control.register_task(
        Task(
            task_id=TASK,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="EXECUTE",
            objective="prepare and execute one governed case",
            required_capabilities=["test_execution"],
        )
    )
    assert control.scheduler.task(TASK).state == TaskStatus.READY
    return truth, control


def _providers(order):
    def resolver(spec, context):
        order.append(spec["id"])
        return {
            "success": True,
            "evidence_ref": "evidence://pre/%s/%s" % (spec["id"], context["attempt_id"]),
        }

    def reuse(req, context):
        order.append("REUSE_EXISTING")
        return {
            "success": True,
            "binding": {"loan_id": "L-100"},
            "tool_call_ref": "toolcall://db/search/L-100",
            "evidence_ref": "evidence://db/search/L-100",
        }

    def derive(req, context):
        order.append("DERIVE")
        return {
            "success": True,
            "binding": {"amount": 1000},
            "tool_call_ref": "toolcall://derive/amount",
            "evidence_ref": "evidence://derive/amount",
        }

    def verify(req, binding, context):
        order.append("VERIFY-" + req["id"])
        return {
            "success": True,
            "evidence_ref": "evidence://verify/%s" % req["id"],
        }

    return {
        "precondition_resolvers": {"ENVIRONMENT": resolver, "AUTH": resolver},
        "data_strategies": {"REUSE_EXISTING": reuse, "DERIVE": derive},
        "data_verifier": verify,
    }


def test_runtime_preparation_persists_preconditions_data_verification_and_prepared_artifact(tmp_path: Path):
    truth, control = _control(tmp_path)
    order = []
    result = RuntimePreparationService(evidence_root=str(tmp_path / "evidence")).prepare(
        control,
        TASK,
        case=_case(),
        attempt_id="ATT-PREP-1",
        target_id=TARGET,
        **_providers(order),
    )

    assert result.prepared.status == "PREPARED"
    assert result.prepared.initial_state_bindings["STATE-LOAN"]["loan_id"] == "L-100"
    assert result.prepared.input_data_bindings["INPUT-AMOUNT"]["amount"] == 1000
    assert order[:2] == ["PRE-ENV", "PRE-AUTH"]
    assert order.index("REUSE_EXISTING") < order.index("VERIFY-STATE-LOAN")
    assert order.index("DERIVE") < order.index("VERIFY-INPUT-AMOUNT")

    artifacts = truth.query("rc7_artifact", artifact_id=result.artifact_id)
    assert len(artifacts) == 1
    assert artifacts[0]["artifact_type_name"] == "PREPARED_ATTEMPT"
    assert artifacts[0]["content_hash"] == result.content_hash
    assert set(artifacts[0]["evidence_refs"]) == set(result.evidence_ids)

    evidence = [truth.query("rc7_evidence", evidence_id=evidence_id)[0] for evidence_id in result.evidence_ids]
    kinds = {row["kind"] for row in evidence}
    assert "PRECONDITION_EVIDENCE" in kinds
    assert "PREPARATION_BINDING_EVIDENCE" in kinds
    assert "RUNTIME_PREPARATION_RECORD" in kinds
    record = [row for row in evidence if row["kind"] == "RUNTIME_PREPARATION_RECORD"]
    assert len(record) == 1
    assert record[0]["content_hash"] == result.content_hash


def test_same_attempt_rehydrates_from_r1_without_rerunning_providers(tmp_path: Path):
    truth, control = _control(tmp_path)
    first_calls = []
    first = RuntimePreparationService(evidence_root=str(tmp_path / "evidence")).prepare(
        control,
        TASK,
        case=_case(),
        attempt_id="ATT-PREP-REPLAY",
        target_id=TARGET,
        **_providers(first_calls),
    )
    assert first_calls

    def forbidden(*args, **kwargs):
        raise AssertionError("provider must not run during R1 rehydrate")

    second = RuntimePreparationService(evidence_root=str(tmp_path / "evidence")).prepare(
        control,
        TASK,
        case=_case(),
        attempt_id="ATT-PREP-REPLAY",
        target_id=TARGET,
        precondition_resolvers={"ENVIRONMENT": forbidden, "AUTH": forbidden},
        data_strategies={"REUSE_EXISTING": forbidden, "DERIVE": forbidden},
        data_verifier=forbidden,
    )
    assert second == first
    assert len(truth.query("rc7_artifact", artifact_id=first.artifact_id)) == 1
    for evidence_id in first.evidence_ids:
        assert len(truth.query("rc7_evidence", evidence_id=evidence_id)) == 1


def test_attempt_id_cannot_be_reused_for_different_case_or_target(tmp_path: Path):
    _, control = _control(tmp_path)
    service = RuntimePreparationService(evidence_root=str(tmp_path / "evidence"))
    service.prepare(
        control,
        TASK,
        case=_case(),
        attempt_id="ATT-PREP-IMMUTABLE",
        target_id=TARGET,
        **_providers([]),
    )

    with pytest.raises(RuntimePreparationError, match="ATTEMPT_TARGET_IMMUTABILITY_VIOLATION"):
        service.prepare(
            control,
            TASK,
            case=_case(),
            attempt_id="ATT-PREP-IMMUTABLE",
            target_id="TARGET-OTHER",
            **_providers([]),
        )

    changed = _case()
    changed["case_version"] = 4
    with pytest.raises(RuntimePreparationError, match="ATTEMPT_CASE_IMMUTABILITY_VIOLATION"):
        service.prepare(
            control,
            TASK,
            case=changed,
            attempt_id="ATT-PREP-IMMUTABLE",
            target_id=TARGET,
            **_providers([]),
        )


def test_db_create_still_requires_explicit_human_gate_and_leaves_no_prepared_artifact(tmp_path: Path):
    truth, control = _control(tmp_path)
    case = _case()
    case["test_data"]["initial_state"][0]["allowed_strategies"] = ["DB_CREATE"]

    def resolver(spec, context):
        return {"success": True, "evidence_ref": "evidence://pre/%s" % spec["id"]}

    def db_create(req, context):
        return {
            "success": True,
            "binding": {"loan_id": "L-DB"},
            "tool_call_ref": "toolcall://db/create/L-DB",
            "evidence_ref": "evidence://db/create/L-DB",
        }

    def derive(req, context):
        return {
            "success": True,
            "binding": {"amount": 1000},
            "tool_call_ref": "toolcall://derive/amount",
            "evidence_ref": "evidence://derive/amount",
        }

    def verify(req, binding, context):
        return {"success": True, "evidence_ref": "evidence://verify/%s" % req["id"]}

    with pytest.raises(PreparationContractError, match="HUMAN_GATE_REQUIRED:STATE-LOAN:DB_CREATE"):
        RuntimePreparationService(evidence_root=str(tmp_path / "evidence")).prepare(
            control,
            TASK,
            case=case,
            attempt_id="ATT-PREP-DB",
            target_id=TARGET,
            precondition_resolvers={"ENVIRONMENT": resolver, "AUTH": resolver},
            data_strategies={"DB_CREATE": db_create, "DERIVE": derive},
            data_verifier=verify,
        )

    artifact_id_prefix = "ART-PREPARED-"
    assert not any(
        str(row.get("artifact_id", "")).startswith(artifact_id_prefix)
        for row in truth.query("rc7_artifact", mission_id=MISSION)
    )
