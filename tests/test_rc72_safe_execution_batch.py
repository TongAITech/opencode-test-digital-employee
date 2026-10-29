from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_context_economy import (
    ContextAffinity,
    ExecutionBatchPlanner,
    ExecutionMode,
    SemanticWorkDescriptor,
)
from rc7_runtime.rc72_model_economy import MissionCriticality, SemanticCostClass
from rc7_runtime.rc72_safe_execution_batch import (
    ExecutionBatchMemberResult,
    SafeExecutionBatchService,
    install_rc72_safe_execution_batch_overlay,
)
from rc7_runtime.rc72_truth import install_rc72_truth_overlay


RELEASE = "RC7.2"
MISSION = "M-SAFE-BATCH"


def _truth(tmp_path: Path) -> TruthRuntime:
    tmp_path.mkdir(parents=True, exist_ok=True)
    install_rc72_truth_overlay()
    install_rc72_safe_execution_batch_overlay()
    return TruthRuntime(tmp_path / "r1.jsonl")


def _descriptor(workitem_id: str, *, sst: str = "SST-1") -> SemanticWorkDescriptor:
    return SemanticWorkDescriptor(
        workitem_id=workitem_id,
        mission_id=MISSION,
        node="EXECUTION",
        stage="N7",
        execution_mode=ExecutionMode.SEMANTIC,
        mission_criticality=MissionCriticality.BLOCKING,
        semantic_cost_class=SemanticCostClass.HIGH,
        affinity=ContextAffinity(
            requirement_id="REQ-1",
            sst_id=sst,
            service="cfg-scd",
            environment="FAT1",
            data_domain="loan",
            oracle_family="api-db",
            tool_family="dsh-agent-teams",
        ),
        input_refs=("ART-SHARED", "CASE-" + workitem_id),
    )


def _batch(*workitems: str):
    plan = ExecutionBatchPlanner(max_batch_size=8).plan([_descriptor(value) for value in workitems])
    assert len(plan.batches) == 1
    return plan.batches[0]


def _binding(
    truth: TruthRuntime,
    *,
    workitem_id: str,
    attempt_id: str,
    binding_id: str,
    node_id: str = "MN-N7",
    node_type: str = "N7_EXECUTION",
    lineage_status: str = "RESOLVED",
):
    truth.append_atomic(
        "RC72_WORKITEM_ATTEMPT_BINDING_UPSERTED",
        {
            "binding_id": binding_id,
            "release_id": RELEASE,
            "mission_id": MISSION,
            "etu_id": "ETU-" + workitem_id,
            "workitem_id": workitem_id,
            "case_id": "CASE-" + workitem_id,
            "attempt_id": attempt_id,
            "state": "RESERVED",
            "worker_id": None,
            "session_id": None,
            "task_lease_ref": None,
            "capability_lease_refs": [],
            "resource_lease_refs": [],
            "parent_attempt_id": None,
            "mission_node_id": node_id if lineage_status == "RESOLVED" else None,
            "mission_node_type": node_type if lineage_status == "RESOLVED" else None,
            "mission_node_lineage_status": lineage_status,
            "mission_node_lineage_reason": None if lineage_status == "RESOLVED" else "FIXTURE_UNRESOLVED",
            "created_at": 1,
            "updated_at": 1,
            "artifact_version": 1,
        },
    )


def test_safe_batch_admission_requires_independent_canonical_attempts_and_persists_r1(tmp_path: Path):
    truth = _truth(tmp_path)
    _binding(truth, workitem_id="WI-1", attempt_id="ATT-1", binding_id="BIND-1")
    _binding(truth, workitem_id="WI-2", attempt_id="ATT-2", binding_id="BIND-2")
    batch = _batch("WI-1", "WI-2")

    receipt = SafeExecutionBatchService(truth, release_id=RELEASE).admit(
        batch,
        attempt_ids_by_workitem={"WI-1": "ATT-1", "WI-2": "ATT-2"},
    )

    assert receipt["state"] == "ADMITTED"
    assert receipt["batch_id"] == batch.batch_id
    assert receipt["context_sha256"] == batch.context_envelope.context_sha256
    assert receipt["mission_node_id"] == "MN-N7"
    assert receipt["mission_node_type"] == "N7_EXECUTION"
    assert [(item["workitem_id"], item["attempt_id"]) for item in receipt["members"]] == [
        ("WI-1", "ATT-1"),
        ("WI-2", "ATT-2"),
    ]
    assert len(truth.query("rc72_execution_batch_receipt", batch_receipt_id=receipt["batch_receipt_id"])) == 1


def test_safe_batch_rejects_shared_attempt_identity(tmp_path: Path):
    truth = _truth(tmp_path)
    _binding(truth, workitem_id="WI-1", attempt_id="ATT-SHARED", binding_id="BIND-1")
    _binding(truth, workitem_id="WI-2", attempt_id="ATT-SHARED", binding_id="BIND-2")

    with pytest.raises(ContractError, match="ATTEMPTS_MUST_BE_INDEPENDENT"):
        SafeExecutionBatchService(truth, release_id=RELEASE).admit(
            _batch("WI-1", "WI-2"),
            attempt_ids_by_workitem={"WI-1": "ATT-SHARED", "WI-2": "ATT-SHARED"},
        )


def test_safe_batch_rejects_unresolved_or_cross_node_lineage_instead_of_guessing(tmp_path: Path):
    truth = _truth(tmp_path)
    _binding(
        truth,
        workitem_id="WI-1",
        attempt_id="ATT-1",
        binding_id="BIND-1",
        lineage_status="UNRESOLVED",
    )
    _binding(truth, workitem_id="WI-2", attempt_id="ATT-2", binding_id="BIND-2")
    service = SafeExecutionBatchService(truth, release_id=RELEASE)
    with pytest.raises(ContractError, match="CANONICAL_NODE_UNRESOLVED"):
        service.admit(
            _batch("WI-1", "WI-2"),
            attempt_ids_by_workitem={"WI-1": "ATT-1", "WI-2": "ATT-2"},
        )

    truth2 = _truth(tmp_path / "other")
    _binding(truth2, workitem_id="WI-1", attempt_id="ATT-1", binding_id="BIND-1", node_id="MN-N7")
    _binding(
        truth2,
        workitem_id="WI-2",
        attempt_id="ATT-2",
        binding_id="BIND-2",
        node_id="MN-N8",
        node_type="N8_DIAGNOSIS",
    )
    with pytest.raises(ContractError, match="CROSS_CANONICAL_NODE_FORBIDDEN"):
        SafeExecutionBatchService(truth2, release_id=RELEASE).admit(
            _batch("WI-1", "WI-2"),
            attempt_ids_by_workitem={"WI-1": "ATT-1", "WI-2": "ATT-2"},
        )


def test_batch_results_must_be_exactly_separable_per_workitem_attempt(tmp_path: Path):
    truth = _truth(tmp_path)
    _binding(truth, workitem_id="WI-1", attempt_id="ATT-1", binding_id="BIND-1")
    _binding(truth, workitem_id="WI-2", attempt_id="ATT-2", binding_id="BIND-2")
    service = SafeExecutionBatchService(truth, release_id=RELEASE)
    receipt = service.admit(
        _batch("WI-1", "WI-2"),
        attempt_ids_by_workitem={"WI-1": "ATT-1", "WI-2": "ATT-2"},
    )

    with pytest.raises(ContractError, match="RESULTS_NOT_EXACT"):
        service.record_results(
            receipt["batch_receipt_id"],
            [
                ExecutionBatchMemberResult(
                    workitem_id="WI-1",
                    attempt_id="ATT-1",
                    actual_result_ref="RESULT-WI-1",
                    assertion_result="PASS",
                    evidence_refs=("EVD-WI-1",),
                )
            ],
        )

    recorded = service.record_results(
        receipt["batch_receipt_id"],
        [
            ExecutionBatchMemberResult(
                workitem_id="WI-1",
                attempt_id="ATT-1",
                actual_result_ref="RESULT-WI-1",
                assertion_result="PASS",
                evidence_refs=("EVD-WI-1",),
            ),
            ExecutionBatchMemberResult(
                workitem_id="WI-2",
                attempt_id="ATT-2",
                actual_result_ref="RESULT-WI-2",
                assertion_result="FAIL",
                evidence_refs=("EVD-WI-2",),
                gap_refs=("GAP-WI-2",),
            ),
        ],
    )
    assert recorded["state"] == "RESULTS_RECORDED"
    assert recorded["result_count"] == 2
    assert recorded["results"][0]["assertion_result"] == "PASS"
    assert recorded["results"][0]["gap_refs"] == []
    assert recorded["results"][1]["assertion_result"] == "FAIL"
    assert recorded["results"][1]["gap_refs"] == ["GAP-WI-2"]


def test_failed_sibling_does_not_rewrite_pass_sibling_or_batch_business_state(tmp_path: Path):
    truth = _truth(tmp_path)
    _binding(truth, workitem_id="WI-1", attempt_id="ATT-1", binding_id="BIND-1")
    _binding(truth, workitem_id="WI-2", attempt_id="ATT-2", binding_id="BIND-2")
    service = SafeExecutionBatchService(truth, release_id=RELEASE)
    receipt = service.admit(
        _batch("WI-1", "WI-2"),
        attempt_ids_by_workitem={"WI-1": "ATT-1", "WI-2": "ATT-2"},
    )
    recorded = service.record_results(
        receipt["batch_receipt_id"],
        [
            ExecutionBatchMemberResult("WI-1", "ATT-1", "RESULT-1", "PASS", ("EVD-1",)),
            ExecutionBatchMemberResult("WI-2", "ATT-2", "RESULT-2", "FAIL", ("EVD-2",), ("GAP-2",)),
        ],
    )
    assert [result["assertion_result"] for result in recorded["results"]] == ["PASS", "FAIL"]
    bindings = truth.query("rc72_workitem_attempt_binding", mission_id=MISSION)
    assert {row["workitem_id"]: row["state"] for row in bindings} == {"WI-1": "RESERVED", "WI-2": "RESERVED"}
