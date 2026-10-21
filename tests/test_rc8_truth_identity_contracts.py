from __future__ import annotations

import pytest

from rc8_runtime import (
    ArtifactAvailability,
    CapabilityQualification,
    CapabilityState,
    CompletionClaim,
    EvidenceManifest,
    NodeIdentity,
    ProductionBatch,
    RC8ContractError,
    RequirementDeliveryScope,
    RuntimeEventEnvelope,
    RuntimeProducerKind,
    TestRunIdentity,
    WorkItemIdentity,
    require_pass_evidence,
    transition_capability,
)


def _evidence(*, availability=ArtifactAvailability.AVAILABLE, assertions=None):
    return EvidenceManifest(
        artifact_id="ART-1",
        test_run_id="RUN-1",
        work_item_id="WI-1",
        node_id="NODE-1",
        kind="API_RESPONSE",
        producer_kind=RuntimeProducerKind.TOOL,
        producer_ref="api-runner",
        source_tool="api-runner",
        content_ref="artifact://ART-1",
        sha256="a" * 64,
        size_bytes=42,
        availability=availability,
        assertion_refs=list(assertions or []),
        runtime_event_refs=["EV-1"],
    )


def test_windows_node_requires_git_bash_and_linux_requires_bash() -> None:
    windows = NodeIdentity(
        node_id="NODE-WIN",
        operator_ref="tester-a",
        os_family="windows",
        architecture="x86_64",
        shell="git-bash",
    )
    linux = NodeIdentity(
        node_id="NODE-LINUX",
        operator_ref="tester-b",
        os_family="linux",
        architecture="aarch64",
        shell="bash",
    )
    assert windows.shell == "git-bash"
    assert linux.shell == "bash"

    with pytest.raises(RC8ContractError, match="WINDOWS_NODE_REQUIRES_GIT_BASH"):
        NodeIdentity(
            node_id="NODE-BAD",
            operator_ref="tester",
            os_family="windows",
            architecture="x86_64",
            shell="cmd",
        )


def test_requirement_delivery_scope_allows_one_requirement_to_span_multiple_apps_and_versions() -> None:
    ProductionBatch("PB-1", "2026-10-30", "20261030-01")
    scope_a = RequirementDeliveryScope(
        delivery_scope_id="SCOPE-A",
        production_batch_id="PB-1",
        requirement_id="REQ-320",
        system_version_id="BLOAN-PF1.3.0",
        application_id="cfg-data",
        sst_id="SST-A",
    )
    scope_b = RequirementDeliveryScope(
        delivery_scope_id="SCOPE-B",
        production_batch_id="PB-1",
        requirement_id="REQ-320",
        system_version_id="RULE-PF2.4.0",
        application_id="rule-center",
        sst_id="SST-B",
    )
    assert scope_a.requirement_id == scope_b.requirement_id
    assert scope_a.system_version_id != scope_b.system_version_id
    assert scope_a.application_id != scope_b.application_id


def test_test_run_and_work_item_identity_are_session_independent() -> None:
    run = TestRunIdentity(
        test_run_id="RUN-1",
        production_batch_id="PB-1",
        scope_refs=["SCOPE-A"],
        created_by="tester-a",
    )
    work = WorkItemIdentity(
        work_item_id="WI-1",
        test_run_id=run.test_run_id,
        stage="EXECUTION",
        scope_refs=["SCOPE-A"],
        required_capabilities=["CAN_BROWSER"],
    )
    assert work.test_run_id == "RUN-1"
    assert not hasattr(run, "session_id")
    assert not hasattr(work, "session_id")


def test_runtime_event_requires_real_node_worker_or_tool_producer() -> None:
    event = RuntimeEventEnvelope(
        event_id="EV-1",
        test_run_id="RUN-1",
        work_item_id="WI-1",
        node_id="NODE-1",
        producer_kind=RuntimeProducerKind.TOOL,
        producer_ref="browser-skill",
        event_type="API_RESPONSE_CAPTURED",
        sequence=1,
        case_id="TC-1",
        attempt_id="ATT-1",
        step_id="STEP-2",
    )
    assert event.producer_kind == RuntimeProducerKind.TOOL

    with pytest.raises(RC8ContractError, match="RUNTIME_PRODUCER_KIND_INVALID"):
        RuntimeEventEnvelope(
            event_id="EV-BAD",
            test_run_id="RUN-1",
            work_item_id="WI-1",
            node_id="NODE-1",
            producer_kind="DIRECTOR",  # type: ignore[arg-type]
            producer_ref="director",
            event_type="CASE_PASSED",
            sequence=2,
        )


def test_verified_capability_requires_real_probe_and_evidence() -> None:
    with pytest.raises(RC8ContractError, match="VERIFIED_CAPABILITY_REQUIRES_REAL_PROBE"):
        CapabilityQualification(
            node_id="NODE-1",
            capability_id="CAN_CODEGRAPH",
            state=CapabilityState.VERIFIED,
            evidence_refs=["ART-CG-1"],
            verified_at=1,
        )

    verified = CapabilityQualification(
        node_id="NODE-1",
        capability_id="CAN_CODEGRAPH",
        state=CapabilityState.VERIFIED,
        probe_ref="probe://codegraph/query/1",
        evidence_refs=["ART-CG-1"],
        verified_at=1,
    )
    assert verified.state == CapabilityState.VERIFIED


def test_capability_state_machine_forbids_install_to_verified_shortcut() -> None:
    assert transition_capability(CapabilityState.DISCOVERED, CapabilityState.REGISTERED) == CapabilityState.REGISTERED
    with pytest.raises(RC8ContractError, match="CAPABILITY_TRANSITION_FORBIDDEN"):
        transition_capability(CapabilityState.DISCOVERED, CapabilityState.VERIFIED)


def test_pass_requires_available_evidence_for_every_assertion() -> None:
    require_pass_evidence(["AST-1", "AST-2"], [_evidence(assertions=["AST-1", "AST-2"])])

    with pytest.raises(RC8ContractError, match="PASS_ASSERTION_EVIDENCE_MISSING:AST-2"):
        require_pass_evidence(["AST-1", "AST-2"], [_evidence(assertions=["AST-1"])])

    with pytest.raises(RC8ContractError, match="PASS_ASSERTION_EVIDENCE_MISSING:AST-1"):
        require_pass_evidence(
            ["AST-1"],
            [_evidence(availability=ArtifactAvailability.UPLOADING, assertions=["AST-1"])],
        )


def test_plan_complete_does_not_imply_test_sufficient() -> None:
    claim = CompletionClaim(
        test_run_id="RUN-1",
        plan_complete=True,
        test_sufficient=False,
        unresolved_required_gaps=2,
    )
    assert claim.plan_complete is True
    assert claim.test_sufficient is False

    with pytest.raises(RC8ContractError, match="TEST_SUFFICIENT_REQUIRES_ZERO_REQUIRED_GAPS"):
        CompletionClaim(
            test_run_id="RUN-1",
            plan_complete=True,
            test_sufficient=True,
            unresolved_required_gaps=1,
            evaluator_ref="mission-evaluator",
            evidence_refs=["ART-EVAL"],
        )

    sufficient = CompletionClaim(
        test_run_id="RUN-1",
        plan_complete=True,
        test_sufficient=True,
        unresolved_required_gaps=0,
        evaluator_ref="mission-evaluator",
        evidence_refs=["ART-EVAL"],
    )
    assert sufficient.test_sufficient is True
