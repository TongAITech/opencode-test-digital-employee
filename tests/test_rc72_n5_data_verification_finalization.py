from pathlib import Path
import json

import pytest

from rc7_runtime.rc72_data_resources import DataLeaseManager
from rc7_runtime.rc72_n5_data_resolution import N5DataResolutionService
from rc7_runtime.rc72_n5_data_verification_finalization import (
    N5DataVerificationFinalizationError,
    N5DataVerificationFinalizationService,
    validate_rc72_n5_data_verification_result,
)

from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE
from test_rc72_n5_data_verification_anchor import (
    _anchor_service,
    _raw_path,
    _verified,
)


def _anchored(tmp_path: Path, monkeypatch, **launcher_kwargs):
    truth, receipt, promoted, verifier_service, result, attempt = _verified(
        tmp_path,
        monkeypatch,
        **launcher_kwargs
    )
    anchor = _anchor_service(truth, verifier_service).anchor(
        release_batch_id=BATCH,
        data_requirement_id=receipt["data_requirement_id"],
    )
    return truth, receipt, promoted, verifier_service, result, attempt, anchor


def _service(truth, verifier_service, *, source_commit=COMMIT):
    return N5DataVerificationFinalizationService(
        truth,
        release_id=RELEASE,
        mission_id=MISSION,
        source_commit=source_commit,
        state_root=str(verifier_service.launcher.state_root),
    )


def test_n5_verifier_finalization_registers_verified_resource_and_exact_binding_only(
    tmp_path: Path, monkeypatch
):
    truth, receipt, promoted, verifier_service, _verify_result, _attempt, anchor = _anchored(
        tmp_path, monkeypatch
    )
    finalizer = _service(truth, verifier_service)
    result = finalizer.finalize(
        release_batch_id=BATCH,
        data_requirement_id=receipt["data_requirement_id"],
    )

    assert result["status"] == "FINALIZED_VERIFIED"
    assert result["data_ref"] == "data://tdsql/account/fixture-001"
    assert result["reservation_mode"] == "SHARED_READ"

    evidence = truth.query(
        "rc7_evidence", evidence_id=result["verification_evidence_id"]
    )
    assert len(evidence) == 1
    assert evidence[0]["kind"] == "N5_DATA_VERIFICATION_DSH_RAW_PROOF"
    assert evidence[0]["content_hash"] == anchor["raw_output_sha256"]
    assert evidence[0]["source_ref"] == "dsh://session/%s" % anchor["verifier_dsh_session_id"]
    assert evidence[0]["content_ref"] == anchor["raw_output_ref"]

    resources = truth.query("rc72_data_resource", data_ref=result["data_ref"])
    assert len(resources) == 1
    resource = resources[0]
    assert resource["release_id"] == RELEASE
    assert resource["verified"] is True
    assert resource["mutable"] is False
    assert resource["data_domain"] == "BLOAN_TEST_DATA"
    assert resource["metadata_ref"] == "candidate://tdsql/account/fixture-001"

    bindings = truth.query(
        "rc72_n5_data_binding", binding_id=result["binding_id"]
    )
    assert len(bindings) == 1
    binding = bindings[0]
    assert binding["data_requirement_id"] == receipt["data_requirement_id"]
    assert binding["data_ref"] == result["data_ref"]
    assert binding["verification_evidence_refs"] == [result["verification_evidence_id"]]
    assert binding["status"] == "VERIFIED"
    assert binding["reservation_mode"] == "SHARED_READ"

    finalizations = truth.query(
        "rc72_n5_data_verification_result",
        finalization_id=result["finalization_id"],
    )
    assert len(finalizations) == 1
    finalized = finalizations[0]
    assert finalized["decision"] == "VERIFIED_CANDIDATE"
    assert finalized["candidate_artifact_id"] == promoted["artifact_id"]
    assert finalized["raw_output_sha256"] == anchor["raw_output_sha256"]
    assert finalized["binding_id"] == result["binding_id"]

    # Finalization admits verified data truth only. It does not reserve a resource,
    # pass N5, or release N6.
    assert truth.query("rc72_data_lease") == []
    assert truth.query(
        "rc72_node_delivery", mission_id=MISSION, node_type="N5_TEST_DATA"
    ) == []
    assert truth.query(
        "rc72_node_gate", mission_id=MISSION, node_type="N5_TEST_DATA"
    ) == []
    assert truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N5_TEST_DATA"
    )[0]["state"] == "RUNNING"
    assert truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N6_EXECUTABLE_READINESS"
    )[0]["state"] == "NOT_STARTED"

    # The pre-existing plan is not silently rewritten by finalization. A separate,
    # deterministic resolver pass makes the new exact binding reusable.
    plan = truth.query(
        "rc72_n5_data_resolution_plan", plan_id=receipt["resolution_plan_id"]
    )[0]
    assert plan["status"] == "DISCOVERY_REQUIRED"
    resolved = N5DataResolutionService(
        truth,
        release_id=RELEASE,
        source_commit=COMMIT,
    ).resolve_all(release_batch_id=BATCH)
    reused = [row for row in resolved["plans"] if row["data_requirement_id"] == receipt["data_requirement_id"]]
    assert len(reused) == 1
    assert reused[0]["status"] == "REUSE_VERIFIED"
    assert reused[0]["data_ref"] == result["data_ref"]
    assert truth.query("rc72_data_lease") == []


def test_n5_verifier_finalization_replay_is_idempotent(
    tmp_path: Path, monkeypatch
):
    truth, receipt, _promoted, verifier_service, _verify_result, _attempt, _anchor = _anchored(
        tmp_path, monkeypatch
    )
    finalizer = _service(truth, verifier_service)
    first = finalizer.finalize(
        release_batch_id=BATCH,
        data_requirement_id=receipt["data_requirement_id"],
    )
    second = finalizer.finalize(
        release_batch_id=BATCH,
        data_requirement_id=receipt["data_requirement_id"],
    )

    assert first["status"] == "FINALIZED_VERIFIED"
    assert second["status"] == "RESUMED"
    assert second["finalization_id"] == first["finalization_id"]
    assert second["data_ref"] == first["data_ref"]
    assert second["binding_id"] == first["binding_id"]
    assert len(truth.query("rc72_data_resource", data_ref=first["data_ref"])) == 1
    assert len(truth.query("rc72_n5_data_binding", binding_id=first["binding_id"])) == 1
    assert len(truth.query("rc7_evidence", evidence_id=first["verification_evidence_id"])) == 1
    assert len(truth.query("rc72_n5_data_verification_result", finalization_id=first["finalization_id"])) == 1
    assert truth.query("rc72_data_lease") == []


def test_n5_verifier_finalization_rejects_raw_bytes_changed_after_anchor(
    tmp_path: Path, monkeypatch
):
    truth, receipt, _promoted, verifier_service, _verify_result, attempt, _anchor = _anchored(
        tmp_path, monkeypatch
    )
    path = _raw_path(attempt)
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    final = [event for event in events if event.get("type") == "final"][0]
    candidate = json.loads(final["text"])
    candidate["candidate_ref"] = "candidate://tdsql/account/fixture-tampered"
    final["text"] = json.dumps(candidate, ensure_ascii=False)
    path.write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        N5DataVerificationFinalizationError,
        match="ANCHOR_INVALID:.*CONFLICT:raw_output_sha256",
    ):
        _service(truth, verifier_service).finalize(
            release_batch_id=BATCH,
            data_requirement_id=receipt["data_requirement_id"],
        )
    assert truth.query("rc72_n5_data_verification_result") == []
    assert truth.query("rc72_n5_data_binding", data_requirement_id=receipt["data_requirement_id"]) == []
    assert truth.query("rc72_data_resource") == []
    assert truth.query("rc72_data_lease") == []


def test_n5_repair_required_is_persisted_without_resource_binding_or_lease(
    tmp_path: Path, monkeypatch
):
    truth, receipt, _promoted, verifier_service, _verify_result, _attempt, anchor = _anchored(
        tmp_path, monkeypatch, repair=True
    )
    result = _service(truth, verifier_service).finalize(
        release_batch_id=BATCH,
        data_requirement_id=receipt["data_requirement_id"],
    )

    assert result["status"] == "REPAIR_REQUIRED"
    assert result["unknowns"]
    assert result["gaps"]
    finalization = truth.query(
        "rc72_n5_data_verification_result",
        finalization_id=result["finalization_id"],
    )[0]
    assert finalization["decision"] == "REPAIR_REQUIRED"
    assert finalization["raw_output_sha256"] == anchor["raw_output_sha256"]
    assert finalization["candidate_ref"] is None
    assert finalization["data_ref"] is None
    assert finalization["binding_id"] is None
    evidence = truth.query("rc7_evidence", evidence_id=result["verification_evidence_id"])[0]
    assert evidence["content_hash"] == anchor["raw_output_sha256"]
    assert truth.query("rc72_data_resource") == []
    assert truth.query("rc72_n5_data_binding", data_requirement_id=receipt["data_requirement_id"]) == []
    assert truth.query("rc72_data_lease") == []
    assert truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N5_TEST_DATA"
    )[0]["state"] == "RUNNING"
    assert truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N6_EXECUTABLE_READINESS"
    )[0]["state"] == "NOT_STARTED"


def test_n5_verifier_finalization_fails_closed_on_conflicting_existing_resource(
    tmp_path: Path, monkeypatch
):
    truth, receipt, _promoted, verifier_service, _verify_result, _attempt, _anchor = _anchored(
        tmp_path, monkeypatch
    )
    data_ref = "data://tdsql/account/fixture-001"
    DataLeaseManager(truth, release_id=RELEASE).register_data_ref(
        data_ref=data_ref,
        data_domain="WRONG_DOMAIN",
        verified=True,
        mutable=False,
        metadata_ref="candidate://tdsql/account/fixture-001",
    )

    with pytest.raises(
        N5DataVerificationFinalizationError,
        match="RESOURCE_CONFLICT:data_domain",
    ):
        _service(truth, verifier_service).finalize(
            release_batch_id=BATCH,
            data_requirement_id=receipt["data_requirement_id"],
        )
    assert truth.query("rc72_n5_data_binding", data_requirement_id=receipt["data_requirement_id"]) == []
    assert truth.query("rc72_n5_data_verification_result") == []
    assert truth.query("rc72_data_lease") == []


def test_n5_verifier_finalization_requires_exact_source_commit(
    tmp_path: Path, monkeypatch
):
    truth, receipt, _promoted, verifier_service, _verify_result, _attempt, _anchor = _anchored(
        tmp_path, monkeypatch
    )
    with pytest.raises(
        N5DataVerificationFinalizationError,
        match="ANCHOR_INVALID:.*EXACT_ATTEMPT_REQUIRED:0",
    ):
        _service(
            truth,
            verifier_service,
            source_commit="stale-source-commit",
        ).finalize(
            release_batch_id=BATCH,
            data_requirement_id=receipt["data_requirement_id"],
        )
    assert truth.query("rc72_n5_data_binding", data_requirement_id=receipt["data_requirement_id"]) == []
    assert truth.query("rc72_data_lease") == []


def test_n5_verification_result_contract_rejects_premature_lease_claim(
    tmp_path: Path, monkeypatch
):
    truth, receipt, _promoted, verifier_service, _verify_result, _attempt, _anchor = _anchored(
        tmp_path, monkeypatch
    )
    result = _service(truth, verifier_service).finalize(
        release_batch_id=BATCH,
        data_requirement_id=receipt["data_requirement_id"],
    )
    row = truth.query(
        "rc72_n5_data_verification_result",
        finalization_id=result["finalization_id"],
    )[0]
    forged = dict(row)
    forged["data_lease_id"] = "DATALEASE-PREMATURE"
    with pytest.raises(Exception, match="PREMATURE_CLAIM_FORBIDDEN:data_lease_id"):
        validate_rc72_n5_data_verification_result(forged)
