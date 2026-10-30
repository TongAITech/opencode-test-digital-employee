from pathlib import Path
import json
import subprocess

import pytest

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_n2_candidate_guard import (
    N2GovernedRequirementHandoffService,
    N2RequirementCandidateGuardError,
    N2RequirementEvidenceAnchorService,
    N2TraceableRequirementDshHandoffService,
    install_rc72_n2_candidate_guard_overlay,
    validate_rc72_n2_dsh_evidence_anchor,
)
from rc7_runtime.rc72_n2_requirement_assignment import (
    N2RequirementAssignmentService,
    install_rc72_n2_requirement_assignment_overlay,
)
from rc7_runtime.rc72_n2_requirement_handoff import N2RequirementHandoffError

from rc72_n2_test_support import (
    BATCH,
    COMMIT,
    MISSION,
    RELEASE,
    REQUIREMENTS,
    build_truth,
    dispatch_n2,
)


TOOL = "requirement-source-probe"


def _candidate(requirement_id, *, include_trace=True, malformed_trace=False):
    source_ref = "starlink://requirement/%s" % requirement_id
    analysis = {
        "atomic_statements": [
            {
                "id": "ATOM-%s" % requirement_id,
                "text": "fixture statement",
                "source_ref": source_ref,
                "testable": True,
            }
        ],
        "source_assertions": [
            {
                "id": "SRC-%s" % requirement_id,
                "text": "fixture source",
                "source_ref": source_ref,
            }
        ],
        "business_rules": [],
        "roles": [],
        "preconditions": [],
        "normal_paths": [],
        "negative_paths": [],
        "boundaries": [],
        "states": [],
        "data_constraints": [],
        "dependencies": [],
        "side_effects": [],
        "dimension_exclusions": [],
    }
    if include_trace:
        analysis["trace_links"] = [
            {
                "source_id": "SRC-%s" % requirement_id,
                "atomic_id": "ATOM-%s" % requirement_id,
                "evidence_ref": "not-a-real-source" if malformed_trace else source_ref,
            }
        ]
    return {
        "status": "CANDIDATE",
        "facts": {
            "requirement_id": requirement_id,
            "sst_ids": ["SST-%s" % requirement_id],
            "source_refs": [source_ref],
            "analysis": analysis,
        },
        "unknowns": [],
        "gaps": [],
    }


def _ready(tmp_path):
    truth = build_truth(tmp_path)
    install_rc72_n2_requirement_assignment_overlay()
    install_rc72_n2_candidate_guard_overlay()
    dispatch_n2(truth)
    assigned = N2RequirementAssignmentService(
        truth, source_commit=COMMIT
    ).assign_all(release_batch_id=BATCH)
    assert assigned["status"] == "ASSIGNED"
    return truth


def _launcher(tmp_path: Path, truth, *, include_trace=True, malformed_trace=False, calls=None):
    dsh = tmp_path / "dsh-n2-guard"
    dsh.write_text("fixture executable placeholder", encoding="utf-8")
    patch = tmp_path / "patch-n2-guard.json"
    patch.write_text("{}", encoding="utf-8")
    counter = calls if calls is not None else {"count": 0}

    def runner(command, **kwargs):
        counter["count"] += 1
        prompt = str(command[-1])
        matches = [req for req in REQUIREMENTS if req in prompt]
        assert len(matches) == 1
        requirement_id = matches[0]
        candidate = _candidate(
            requirement_id,
            include_trace=include_trace,
            malformed_trace=malformed_trace,
        )
        events = [
            {"type": "session", "session_id": "session-n2-guard-%d" % counter["count"]},
            {"type": "tool_call", "tool_name": TOOL},
            {"type": "final", "text": json.dumps(candidate, ensure_ascii=False)},
        ]
        stdout = "\n".join(json.dumps(item, ensure_ascii=False) for item in events) + "\n"
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    return DshHeadlessWorkerLauncher(
        dsh_bin=str(dsh),
        patch_path=str(patch),
        cwd=str(tmp_path),
        truth=truth,
        authority=RC72AuthorityRuntime(b"rc72-n2-guard-test-signing-key"),
        coordinator_instance_id="coordinator-n2-guard",
        release_id=RELEASE,
        state_root=str(tmp_path / "state-n2-guard"),
        command_runner=runner,
    )


def test_governed_n2_handoff_immediately_hash_anchors_traceable_raw_output(tmp_path):
    truth = _ready(tmp_path)
    launcher = _launcher(tmp_path, truth)

    result = N2GovernedRequirementHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=launcher,
        allowed_tools=[TOOL],
    ).handoff(release_batch_id=BATCH, requirement_id=REQUIREMENTS[0])

    assert result["status"] == "SESSION_OBSERVED"
    assert result["candidate_schema"] == "RC72_N2_REQUIREMENT_CANDIDATE_V1_TRACEABLE"
    assert result["raw_output_sha256"].startswith("sha256:")
    anchor = truth.query(
        "rc72_n2_dsh_evidence_anchor",
        anchor_id=result["evidence_anchor_id"],
    )[0]
    assert anchor["attempt_id"] == result["attempt_id"]
    assert anchor["requirement_id"] == REQUIREMENTS[0]
    assert anchor["raw_output_sha256"] == result["raw_output_sha256"]
    assert anchor["raw_output_ref"].startswith("file://")
    assert truth.query("rc72_node_delivery", mission_id=MISSION, node_type="N2_REQUIREMENT") == []
    assert truth.query("rc72_node_gate", mission_id=MISSION, node_type="N2_REQUIREMENT") == []


def test_anchor_detects_raw_output_replacement_after_initial_admission(tmp_path):
    truth = _ready(tmp_path)
    launcher = _launcher(tmp_path, truth)
    governed = N2GovernedRequirementHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=launcher,
        allowed_tools=[TOOL],
    )
    result = governed.handoff(
        release_batch_id=BATCH, requirement_id=REQUIREMENTS[0]
    )
    anchor = truth.query(
        "rc72_n2_dsh_evidence_anchor",
        anchor_id=result["evidence_anchor_id"],
    )[0]
    raw_path = Path(anchor["raw_output_ref"][len("file://"):])
    raw_path.write_text(
        raw_path.read_text(encoding="utf-8") + json.dumps({"type": "noise"}) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        N2RequirementCandidateGuardError,
        match="ANCHOR_CONFLICT",
    ):
        N2RequirementEvidenceAnchorService(
            truth,
            source_commit=COMMIT,
            state_root=str(launcher.state_root),
        ).anchor(release_batch_id=BATCH, requirement_id=REQUIREMENTS[0])


def test_trace_links_are_required_before_attempt_becomes_promotion_eligible(tmp_path):
    truth = _ready(tmp_path)
    launcher = _launcher(tmp_path, truth, include_trace=False)

    with pytest.raises(N2RequirementHandoffError, match="TRACE_LINKS_REQUIRED"):
        N2TraceableRequirementDshHandoffService(
            truth,
            source_commit=COMMIT,
            launcher=launcher,
            allowed_tools=[TOOL],
        ).handoff(release_batch_id=BATCH, requirement_id=REQUIREMENTS[0])

    assert truth.query("rc72_n2_dsh_evidence_anchor", mission_id=MISSION) == []


def test_trace_link_must_reference_exact_real_source_locator(tmp_path):
    truth = _ready(tmp_path)
    launcher = _launcher(tmp_path, truth, malformed_trace=True)

    with pytest.raises(
        N2RequirementHandoffError,
        match="TRACE_EVIDENCE_NOT_SOURCE_REF",
    ):
        N2TraceableRequirementDshHandoffService(
            truth,
            source_commit=COMMIT,
            launcher=launcher,
            allowed_tools=[TOOL],
        ).handoff(release_batch_id=BATCH, requirement_id=REQUIREMENTS[0])

    assert truth.query("rc72_n2_dsh_evidence_anchor", mission_id=MISSION) == []


def test_governed_handoff_is_idempotent_without_relaunch_and_reuses_anchor(tmp_path):
    truth = _ready(tmp_path)
    calls = {"count": 0}
    launcher = _launcher(tmp_path, truth, calls=calls)
    service = N2GovernedRequirementHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=launcher,
        allowed_tools=[TOOL],
    )

    first = service.handoff(release_batch_id=BATCH, requirement_id=REQUIREMENTS[0])
    second = service.handoff(release_batch_id=BATCH, requirement_id=REQUIREMENTS[0])

    assert first["status"] == "SESSION_OBSERVED"
    assert second["status"] == "RESUMED"
    assert first["attempt_id"] == second["attempt_id"]
    assert first["evidence_anchor_id"] == second["evidence_anchor_id"]
    assert first["raw_output_sha256"] == second["raw_output_sha256"]
    assert calls["count"] == 1


def test_anchor_contract_forbids_smuggled_gate_or_field_truth(tmp_path):
    truth = _ready(tmp_path)
    launcher = _launcher(tmp_path, truth)
    result = N2GovernedRequirementHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=launcher,
        allowed_tools=[TOOL],
    ).handoff(release_batch_id=BATCH, requirement_id=REQUIREMENTS[0])
    anchor = dict(
        truth.query(
            "rc72_n2_dsh_evidence_anchor",
            anchor_id=result["evidence_anchor_id"],
        )[0]
    )
    anchor["node_gate"] = "PASS"
    with pytest.raises(Exception, match="BUSINESS_CLAIM_FORBIDDEN:node_gate"):
        validate_rc72_n2_dsh_evidence_anchor(anchor)
