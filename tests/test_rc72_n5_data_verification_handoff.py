from pathlib import Path
import json
import subprocess

import pytest

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.authority import AuthorityError
from rc7_runtime.rc72_authority import DATA_VERIFIER, RC72AuthorityRuntime
from rc7_runtime.rc72_n5_data_discovery_promotion import N5DataDiscoveryCandidatePromotionService
from rc7_runtime.rc72_n5_data_verification_handoff import (
    N5DataVerificationDshHandoffService,
    N5DataVerificationHandoffError,
    validate_rc72_n5_data_verification_attempt,
)

from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE
from test_rc72_n5_data_discovery_handoff import TOOL_DATA
from test_rc72_n5_data_discovery_promotion import _anchored


VERIFY_TOOL = "data-verify-query"


def _promoted(tmp_path: Path, monkeypatch):
    truth, receipt, _anchor, state_root = _anchored(tmp_path, monkeypatch)
    promoted = N5DataDiscoveryCandidatePromotionService(
        truth,
        release_id=RELEASE,
        mission_id=MISSION,
        source_commit=COMMIT,
        state_root=str(state_root),
    ).promote(
        release_batch_id=BATCH,
        data_requirement_id=receipt["data_requirement_id"],
    )
    return truth, receipt, promoted


def _producer_lineage(truth, receipt):
    task = truth.query("rc7_task", task_id=receipt["workitem_id"])[0]
    artifact = truth.query("rc7_artifact", artifact_id=task["output_artifact_refs"][0])[0]
    attempts = truth.query(
        "rc72_n5_data_discovery_attempt",
        data_requirement_id=receipt["data_requirement_id"],
    )
    assert len(attempts) == 1
    return task, artifact, attempts[0]


def _precondition_refs(requirement):
    values = list(requirement.get("case_preconditions") or [])
    if not values:
        return ["data-requirement://%s" % requirement["data_requirement_id"]]
    return [
        "data-requirement://%s/precondition/%d"
        % (requirement["data_requirement_id"], index)
        for index, _item in enumerate(values)
    ]


def _v2_candidate(truth, receipt, *, repair=False, smuggle=False):
    requirement = truth.query(
        "rc72_n5_data_requirement",
        data_requirement_id=receipt["data_requirement_id"],
    )[0]
    plan = truth.query(
        "rc72_n5_data_resolution_plan",
        plan_id=receipt["resolution_plan_id"],
    )[0]
    task, artifact, _producer = _producer_lineage(truth, receipt)
    assert task["state"] == "OUTPUT_PRODUCED"
    value = {
        "status": "REPAIR_REQUIRED" if repair else "VERIFIED_CANDIDATE",
        "release_batch_id": BATCH,
        "data_requirement_id": receipt["data_requirement_id"],
        "resolution_plan_id": plan["plan_id"],
        "case_id": receipt["case_id"],
        "candidate_artifact_id": artifact["artifact_id"],
        "strategy": "DISCOVER_EXISTING",
        "candidate_ref": None if repair else "candidate://tdsql/account/fixture-001",
        "data_domain": None if repair else "BLOAN_TEST_DATA",
        "mutable": None if repair else False,
        "source_or_constructor": None if repair else "real-data-query:fixture-001",
        "verification": (
            "candidate could not be proven against all required preconditions"
            if repair
            else "real data query independently proved every required precondition"
        ),
        "validity_window": None if repair else "release-batch:%s" % BATCH,
        "cleanup_policy": None if repair else "NONE_READ_ONLY",
        "precondition_refs": _precondition_refs(requirement),
        "unknowns": ["candidate identity not proven"] if repair else [],
        "gaps": ["independent verification incomplete"] if repair else [],
    }
    if smuggle:
        value["data_ref"] = "data://premature/verified"
    return value


def _verifier_launcher(
    tmp_path: Path,
    truth,
    receipt,
    *,
    calls=None,
    fixed_session=None,
    tool_name=VERIFY_TOOL,
    repair=False,
    smuggle=False,
):
    dsh = tmp_path / ("dsh-n5-verifier-%s" % id(calls))
    dsh.write_text("fixture executable placeholder", encoding="utf-8")
    patch = tmp_path / ("patch-n5-verifier-%s.json" % id(calls))
    patch.write_text("{}", encoding="utf-8")
    counter = calls if calls is not None else {"count": 0}

    def runner(command, **kwargs):
        counter["count"] += 1
        prompt = str(command[-1])
        assert "independent RC7.2 N5 DATA_VERIFIER" in prompt
        assert receipt["data_requirement_id"] in prompt
        _task, artifact, producer = _producer_lineage(truth, receipt)
        assert artifact["artifact_id"] in prompt
        session_id = fixed_session or "session-n5-verifier-%d" % counter["count"]
        events = [
            {"type": "session", "session_id": session_id},
            {"type": "tool_call", "tool_name": tool_name},
            {
                "type": "final",
                "text": json.dumps(
                    _v2_candidate(
                        truth,
                        receipt,
                        repair=repair,
                        smuggle=smuggle,
                    ),
                    ensure_ascii=False,
                ),
            },
        ]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="\n".join(json.dumps(item, ensure_ascii=False) for item in events) + "\n",
            stderr="",
        )

    return DshHeadlessWorkerLauncher(
        dsh_bin=str(dsh),
        patch_path=str(patch),
        cwd=str(tmp_path),
        truth=truth,
        authority=RC72AuthorityRuntime(b"rc72-n5-data-verifier-test-key"),
        coordinator_instance_id="coordinator-n5-data-verifier",
        release_id=RELEASE,
        state_root=str(tmp_path / ("state-n5-verifier-%s" % id(calls))),
        command_runner=runner,
    )


def _service(tmp_path, truth, receipt, **launcher_kwargs):
    launcher = _verifier_launcher(tmp_path, truth, receipt, **launcher_kwargs)
    return N5DataVerificationDshHandoffService(
        truth,
        release_id=RELEASE,
        mission_id=MISSION,
        source_commit=COMMIT,
        launcher=launcher,
        allowed_tools=[VERIFY_TOOL],
    )


def test_data_verifier_is_zero_artifact_role_with_task_scoped_tools_only():
    authority = RC72AuthorityRuntime(b"rc72-data-verifier-authority-key")
    identity = authority.issue_identity(
        DATA_VERIFIER,
        "DATA_VERIFICATION",
        None,
        0,
        "runtime-assignment-test",
    )
    lease = authority.issue_lease(
        identity.worker_id,
        "artifact:ART-N5-DATA-1",
        (),
        (VERIFY_TOOL,),
    )
    authority.authorize_tool(identity.worker_id, lease.lease_id, VERIFY_TOOL)
    with pytest.raises(AuthorityError, match="LEASE_TOOL_FORBIDDEN"):
        authority.authorize_tool(identity.worker_id, lease.lease_id, "unleased-shell")
    with pytest.raises(AuthorityError, match="LEASE_ARTIFACT_SCOPE_EXCEEDS_ROLE"):
        authority.issue_lease(
            identity.worker_id,
            "artifact:ART-N5-DATA-1",
            ("evidence",),
            (VERIFY_TOOL,),
        )


def test_n5_independent_verifier_observes_v2_raw_candidate_without_admitting_data_truth(
    tmp_path: Path, monkeypatch
):
    truth, receipt, promoted = _promoted(tmp_path, monkeypatch)
    _task, _artifact, producer = _producer_lineage(truth, receipt)
    calls = {"count": 0}
    result = _service(tmp_path, truth, receipt, calls=calls).verify(
        release_batch_id=BATCH,
        data_requirement_id=receipt["data_requirement_id"],
    )

    assert result["status"] == "VERIFIER_SESSION_OBSERVED"
    assert calls["count"] == 1
    assert result["candidate_artifact_id"] == promoted["artifact_id"]
    assert result["producer_worker_id"] == producer["worker_instance_id"]
    assert result["producer_dsh_session_id"] == producer["dsh_session_id"]
    assert result["verifier_worker_id"] != producer["worker_instance_id"]
    assert result["verifier_dsh_session_id"] != producer["dsh_session_id"]
    assert result["attempt_state"] == "VERIFIER_COMPLETED_PENDING_RAW_ANCHOR"
    assert result["workitem_state"] == "OUTPUT_PRODUCED"

    attempts = truth.query(
        "rc72_n5_data_verification_attempt",
        verification_attempt_id=result["verification_attempt_id"],
    )
    assert len(attempts) == 1
    attempt = attempts[0]
    assert attempt["candidate_schema"] == "RC72_N5_DATA_VERIFICATION_CANDIDATE_V2"
    assert attempt["producer_worker_id"] != attempt["verifier_worker_id"]
    assert attempt["producer_dsh_session_id"] != attempt["verifier_dsh_session_id"]
    assert attempt["observed_tool_calls"][0]["tool_name"] == VERIFY_TOOL
    assert any(ref.startswith("file://") for ref in attempt["runtime_evidence_refs"])
    for forbidden in (
        "candidate_ref", "data_domain", "mutable", "source_or_constructor",
        "verification", "validity_window", "cleanup_policy", "precondition_refs",
        "data_ref", "binding_id", "verified", "data_lease_id", "node_pass",
        "n6_ready", "field_verified", "bank_final",
    ):
        assert forbidden not in attempt

    assert truth.query(
        "rc72_n5_data_binding", data_requirement_id=receipt["data_requirement_id"]
    ) == []
    assert truth.query("rc72_data_lease") == []
    n5 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N5_TEST_DATA"
    )[0]
    n6 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N6_EXECUTABLE_READINESS"
    )[0]
    assert n5["state"] == "RUNNING"
    assert n6["state"] == "NOT_STARTED"


def test_n5_verifier_replay_is_idempotent_without_second_verifier_session(
    tmp_path: Path, monkeypatch
):
    truth, receipt, _promoted = _promoted(tmp_path, monkeypatch)
    calls = {"count": 0}
    service = _service(tmp_path, truth, receipt, calls=calls)
    first = service.verify(
        release_batch_id=BATCH,
        data_requirement_id=receipt["data_requirement_id"],
    )
    second = service.verify(
        release_batch_id=BATCH,
        data_requirement_id=receipt["data_requirement_id"],
    )
    assert first["status"] == "VERIFIER_SESSION_OBSERVED"
    assert second["status"] == "RESUMED"
    assert first["verification_attempt_id"] == second["verification_attempt_id"]
    assert first["verifier_worker_id"] == second["verifier_worker_id"]
    assert first["verifier_dsh_session_id"] == second["verifier_dsh_session_id"]
    assert calls["count"] == 1


def test_n5_verifier_rejects_producer_session_reuse_and_admits_no_attempt(
    tmp_path: Path, monkeypatch
):
    truth, receipt, _promoted = _promoted(tmp_path, monkeypatch)
    _task, _artifact, producer = _producer_lineage(truth, receipt)
    service = _service(
        tmp_path,
        truth,
        receipt,
        fixed_session=producer["dsh_session_id"],
    )
    with pytest.raises(
        N5DataVerificationHandoffError,
        match="SESSION_REUSED_FROM_PRODUCER",
    ):
        service.verify(
            release_batch_id=BATCH,
            data_requirement_id=receipt["data_requirement_id"],
        )
    assert truth.query("rc72_n5_data_verification_attempt", mission_id=MISSION) == []
    assert truth.query(
        "rc72_n5_data_binding", data_requirement_id=receipt["data_requirement_id"]
    ) == []


def test_n5_verifier_rejects_unleased_tool_and_admits_no_attempt(
    tmp_path: Path, monkeypatch
):
    truth, receipt, _promoted = _promoted(tmp_path, monkeypatch)
    launcher = _verifier_launcher(
        tmp_path,
        truth,
        receipt,
        tool_name="unapproved-shell",
    )
    service = N5DataVerificationDshHandoffService(
        truth,
        release_id=RELEASE,
        mission_id=MISSION,
        source_commit=COMMIT,
        launcher=launcher,
        allowed_tools=[VERIFY_TOOL],
    )
    with pytest.raises(N5DataVerificationHandoffError, match="UNAUTHORIZED_TOOL"):
        service.verify(
            release_batch_id=BATCH,
            data_requirement_id=receipt["data_requirement_id"],
        )
    assert truth.query("rc72_n5_data_verification_attempt", mission_id=MISSION) == []


def test_n5_verifier_v2_contract_rejects_canonical_data_ref_smuggling(
    tmp_path: Path, monkeypatch
):
    truth, receipt, _promoted = _promoted(tmp_path, monkeypatch)
    service = _service(tmp_path, truth, receipt, smuggle=True)
    with pytest.raises(
        N5DataVerificationHandoffError,
        match="V2_TOP_LEVEL_CONTRACT_INVALID",
    ):
        service.verify(
            release_batch_id=BATCH,
            data_requirement_id=receipt["data_requirement_id"],
        )
    assert truth.query("rc72_n5_data_verification_attempt", mission_id=MISSION) == []
    assert truth.query("rc72_data_lease") == []


def test_n5_verifier_can_report_repair_required_without_claiming_resource_truth(
    tmp_path: Path, monkeypatch
):
    truth, receipt, _promoted = _promoted(tmp_path, monkeypatch)
    result = _service(tmp_path, truth, receipt, repair=True).verify(
        release_batch_id=BATCH,
        data_requirement_id=receipt["data_requirement_id"],
    )
    attempt = truth.query(
        "rc72_n5_data_verification_attempt",
        verification_attempt_id=result["verification_attempt_id"],
    )[0]
    assert attempt["state"] == "VERIFIER_COMPLETED_PENDING_RAW_ANCHOR"
    assert "candidate_ref" not in attempt
    assert "data_ref" not in attempt
    assert truth.query(
        "rc72_n5_data_binding", data_requirement_id=receipt["data_requirement_id"]
    ) == []


def test_n5_verification_attempt_contract_rejects_post_anchor_truth_claims(
    tmp_path: Path, monkeypatch
):
    truth, receipt, _promoted = _promoted(tmp_path, monkeypatch)
    result = _service(tmp_path, truth, receipt).verify(
        release_batch_id=BATCH,
        data_requirement_id=receipt["data_requirement_id"],
    )
    attempt = truth.query(
        "rc72_n5_data_verification_attempt",
        verification_attempt_id=result["verification_attempt_id"],
    )[0]
    for field, value in (
        ("candidate_ref", "candidate://fake"),
        ("data_ref", "data://fake"),
        ("binding_id", "BIND-FAKE"),
        ("data_lease_id", "LEASE-FAKE"),
        ("node_pass", True),
        ("n6_ready", True),
        ("field_verified", True),
        ("bank_final", True),
    ):
        tampered = dict(attempt)
        tampered[field] = value
        with pytest.raises(Exception, match="PREMATURE_TRUTH_FORBIDDEN"):
            validate_rc72_n5_data_verification_attempt(tampered)
