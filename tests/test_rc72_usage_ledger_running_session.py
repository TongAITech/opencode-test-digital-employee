from pathlib import Path

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_domain import AutonomousMissionNode, MissionNodeRecord
from rc7_runtime.rc72_model_usage import install_rc72_token_usage_overlay
from rc7_runtime.rc72_truth import append_rc72_entity, install_rc72_truth_overlay
from rc7_runtime.rc72_usage_ledger import UsageLedgerService, install_rc72_usage_ledger_overlay
from rc7_runtime.rc72_worker_lifecycle import install_rc72_worker_lifecycle_overlay


RELEASE = "RC7.2"
MISSION = "M-LEDGER-RUNNING"


def _truth(tmp_path: Path) -> TruthRuntime:
    install_rc72_truth_overlay()
    install_rc72_worker_lifecycle_overlay()
    install_rc72_token_usage_overlay()
    install_rc72_usage_ledger_overlay()
    return TruthRuntime(tmp_path / "r1.jsonl")


def _append_runtime_lineage(truth: TruthRuntime, binding_session_id: str) -> None:
    append_rc72_entity(
        truth,
        MissionNodeRecord(
            mission_node_id="MN-N7",
            mission_id=MISSION,
            node_type=AutonomousMissionNode.N7_EXECUTION,
            scope_ref="release-batch://RB-1",
        ),
        release_id=RELEASE,
    )
    truth.append_atomic(
        "RC72_WORKITEM_ATTEMPT_BINDING_UPSERTED",
        {
            "binding_id": "BIND-1",
            "release_id": RELEASE,
            "mission_id": MISSION,
            "etu_id": "ETU-1",
            "workitem_id": "WI-1",
            "case_id": "TC-1",
            "attempt_id": "ATT-1",
            "state": "RUNNING",
            "worker_id": "WRK-1",
            "session_id": binding_session_id,
            "task_lease_ref": "LEASE-1",
            "capability_lease_refs": [],
            "resource_lease_refs": [],
            "parent_attempt_id": None,
            "mission_node_id": "MN-N7",
            "mission_node_type": "N7_EXECUTION",
            "mission_node_lineage_status": "RESOLVED",
            "mission_node_lineage_reason": None,
            "created_at": 1,
            "updated_at": 2,
            "artifact_version": 1,
        },
    )
    truth.append_atomic(
        "RC72_WORKER_SESSION_UPSERTED",
        {
            "session_id": "SES-LIFECYCLE-1",
            "release_id": RELEASE,
            "mission_id": MISSION,
            "worker_id": "WRK-1",
            "release_batch_id": "RB-1",
            "team_id": "TEAM-1",
            "role": "EXECUTOR",
            "purpose": "EXECUTION",
            "etu_id": "ETU-1",
            "workitem_id": "WI-1",
            "state": "ACTIVE",
            "context_bundle": {
                "mission_id": MISSION,
                "release_batch_id": "RB-1",
                "team_id": "TEAM-1",
                "role": "EXECUTOR",
                "etu_id": "ETU-1",
                "workitem_id": "WI-1",
                "etu_refs": ["ETU-1"],
                "executable_contract_refs": [],
                "data_refs": [],
                "evidence_refs": [],
                "gap_refs": [],
                "coverage_refs": [],
                "lease_refs": ["LEASE-1"],
            },
            "parent_session_id": None,
            "checkpoint_id": None,
            "close_reason": None,
            "runtime_worker_id": "WRK-1",
            "runtime_assignment_id": "ASN-1",
            "task_lease_ref": "LEASE-1",
            "runtime_attempt_id": "ATT-1",
            "dsh_session_id": "DSH-1",
            "binding_id": "BIND-1",
            "created_at": 1,
            "closed_at": None,
            "artifact_version": 1,
        },
    )
    truth.append_atomic(
        "RC72_TOKEN_USAGE_OBSERVED",
        {
            "token_usage_id": "USE-1",
            "release_id": RELEASE,
            "mission_id": MISSION,
            "attempt_id": "ATT-1",
            "assignment_id": "ASN-1",
            "dsh_session_id": "DSH-1",
            "raw_output_ref": "raw://1",
            "observation_status": "OBSERVED",
            "input_tokens": 30,
            "output_tokens": 10,
            "total_tokens": 40,
            "cached_input_tokens": None,
            "cache_read_tokens": None,
            "cache_write_tokens": None,
            "provider": "bank-provider",
            "model": "bank-model",
            "usage_source_path": "event[0].usage",
            "usage_candidate_count": 1,
            "unknown_reason": None,
            "observation_sha256": "sha-running",
            "recorded_at": 2,
            "artifact_version": 1,
        },
    )


def test_running_binding_accepts_recorded_dsh_session_as_canonical_lineage(tmp_path: Path) -> None:
    truth = _truth(tmp_path)
    _append_runtime_lineage(truth, "DSH-1")

    ledger = UsageLedgerService(truth, release_id=RELEASE).build(mission_id=MISSION)

    assert ledger["status"] == "MEASURED"
    assert ledger["resolved_lineage_count"] == 1
    assert ledger["unresolved_lineage_count"] == 0
    assert ledger["node_summaries"][0]["mission_node_type"] == "N7_EXECUTION"
    assert ledger["receipts"][0]["lifecycle_session_id"] == "SES-LIFECYCLE-1"
    assert ledger["receipts"][0]["dsh_session_id"] == "DSH-1"


def test_binding_session_outside_lifecycle_and_recorded_dsh_remains_unresolved(tmp_path: Path) -> None:
    truth = _truth(tmp_path)
    _append_runtime_lineage(truth, "DSH-WRONG")

    ledger = UsageLedgerService(truth, release_id=RELEASE).build(mission_id=MISSION)

    assert ledger["status"] == "PARTIAL"
    assert ledger["resolved_lineage_count"] == 0
    assert ledger["unresolved_lineage_count"] == 1
    assert ledger["unresolved_lineages"][0]["reason"] == "WORKITEM_BINDING_SESSION_MISMATCH"
    assert ledger["node_summaries"] == []
