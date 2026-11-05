"""C04 product N8->N9 signed reproduction request, not reproduction/Defect PASS.

Real local N7 business failure and DSH process protocol are executed in
approved deterministic fixtures. This suite does NOT assert live bank DSH,
Human Approval, second business Attempt, independent RCA, or N9 completion.
"""
import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_n9_reproduction_authorization import (
    N9ReproductionAuthorizationRequestService,
)
from rc72_n2_test_support import BATCH
from test_rc72_n9_captain_signed_dsh_bridge import _route


def test_possible_product_cause_creates_one_signed_no_io_fresh_reproduction_request(
        tmp_path, monkeypatch):
    truth, plan, prep, server, pipeline, route, calls, candidate, owner = _route(
        tmp_path, monkeypatch, finding="POSSIBLE_PRODUCT_CAUSE")
    try:
        original = pipeline.complete(release_batch_id=BATCH)
        assert original["failure_class"] == "VALID_TEST_FAILURE"
        original_attempt = truth.query(
            "execution_attempt", attempt_id=truth.query(
                "rc72_n7_execution_preparation",
                preparation_id=original["preparation_id"])[0]["attempt_id"])
        assert len(original_attempt) == 1
        before_attempts = truth.query("execution_attempt")
        before_calls = len(server.calls)

        qualified = route.complete(release_batch_id=BATCH)
        assert qualified["status"] == "HOLD"
        assert qualified["reason"] == "N9_CAUSAL_REVIEW_AND_REAL_REPRODUCTION_REQUIRED"
        assert qualified["cause_candidate_only"] is True
        assert qualified["reproduction_admission_reason"] == (
            "N9_INDEPENDENT_REPRODUCTION_AUTHORIZATION_REQUIRED")
        assert qualified["reproduction_request_id"].startswith("N9REPRO-")
        assert qualified["defect_confirmed"] is False
        assert qualified["reproduction_completed"] is False
        assert qualified["field_verified"] is qualified["bank_final"] is False

        rows = truth.query("rc72_n9_reproduction_authorization_request")
        assert len(rows) == 1
        row = rows[0]
        assert row["request_id"] == qualified["reproduction_request_id"]
        assert row["candidate_finding"] == "POSSIBLE_PRODUCT_CAUSE"
        assert row["original_attempt_id"] == truth.query(
            "rc72_n7_execution_preparation",
            preparation_id=original["preparation_id"])[0]["attempt_id"]
        assert row["analysis_id"] == qualified["analysis_id"]
        assert row["analysis_tool_refs"] == ["dsh-event://tool-call/1"]
        assert row["analysis_raw_sha256"] == truth.query(
            "rc72_n9_professional_dsh_analysis")[0]["raw_output_sha256"]
        assert row["original_gap_id"] == truth.query("rc72_diagnosis_outcome")[0]["gap_id"]
        assert row["original_case_id"] == truth.query(
            "rc72_n7_execution_preparation")[0]["case_id"]
        assert row["approved_case_artifact_refs"]
        assert row["state"] == "AWAITING_INDEPENDENT_APPROVAL_AND_FRESH_EXECUTION"
        assert len(row["required_guards"]) == 6
        assert all(key not in row for key in (
            "reproduced", "fresh_attempt_id", "permission_granted",
            "product_defect", "human_approved", "defect_confirmed"))
        assert truth.query("execution_attempt") == before_attempts
        assert len(calls) == 1
        assert len(server.calls) == before_calls
        assert not truth.query("rc7_defect")
        assert not truth.query("rc7_task", task_type="DEFECT_REPRODUCTION")
        assert not truth.query("rc72_node_gate", node_type="N9_DEFECT")

        snapshot = truth.store.path.read_bytes()
        assert route.complete(release_batch_id=BATCH) == qualified
        assert truth.store.path.read_bytes() == snapshot
        assert len(calls) == 1 and len(server.calls) == before_calls
        # Distinct ledger process can reopen signed immutable request without
        # relying on an in-memory DSH/chat session.
        cold = TruthRuntime(truth.store.path)
        assert cold.query("rc72_n9_reproduction_authorization_request")[0] == row
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("finding", [
    "INCONCLUSIVE", "POSSIBLE_TEST_ORACLE_PROBLEM",
    "POSSIBLE_ENVIRONMENT_CAUSE",
])
def test_nonproduct_or_unproven_cause_never_reserves_reproduction_authority(
        tmp_path, monkeypatch, finding):
    truth, plan, prep, server, pipeline, route, calls, _, _ = _route(
        tmp_path, monkeypatch, finding=finding)
    try:
        original = pipeline.complete(release_batch_id=BATCH)
        initial_attempts = truth.query("execution_attempt")
        before_business = len(server.calls)
        result = route.complete(release_batch_id=BATCH)
        assert result["status"] == "HOLD"
        assert result["reproduction_request_id"] is None
        assert result["reproduction_admission_reason"] == (
            "N9_CAUSAL_HYPOTHESIS_NOT_PRODUCT_REPRODUCTION_READY")
        assert not truth.query("rc72_n9_reproduction_authorization_request")
        assert not truth.query("rc7_defect")
        assert truth.query("execution_attempt") == initial_attempts
        assert len(calls) == 1
        assert len(server.calls) == before_business
        before = truth.store.path.read_bytes()
        assert route.complete(release_batch_id=BATCH) == result
        assert truth.store.path.read_bytes() == before
    finally:
        server.shutdown()
        server.server_close()


def test_changed_signed_request_is_denied_on_cold_reentry_without_business_io(
        tmp_path, monkeypatch):
    truth, plan, prep, server, pipeline, route, calls, _, _ = _route(
        tmp_path, monkeypatch, finding="POSSIBLE_PRODUCT_CAUSE")
    try:
        pipeline.complete(release_batch_id=BATCH)
        result = route.complete(release_batch_id=BATCH)
        row = dict(truth.query("rc72_n9_reproduction_authorization_request")[0])
        row["signature"] = "0" * 64
        row["artifact_version"] += 1
        truth.append_atomic("RC72_N9_REPRODUCTION_AUTHORIZATION_REQUESTED", row)
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError, match="N9_REPRODUCTION_REQUEST_SIGNATURE_CHANGED"):
            route.complete(release_batch_id=BATCH)
        assert truth.store.path.read_bytes() == before
        assert len(calls) == len(server.calls) == 1
        assert not truth.query("rc7_defect")
    finally:
        server.shutdown()
        server.server_close()


def test_tampered_independent_dsh_raw_evidence_revokes_request_reuse_without_replay(
        tmp_path, monkeypatch):
    from pathlib import Path
    truth, plan, prep, server, pipeline, route, calls, _, _ = _route(
        tmp_path, monkeypatch, finding="POSSIBLE_PRODUCT_CAUSE")
    try:
        pipeline.complete(release_batch_id=BATCH)
        result = route.complete(release_batch_id=BATCH)
        signed = truth.query("rc72_n9_professional_dsh_analysis")[0]
        raw_path = route.professional_dsh.launcher.state_root / "worker-evidence" / (
            signed["mission_id"]) / (signed["assignment_id"] + ".jsonl")
        raw_path.write_bytes(raw_path.read_bytes() + b"\nTAMPERED-FORENSIC-TOOL")
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError, match="N9_DSH_RAW_BYTES_CHANGED|N9_DSH_NATIVE_RAW"):
            route.complete(release_batch_id=BATCH)
        assert truth.store.path.read_bytes() == before
        assert len(calls) == len(server.calls) == 1
        assert not truth.query("rc7_defect")
    finally:
        server.shutdown()
        server.server_close()


def test_reproduction_request_rejects_foreign_analysis_and_cross_diagnosis(
        tmp_path, monkeypatch):
    truth, plan, prep, server, pipeline, route, calls, _, _ = _route(
        tmp_path, monkeypatch, finding="POSSIBLE_PRODUCT_CAUSE")
    try:
        original = pipeline.complete(release_batch_id=BATCH)
        qualified = route.complete(release_batch_id=BATCH)
        svc = N9ReproductionAuthorizationRequestService(route.professional_dsh)
        before = truth.store.path.read_bytes()
        for analysis_id, diagnosis_id in [
            ("N9DSH-FOREIGN", original["diagnosis_id"]),
            (qualified["analysis_id"], "N8DIAG-FOREIGN"),
        ]:
            with pytest.raises(ContractError):
                svc.request(
                    preparation_id=original["preparation_id"],
                    diagnosis_id=diagnosis_id, analysis_id=analysis_id)
            assert truth.store.path.read_bytes() == before
        assert len(calls) == len(server.calls) == 1
        assert not truth.query("rc7_defect")
    finally:
        server.shutdown()
        server.server_close()



def test_formal_release_batch_driver_n8_route_consumes_signed_n9_request_without_business_replay(
        tmp_path, monkeypatch):
    """Use production ReleaseBatchDriver N8 dispatch, not a parallel N9 callback."""
    import sys
    from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
    from rc7_runtime.rc72_authority import RC72AuthorityRuntime
    from rc7_runtime.rc72_release_driver import ReleaseBatchDriver
    from rc7_runtime.dsh_requirement_evaluator import DshRequirementEvaluator
    from rc7_runtime.rc72_n9_accepted_scope import AcceptedScopeN9Service
    from rc72_pip_field_test_support import provider as field_provider

    truth, plan, prep, server, pipeline, route, calls, _, _ = _route(
        tmp_path, monkeypatch, finding="POSSIBLE_PRODUCT_CAUSE")
    try:
        original = pipeline.complete(release_batch_id=BATCH)
        patch = tmp_path / "driver-n9-request-patch.json"
        patch.write_text("{}", encoding="utf-8")
        def nonparticipating(role):
            def forbidden(*args, **kwargs):
                pytest.fail("ReleaseBatch N8 may not replay an upstream DSH role")
            return DshHeadlessWorkerLauncher(
                dsh_bin=sys.executable, patch_path=str(patch),
                cwd=str(tmp_path), truth=truth,
                authority=RC72AuthorityRuntime(
                    ("n9-request-formal-" + role).encode("utf-8")),
                coordinator_instance_id="nonparticipating-controller",
                release_id=pipeline.release_id,
                state_root=str(tmp_path / ("driver-" + role)),
                command_runner=forbidden)
        driver = ReleaseBatchDriver(
            truth, source_commit=pipeline.source_commit,
            bank_pip_mirror=field_provider(
                truth, source_commit=pipeline.source_commit),
            n1_launcher=nonparticipating("n1"), n1_tools=["n1-native-tool"],
            n2_launcher=nonparticipating("n2"), n2_tools=["n2-native-tool"],
            n2_evaluator=DshRequirementEvaluator(
                nonparticipating("review"), allowed_tools=["n2-review-tool"]),
            n7_pipeline=pipeline, n8_pipeline=route,
            n9_pipeline=AcceptedScopeN9Service(pipeline))
        batch = truth.query("rc72_release_batch", release_batch_id=BATCH)[0]
        before_calls = len(server.calls)
        prior_attempts = truth.query("execution_attempt")
        result = driver._complete_gate("N8_DIAGNOSIS_RECOVERY", batch)
        assert result["status"] == "HOLD"
        assert result["reproduction_request_id"].startswith("N9REPRO-")
        assert len(truth.query("rc72_n9_reproduction_authorization_request")) == 1
        assert truth.query("execution_attempt") == prior_attempts
        assert len(server.calls) == before_calls
        assert len(calls) == 1
        assert not truth.query("rc7_defect")
        before = truth.store.path.read_bytes()
        assert driver._complete_gate("N8_DIAGNOSIS_RECOVERY", batch) == result
        assert truth.store.path.read_bytes() == before
        assert len(server.calls) == before_calls and len(calls) == 1
    finally:
        server.shutdown()
        server.server_close()
