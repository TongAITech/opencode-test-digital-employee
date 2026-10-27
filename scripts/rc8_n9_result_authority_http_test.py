#!/usr/bin/env python3
"""Real PostgreSQL + Redis + R1 + HTTP proof for N9 result authority.

This proof starts from an N8 PRODUCT route, advances a defect to FIX_DETECTED,
then proves N9 cannot consume caller booleans or an old PASS. Only a completed
N7 WorkItem created for the current fix revision plus its Center-derived R1
CASE_EXECUTION_RESULT_DERIVED receipt may advance fix verification/regression.

It proves Center authority wiring, not bank-side PFC execution reality.
"""
from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from rc8_center.control_plane import WorkItemRecord, WorkItemState
from rc8_center.defect_closure import (
    DefectReviewDecision,
    DefectSeverity,
    DefectState,
)
from rc8_center.failure_diagnosis import FailureClassification
from rc8_center.formal_app import app
from rc8_center.n7_execution_result import (
    N7CaseExecutionOutcome,
    N7CaseExecutionResult,
)
from rc8_runtime import WorkItemIdentity
from rc8_runtime.governance import StageInstance, StageState


def _result(
    *,
    run_id: str,
    work_item_id: str,
    case_id: str,
    attempt_id: str,
    outcome: N7CaseExecutionOutcome,
) -> N7CaseExecutionResult:
    return N7CaseExecutionResult(
        outcome=outcome,
        test_run_id=run_id,
        work_item_id=work_item_id,
        case_id=case_id,
        case_execution_attempt_id=attempt_id,
        prepared_attempt_id="prepared:%s" % attempt_id,
        executable_spec_id="executable:%s" % attempt_id,
        assertion_refs=("assertion:business",),
        resolved_assertion_refs=("assertion:business",),
        evidence_refs=("n7-evidence-%s" % work_item_id,),
        reason="CENTER_DERIVED_TEST_RESULT",
    )


def main() -> int:
    suffix = uuid.uuid4().hex[:10]
    run_id = "n9-result-auth-%s" % suffix
    source_case_id = "CASE-N9-%s" % suffix
    source_attempt_id = "source-attempt-%s" % suffix
    defect_id = "defect-%s" % suffix
    fix_ref = "git://sha/fix-%s" % suffix
    stage_id = "stage-n7-n9-auth-%s" % suffix

    client = TestClient(app)
    postgres = app.state.postgres
    control_repository = app.state.control_repository
    governance_repository = app.state.governance_repository
    diagnosis = app.state.failure_diagnosis_service
    defects = app.state.defect_closure_service
    receipts = app.state.n7_case_execution_result_receipt_authority

    assert postgres.ping(), "POSTGRES_PING_FAILED"
    assert app.state.redis_coordination.ping(), "REDIS_PING_FAILED"
    postgres.create_test_run(
        run_id,
        payload={"truth_scope": "N9_N7_RESULT_AUTHORITY_REALITY"},
    )

    diagnosis.observe(
        observation_id="obs-%s" % suffix,
        test_run_id=run_id,
        source_mission_node_id="%s:scope:N7" % run_id,
        source_attempt_id=source_attempt_id,
        source_case_id=source_case_id,
        summary="product semantic mismatch",
        evidence_refs=("evidence://source/%s" % suffix,),
    )
    diagnostic = diagnosis.diagnose(
        diagnostic_id="diag-%s" % suffix,
        observation_id="obs-%s" % suffix,
        classification=FailureClassification.PRODUCT,
        classifier_ref="classifier://n8",
        reason_code="PRODUCT_SEMANTIC_MISMATCH",
        evidence_refs=("evidence://diagnosis/%s" % suffix,),
    )
    route = diagnosis.route(
        decision_id="route-%s" % suffix,
        diagnostic_id=diagnostic.diagnostic_id,
        gap_id="gap-%s" % suffix,
    )

    defects.create_candidate(
        defect_case_id=defect_id,
        route_decision_id=route.decision_id,
        evidence_refs=("evidence://candidate/%s" % suffix,),
    )
    defects.reproduce(
        defect_id,
        reproduction_attempt_id="repro-attempt-%s" % suffix,
        reproducer_ref="team://independent-reproducer",
        evidence_refs=("evidence://repro/%s" % suffix,),
    )
    defects.qualify(
        defect_id,
        qualified=True,
        evidence_refs=("evidence://qualification/%s" % suffix,),
    )
    defects.record_rca(
        defect_id,
        rca_summary="state transition bug",
        evidence_refs=("evidence://rca/%s" % suffix,),
    )
    defects.deduplicate(
        defect_id,
        evidence_refs=("evidence://dedup/%s" % suffix,),
    )
    defects.assess(
        defect_id,
        severity=DefectSeverity.HIGH,
        impact_refs=("api://customer/update",),
        evidence_refs=("evidence://impact/%s" % suffix,),
    )
    defects.review(
        defect_id,
        decision=DefectReviewDecision.ACCEPT,
        evidence_refs=("evidence://review/%s" % suffix,),
    )
    defects.file(
        defect_id,
        external_defect_ref="defect://PFC-%s" % suffix,
        evidence_refs=("evidence://file/%s" % suffix,),
    )
    fixed = defects.detect_fix(
        defect_id,
        fix_revision_ref=fix_ref,
        evidence_refs=("evidence://fix/%s" % suffix,),
    )
    assert fixed.state == DefectState.FIX_DETECTED

    governance_repository.upsert_stage(
        StageInstance(
            stage_instance_id=stage_id,
            test_run_id=run_id,
            stage_type="APPLICABLE_LAYER_EXECUTION",
            scope_version="scope:N9-result-auth:%s" % suffix,
            attempt_no=1,
            state=StageState.COMPLETED,
            assigned_worker="N7ExecutionWorker",
            started_at=fixed.updated_at + 1,
            finished_at=fixed.updated_at + 2,
        )
    )

    def register_validation(
        *,
        work_item_id: str,
        attempt_id: str,
        case_id: str,
        created_at: int,
        outcome: N7CaseExecutionOutcome = N7CaseExecutionOutcome.PASS,
        scope_fix_ref: str = fix_ref,
    ) -> None:
        control_repository.upsert_work_item(
            WorkItemRecord(
                identity=WorkItemIdentity(
                    work_item_id=work_item_id,
                    test_run_id=run_id,
                    stage="APPLICABLE_LAYER_EXECUTION",
                    scope_refs=[scope_fix_ref, "case:%s" % case_id],
                    required_capabilities=[],
                ),
                state=WorkItemState.COMPLETED,
            )
        )
        control_repository.link_work_item_to_stage(
            work_item_id=work_item_id,
            stage_instance_id=stage_id,
            test_run_id=run_id,
            created_at=created_at,
        )
        receipts.record(
            _result(
                run_id=run_id,
                work_item_id=work_item_id,
                case_id=case_id,
                attempt_id=attempt_id,
                outcome=outcome,
            ),
            node_id="center-n9-reality",
        )

    stale_work = "work-stale-pass-%s" % suffix
    register_validation(
        work_item_id=stale_work,
        attempt_id="attempt-stale-pass-%s" % suffix,
        case_id=source_case_id,
        created_at=fixed.updated_at,
    )
    stale = client.post(
        "/api/v1/defects/%s/verify-fix" % defect_id,
        json={"work_item_id": stale_work},
    )
    assert stale.status_code == 409, stale.text
    assert (
        stale.json()["detail"]
        == "N9_VALIDATION_WORK_ITEM_NOT_NEWER_THAN_DEFECT_STATE"
    )

    verify_work = "work-fix-verify-%s" % suffix
    register_validation(
        work_item_id=verify_work,
        attempt_id="attempt-fix-verify-%s" % suffix,
        case_id=source_case_id,
        created_at=fixed.updated_at + 1,
    )

    caller_boolean = client.post(
        "/api/v1/defects/%s/verify-fix" % defect_id,
        json={"work_item_id": verify_work, "passed": True},
    )
    assert caller_boolean.status_code == 422, caller_boolean.text

    verified = client.post(
        "/api/v1/defects/%s/verify-fix" % defect_id,
        json={"work_item_id": verify_work},
    )
    assert verified.status_code == 200, verified.text
    verified_defect = verified.json()["defect"]
    assert verified_defect["state"] == "FIX_VERIFIED", verified_defect
    assert verified_defect["fix_verification_work_item_id"] == verify_work
    assert verified_defect["fix_verification_attempt_id"].startswith(
        "attempt-fix-verify-"
    )
    assert verified["truth_note"].startswith(
        "FIX_RESULT_DERIVED_FROM_CENTER_N7_R1_RECEIPT"
    )

    current = defects.repository.get_defect_case(defect_id)
    regression_work = "work-impact-regression-%s" % suffix
    register_validation(
        work_item_id=regression_work,
        attempt_id="attempt-impact-regression-%s" % suffix,
        case_id="CASE-IMPACT-%s" % suffix,
        created_at=current.updated_at + 1,
    )
    regression = client.post(
        "/api/v1/defects/%s/impact-regression" % defect_id,
        json={"work_item_id": regression_work},
    )
    assert regression.status_code == 200, regression.text
    regression_defect = regression.json()["defect"]
    assert regression_defect["state"] == "REGRESSION_VERIFIED", regression_defect
    assert regression_defect["impact_regression_work_item_id"] == regression_work

    persisted = client.get("/api/v1/defects/%s" % defect_id)
    assert persisted.status_code == 200, persisted.text
    body = persisted.json()["defect"]
    assert body["fix_verification_work_item_id"] == verify_work
    assert body["impact_regression_work_item_id"] == regression_work
    assert any(
        str(ref).startswith("r1-event:center-n7-case-result:")
        for ref in body["fix_verification_evidence_refs"]
    )

    print("N9_N7_RESULT_AUTHORITY_REALITY=PASS")
    print("CALLER_BOOLEAN_PASS=REJECTED")
    print("STALE_PRE_FIX_PASS_RECEIPT=REJECTED")
    print("FIX_VERIFICATION_WORK_ITEM=%s" % verify_work)
    print("IMPACT_REGRESSION_WORK_ITEM=%s" % regression_work)
    print("RUNTIME_TRUTH=R1_EVENT_STREAM")
    print("TRUTH_NOTE=REAL_POSTGRESQL_REDIS_R1_HTTP_NOT_BANK_EXECUTION_REALITY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
