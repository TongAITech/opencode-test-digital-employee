from pathlib import Path

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_domain import AutonomousMissionNode, MissionNodeRecord
from rc7_runtime.rc72_model_usage import install_rc72_token_usage_overlay
from rc7_runtime.rc72_truth import append_rc72_entity, install_rc72_truth_overlay
from rc7_runtime.rc72_usage_ledger import UsageLedgerService, install_rc72_usage_ledger_overlay
from rc7_runtime.rc72_worker_lifecycle import install_rc72_worker_lifecycle_overlay


RELEASE = "RC7.2"
MISSION = "M-LEDGER"


def _truth(tmp_path: Path) -> TruthRuntime:
    install_rc72_truth_overlay()
    install_rc72_worker_lifecycle_overlay()
    install_rc72_token_usage_overlay()
    install_rc72_usage_ledger_overlay()
    return TruthRuntime(tmp_path / "r1.jsonl")


def _append_node(truth: TruthRuntime) -> None:
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


def _append_lineage(truth: TruthRuntime, suffix: str) -> None:
    attempt_id = "ATT-" + suffix
    assignment_id = "ASN-" + suffix
    binding_id = "BIND-" + suffix
    session_id = "SES-" + suffix
    worker_id = "WRK-" + suffix
    truth.append_atomic(
        "RC72_WORKITEM_ATTEMPT_BINDING_UPSERTED",
        {
            "binding_id": binding_id,
            "release_id": RELEASE,
            "mission_id": MISSION,
            "etu_id": "ETU-1",
            "workitem_id": "WI-1",
            "case_id": "TC-1",
            "attempt_id": attempt_id,
            "state": "PREPARED",
            "worker_id": worker_id,
            "session_id": session_id,
            "task_lease_ref": "LEASE-" + suffix,
            "capability_lease_refs": [],
            "resource_lease_refs": [],
            "parent_attempt_id": None,
            "mission_node_id": "MN-N7",
            "mission_node_type": "N7_EXECUTION",
            "mission_node_lineage_status": "RESOLVED",
            "mission_node_lineage_reason": None,
            "created_at": 1,
            "updated_at": 1,
            "artifact_version": 1,
        },
    )
    truth.append_atomic(
        "RC72_WORKER_SESSION_UPSERTED",
        {
            "session_id": session_id,
            "release_id": RELEASE,
            "mission_id": MISSION,
            "worker_id": worker_id,
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
                "lease_refs": ["LEASE-" + suffix],
            },
            "parent_session_id": None,
            "checkpoint_id": None,
            "close_reason": None,
            "runtime_worker_id": worker_id,
            "runtime_assignment_id": assignment_id,
            "task_lease_ref": "LEASE-" + suffix,
            "runtime_attempt_id": attempt_id,
            "dsh_session_id": "DSH-" + suffix,
            "binding_id": binding_id,
            "created_at": 1,
            "closed_at": None,
            "artifact_version": 1,
        },
    )


def _append_observed_usage(truth: TruthRuntime, suffix: str, *, input_tokens: int = 100, output_tokens: int = 20) -> None:
    truth.append_atomic(
        "RC72_TOKEN_USAGE_OBSERVED",
        {
            "token_usage_id": "USE-" + suffix,
            "release_id": RELEASE,
            "mission_id": MISSION,
            "attempt_id": "ATT-" + suffix,
            "assignment_id": "ASN-" + suffix,
            "dsh_session_id": "DSH-" + suffix,
            "raw_output_ref": "raw://" + suffix,
            "observation_status": "OBSERVED",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "cached_input_tokens": None,
            "cache_read_tokens": None,
            "cache_write_tokens": None,
            "provider": "bank-provider",
            "model": "bank-model",
            "usage_source_path": "event[0].usage",
            "usage_candidate_count": 1,
            "unknown_reason": None,
            "observation_sha256": "sha-" + suffix,
            "recorded_at": 1,
            "artifact_version": 1,
        },
    )


def _append_unknown_usage(truth: TruthRuntime, suffix: str) -> None:
    truth.append_atomic(
        "RC72_TOKEN_USAGE_OBSERVED",
        {
            "token_usage_id": "USE-" + suffix,
            "release_id": RELEASE,
            "mission_id": MISSION,
            "attempt_id": "ATT-" + suffix,
            "assignment_id": "ASN-" + suffix,
            "dsh_session_id": "DSH-" + suffix,
            "raw_output_ref": "raw://" + suffix,
            "observation_status": "UNKNOWN",
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "cached_input_tokens": None,
            "cache_read_tokens": None,
            "cache_write_tokens": None,
            "provider": None,
            "model": None,
            "usage_source_path": None,
            "usage_candidate_count": 0,
            "unknown_reason": "TOKEN_USAGE_NOT_EXPOSED_BY_DSH_JSONL",
            "observation_sha256": None,
            "recorded_at": 1,
            "artifact_version": 1,
        },
    )


def test_measured_usage_aggregates_through_assignment_session_binding_and_n_node(tmp_path: Path) -> None:
    truth = _truth(tmp_path)
    _append_node(truth)
    _append_lineage(truth, "1")
    _append_observed_usage(truth, "1")

    ledger = UsageLedgerService(truth, release_id=RELEASE).build(mission_id=MISSION)

    assert ledger["status"] == "MEASURED"
    assert ledger["source_usage_count"] == 1
    assert ledger["resolved_lineage_count"] == 1
    assert ledger["unresolved_lineage_count"] == 0
    assert ledger["tokens"]["input_tokens"] == 100
    assert ledger["tokens"]["output_tokens"] == 20
    assert ledger["tokens"]["total_tokens"] == 120
    assert ledger["tokens"]["cache_read_tokens"] is None
    assert ledger["counter_observation_counts"]["cache_read_tokens"] == 0
    assert ledger["node_summaries"][0]["mission_node_id"] == "MN-N7"
    assert ledger["node_summaries"][0]["mission_node_type"] == "N7_EXECUTION"
    assert ledger["workitem_summaries"][0]["workitem_id"] == "WI-1"
    assert ledger["attempt_summaries"][0]["attempt_id"] == "ATT-1"
    assert ledger["receipts"][0]["provider"] == "bank-provider"
    assert ledger["receipts"][0]["lifecycle_session_id"] == "SES-1"


def test_unknown_usage_remains_unknown_and_never_becomes_zero(tmp_path: Path) -> None:
    truth = _truth(tmp_path)
    _append_node(truth)
    _append_lineage(truth, "1")
    _append_unknown_usage(truth, "1")

    ledger = UsageLedgerService(truth, release_id=RELEASE).build(mission_id=MISSION)

    assert ledger["status"] == "UNKNOWN"
    assert ledger["measured_usage_count"] == 0
    assert ledger["unknown_usage_count"] == 1
    assert ledger["resolved_lineage_count"] == 1
    for value in ledger["tokens"].values():
        assert value is None
    for value in ledger["counter_observation_counts"].values():
        assert value == 0
    assert ledger["node_summaries"][0]["unknown_call_count"] == 1
    assert ledger["node_summaries"][0]["tokens"]["total_tokens"] is None


def test_missing_canonical_session_surfaces_unresolved_lineage_without_fake_n_attribution(tmp_path: Path) -> None:
    truth = _truth(tmp_path)
    _append_node(truth)
    _append_observed_usage(truth, "ORPHAN")

    ledger = UsageLedgerService(truth, release_id=RELEASE).build(mission_id=MISSION)

    assert ledger["status"] == "PARTIAL"
    assert ledger["measured_usage_count"] == 1
    assert ledger["resolved_lineage_count"] == 0
    assert ledger["unresolved_lineage_count"] == 1
    assert ledger["node_summaries"] == []
    assert ledger["workitem_summaries"] == []
    assert ledger["attempt_summaries"] == []
    assert ledger["unresolved_lineages"] == [
        {
            "token_usage_id": "USE-ORPHAN",
            "assignment_id": "ASN-ORPHAN",
            "reason": "WORKER_SESSION_NOT_UNIQUE:0",
        }
    ]


def test_mixed_measured_and_unknown_usage_is_partial_but_sums_only_observed_counters(tmp_path: Path) -> None:
    truth = _truth(tmp_path)
    _append_node(truth)
    _append_lineage(truth, "1")
    _append_lineage(truth, "2")
    _append_observed_usage(truth, "1", input_tokens=40, output_tokens=10)
    _append_unknown_usage(truth, "2")

    service = UsageLedgerService(truth, release_id=RELEASE)
    first = service.build(mission_id=MISSION)
    second = service.build(mission_id=MISSION)

    assert first["status"] == "PARTIAL"
    assert first["source_usage_count"] == 2
    assert first["measured_usage_count"] == 1
    assert first["unknown_usage_count"] == 1
    assert first["tokens"]["total_tokens"] == 50
    assert first["counter_observation_counts"]["total_tokens"] == 1
    assert first["node_summaries"][0]["call_count"] == 2
    assert first["node_summaries"][0]["unknown_call_count"] == 1
    assert second["artifact_version"] == first["artifact_version"]
    assert second["source_digest"] == first["source_digest"]
