import unittest
from types import SimpleNamespace

from rc8_center.control_plane import WorkItemRecord, WorkItemState
from rc8_center.defect_closure import (
    CenterDefectClosureService,
    DefectClosureError,
    DefectReviewDecision,
    DefectSeverity,
    DefectState,
    MemoryDefectClosureRepository,
)
from rc8_center.failure_diagnosis import (
    CenterFailureDiagnosisService,
    FailureClassification,
    MemoryFailureDiagnosisRepository,
)
from rc8_center.n7_execution_result import (
    N7CaseExecutionOutcome,
    N7CaseExecutionResult,
)
from rc8_runtime import WorkItemIdentity


class _Receipts:
    def __init__(self):
        self.values = {}

    def add(self, result):
        self.values[result.work_item_id] = result

    def read_for_work_item(self, work_item_id):
        return self.values[work_item_id]

    @staticmethod
    def event_id_for(result):
        return "center-n7-case-result:%s:%s" % (
            result.work_item_id,
            result.case_execution_attempt_id,
        )


class _ControlRepository:
    def __init__(self):
        self.work = {}
        self.links = {}

    def add(
        self,
        work_item_id,
        *,
        test_run_id="run-1",
        scope_refs=(),
        created_at=0,
        state=WorkItemState.COMPLETED,
        stage="APPLICABLE_LAYER_EXECUTION",
    ):
        self.work[work_item_id] = WorkItemRecord(
            identity=WorkItemIdentity(
                work_item_id=work_item_id,
                test_run_id=test_run_id,
                stage=stage,
                scope_refs=list(scope_refs),
                required_capabilities=[],
            ),
            state=state,
        )
        self.links[work_item_id] = SimpleNamespace(
            work_item_id=work_item_id,
            test_run_id=test_run_id,
            created_at=created_at,
        )

    def get_work_item(self, work_item_id):
        return self.work.get(work_item_id)

    def get_stage_link_for_work_item(self, work_item_id):
        return self.links.get(work_item_id)


class DefectClosureTest(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.diagnosis_repo = MemoryFailureDiagnosisRepository()
        self.diagnosis = CenterFailureDiagnosisService(
            self.diagnosis_repo, now_fn=lambda: self.now
        )
        self.repo = MemoryDefectClosureRepository()
        self.receipts = _Receipts()
        self.control = _ControlRepository()
        self.service = CenterDefectClosureService(
            self.repo,
            self.diagnosis_repo,
            n7_result_receipts=self.receipts,
            control_repository=self.control,
            now_fn=lambda: self.now,
        )

    def _route(self, classification=FailureClassification.PRODUCT, suffix="1"):
        self.diagnosis.observe(
            observation_id="obs-%s" % suffix,
            test_run_id="run-1",
            source_mission_node_id="run-1:scope:N7",
            source_attempt_id="attempt-%s" % suffix,
            source_case_id="case-%s" % suffix,
            summary="failure-%s" % suffix,
            evidence_refs=("evidence://attempt/%s" % suffix,),
        )
        diagnostic = self.diagnosis.diagnose(
            diagnostic_id="diag-%s" % suffix,
            observation_id="obs-%s" % suffix,
            classification=classification,
            classifier_ref="classifier://n8",
            reason_code=classification.value,
            evidence_refs=("evidence://diagnosis/%s" % suffix,),
        )
        return self.diagnosis.route(
            decision_id="route-%s" % suffix,
            diagnostic_id=diagnostic.diagnostic_id,
            gap_id="gap-%s" % suffix,
        )

    def _advance_to_fix(self, *, fix_ref="git://sha/fix1"):
        route = self._route()
        self.service.create_candidate(
            defect_case_id="defect-1",
            route_decision_id=route.decision_id,
            evidence_refs=("evidence://candidate",),
        )
        self.now += 1
        self.service.reproduce(
            "defect-1",
            reproduction_attempt_id="attempt-repro-2",
            reproducer_ref="team://independent-reproducer",
            evidence_refs=("evidence://repro/2",),
        )
        self.now += 1
        self.service.qualify(
            "defect-1",
            qualified=True,
            evidence_refs=("evidence://qualification",),
        )
        self.now += 1
        self.service.record_rca(
            "defect-1",
            rca_summary="service rejects valid state transition",
            evidence_refs=("evidence://rca",),
        )
        self.now += 1
        self.service.deduplicate(
            "defect-1", evidence_refs=("evidence://dedup",)
        )
        self.now += 1
        self.service.assess(
            "defect-1",
            severity=DefectSeverity.HIGH,
            impact_refs=("requirement://STBB19-320", "api://customer/update"),
            evidence_refs=("evidence://impact",),
        )
        self.now += 1
        self.service.review(
            "defect-1",
            decision=DefectReviewDecision.ACCEPT,
            evidence_refs=("evidence://review",),
        )
        self.now += 1
        self.service.file(
            "defect-1",
            external_defect_ref="defect://PFC-1001",
            evidence_refs=("evidence://file",),
        )
        self.now += 1
        return self.service.detect_fix(
            "defect-1",
            fix_revision_ref=fix_ref,
            evidence_refs=("evidence://fix-detected",),
        )

    def _seed_result(
        self,
        work_item_id,
        attempt_id,
        *,
        outcome=N7CaseExecutionOutcome.PASS,
        case_id="case-1",
        created_at=None,
        fix_ref="git://sha/fix1",
        scope_refs=None,
    ):
        created = self.now + 1 if created_at is None else created_at
        refs = (fix_ref,) if scope_refs is None else tuple(scope_refs)
        self.control.add(
            work_item_id,
            scope_refs=refs,
            created_at=created,
        )
        result = N7CaseExecutionResult(
            outcome=outcome,
            test_run_id="run-1",
            work_item_id=work_item_id,
            case_id=case_id,
            case_execution_attempt_id=attempt_id,
            prepared_attempt_id="prepared:%s" % attempt_id,
            executable_spec_id="executable:%s" % attempt_id,
            assertion_refs=("assertion:business",),
            resolved_assertion_refs=("assertion:business",),
            evidence_refs=("artifact-%s" % work_item_id,),
            reason="CENTER_DERIVED_TEST_RESULT",
        )
        self.receipts.add(result)
        return result, created

    def test_non_product_failure_cannot_create_defect_candidate(self):
        route = self._route(FailureClassification.SCRIPT)
        with self.assertRaisesRegex(
            DefectClosureError, "N9_REQUIRES_PRODUCT_ROUTE"
        ):
            self.service.create_candidate(
                defect_case_id="defect-1",
                route_decision_id=route.decision_id,
                evidence_refs=("evidence://candidate",),
            )

    def test_independent_reproduction_requires_new_attempt(self):
        route = self._route()
        self.service.create_candidate(
            defect_case_id="defect-1",
            route_decision_id=route.decision_id,
            evidence_refs=("evidence://candidate",),
        )
        with self.assertRaisesRegex(
            DefectClosureError,
            "INDEPENDENT_REPRODUCTION_REQUIRES_NEW_ATTEMPT",
        ):
            self.service.reproduce(
                "defect-1",
                reproduction_attempt_id="attempt-1",
                reproducer_ref="team://defect-review",
                evidence_refs=("evidence://repro",),
            )

    def test_caller_boolean_cannot_authoritatively_verify_fix(self):
        self._advance_to_fix()
        with self.assertRaises(TypeError):
            self.service.verify_fix(
                "defect-1",
                passed=True,
                evidence_refs=("evidence://caller-claimed-pass",),
            )

    def test_full_defect_lifecycle_uses_new_n7_result_receipts(self):
        self._advance_to_fix()
        verify_result, verify_created = self._seed_result(
            "work-fix-verify",
            "attempt-fix-verify",
        )
        self.now = verify_created + 1
        verified = self.service.verify_fix(
            "defect-1",
            verification_work_item_id="work-fix-verify",
        )
        self.assertEqual(DefectState.FIX_VERIFIED, verified.state)
        self.assertEqual("work-fix-verify", verified.fix_verification_work_item_id)
        self.assertEqual(
            verify_result.case_execution_attempt_id,
            verified.fix_verification_attempt_id,
        )
        self.assertIn(
            "r1-event:center-n7-case-result:work-fix-verify:attempt-fix-verify",
            verified.fix_verification_evidence_refs,
        )

        regression_result, regression_created = self._seed_result(
            "work-impact-regression",
            "attempt-impact-regression",
            case_id="case-impact-2",
        )
        self.now = max(self.now + 1, regression_created + 1)
        # The regression WorkItem must be newer than FIX_VERIFIED, so replace
        # the test lineage with a fresh Center registration time.
        self.control.links["work-impact-regression"].created_at = self.now + 1
        self.now += 2
        regressed = self.service.record_impact_regression(
            "defect-1",
            regression_work_item_id="work-impact-regression",
        )
        self.assertEqual(DefectState.REGRESSION_VERIFIED, regressed.state)
        self.assertEqual(
            regression_result.case_execution_attempt_id,
            regressed.impact_regression_attempt_id,
        )
        self.assertEqual("case-impact-2", regressed.impact_regression_case_id)

        self.now += 1
        closed = self.service.close(
            "defect-1", evidence_refs=("evidence://close",)
        )
        self.assertEqual(DefectState.CLOSED, closed.state)
        self.assertTrue(closed.disposition_complete)

    def test_failed_authoritative_fix_verification_reopens(self):
        self._advance_to_fix()
        _, created = self._seed_result(
            "work-fix-fail",
            "attempt-fix-fail",
            outcome=N7CaseExecutionOutcome.FAIL,
        )
        self.now = created + 1
        reopened = self.service.verify_fix(
            "defect-1",
            verification_work_item_id="work-fix-fail",
        )
        self.assertEqual(DefectState.REOPENED, reopened.state)
        self.assertFalse(reopened.disposition_complete)

    def test_old_or_wrong_revision_pass_receipt_cannot_be_replayed(self):
        fixed = self._advance_to_fix()
        self._seed_result(
            "work-old-pass",
            "attempt-old-pass",
            created_at=fixed.updated_at,
        )
        with self.assertRaisesRegex(
            DefectClosureError,
            "N9_VALIDATION_WORK_ITEM_NOT_NEWER_THAN_DEFECT_STATE",
        ):
            self.service.verify_fix(
                "defect-1",
                verification_work_item_id="work-old-pass",
            )

        self._seed_result(
            "work-wrong-revision",
            "attempt-wrong-revision",
            created_at=fixed.updated_at + 1,
            scope_refs=("git://sha/other-fix",),
        )
        with self.assertRaisesRegex(
            DefectClosureError,
            "N9_VALIDATION_WORK_ITEM_FIX_REVISION_MISMATCH",
        ):
            self.service.verify_fix(
                "defect-1",
                verification_work_item_id="work-wrong-revision",
            )

    def test_fix_verification_requires_source_case_and_new_attempt(self):
        fixed = self._advance_to_fix()
        self._seed_result(
            "work-wrong-case",
            "attempt-new",
            case_id="case-other",
            created_at=fixed.updated_at + 1,
        )
        with self.assertRaisesRegex(
            DefectClosureError, "N9_FIX_VERIFICATION_CASE_MISMATCH"
        ):
            self.service.verify_fix(
                "defect-1",
                verification_work_item_id="work-wrong-case",
            )

        self._seed_result(
            "work-reused-attempt",
            "attempt-repro-2",
            created_at=fixed.updated_at + 2,
        )
        with self.assertRaisesRegex(
            DefectClosureError, "N9_VALIDATION_REQUIRES_NEW_EXECUTION_ATTEMPT"
        ):
            self.service.verify_fix(
                "defect-1",
                verification_work_item_id="work-reused-attempt",
            )


if __name__ == "__main__":
    unittest.main()
