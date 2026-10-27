import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine

from rc8_center.control_plane import WorkItemRecord, WorkItemState
from rc8_center.defect_closure import (
    CenterDefectClosureService,
    DefectReviewDecision,
    DefectSeverity,
    DefectState,
)
from rc8_center.failure_diagnosis import (
    CenterFailureDiagnosisService,
    FailureClassification,
)
from rc8_center.infrastructure.postgres import Base, PostgresStore
from rc8_center.infrastructure.postgres_defect_closure import PostgresDefectClosureRepository
from rc8_center.infrastructure.postgres_failure_diagnosis import PostgresFailureDiagnosisRepository
from rc8_center.n7_execution_result import N7CaseExecutionOutcome, N7CaseExecutionResult
from rc8_runtime import WorkItemIdentity


class _Receipts:
    def __init__(self):
        self.values = {}

    def add(self, value):
        self.values[value.work_item_id] = value

    def read_for_work_item(self, work_item_id):
        return self.values[work_item_id]

    @staticmethod
    def event_id_for(result):
        return "center-n7-case-result:%s:%s" % (
            result.work_item_id,
            result.case_execution_attempt_id,
        )


class _Control:
    def __init__(self):
        self.work = {}
        self.links = {}

    def add(self, work_item_id, fix_ref, created_at):
        self.work[work_item_id] = WorkItemRecord(
            identity=WorkItemIdentity(
                work_item_id=work_item_id,
                test_run_id="run-1",
                stage="APPLICABLE_LAYER_EXECUTION",
                scope_refs=[fix_ref],
                required_capabilities=[],
            ),
            state=WorkItemState.COMPLETED,
        )
        self.links[work_item_id] = SimpleNamespace(
            test_run_id="run-1",
            created_at=created_at,
        )

    def get_work_item(self, work_item_id):
        return self.work.get(work_item_id)

    def get_stage_link_for_work_item(self, work_item_id):
        return self.links.get(work_item_id)


class PostgresDefectClosureTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        database = Path(self.tmpdir.name) / "center.db"
        self.engine = create_engine(
            "sqlite+pysqlite:///%s" % database.as_posix(), future=True
        )
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.store = PostgresStore(self.engine)
        self.diagnosis_repo = PostgresFailureDiagnosisRepository(self.store)
        self.diagnosis = CenterFailureDiagnosisService(
            self.diagnosis_repo, now_fn=lambda: self.now
        )
        self.repo = PostgresDefectClosureRepository(self.store)
        self.receipts = _Receipts()
        self.control = _Control()
        self.now = 100
        self.service = CenterDefectClosureService(
            self.repo,
            self.diagnosis_repo,
            n7_result_receipts=self.receipts,
            control_repository=self.control,
            now_fn=lambda: self.now,
        )

    def _result(self, work_item_id, attempt_id, case_id):
        result = N7CaseExecutionResult(
            outcome=N7CaseExecutionOutcome.PASS,
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
        return result

    def test_closed_defect_survives_repository_reconstruction_with_n7_authority(self):
        self.diagnosis.observe(
            observation_id="obs-1",
            test_run_id="run-1",
            source_mission_node_id="run-1:scope:N7",
            source_attempt_id="attempt-1",
            source_case_id="case-1",
            summary="product mismatch",
            evidence_refs=("evidence://attempt/1",),
        )
        diagnostic = self.diagnosis.diagnose(
            diagnostic_id="diag-1",
            observation_id="obs-1",
            classification=FailureClassification.PRODUCT,
            classifier_ref="classifier://n8",
            reason_code="PRODUCT_SEMANTIC_MISMATCH",
            evidence_refs=("evidence://diagnosis/1",),
        )
        route = self.diagnosis.route(
            decision_id="route-1",
            diagnostic_id=diagnostic.diagnostic_id,
            gap_id="gap-1",
        )
        self.service.create_candidate(
            defect_case_id="defect-1",
            route_decision_id=route.decision_id,
            evidence_refs=("evidence://candidate",),
        )
        self.now += 1
        self.service.reproduce(
            "defect-1",
            reproduction_attempt_id="attempt-repro",
            reproducer_ref="team://independent",
            evidence_refs=("evidence://repro",),
        )
        self.now += 1
        self.service.qualify(
            "defect-1",
            qualified=True,
            evidence_refs=("evidence://qualify",),
        )
        self.now += 1
        self.service.record_rca(
            "defect-1",
            rca_summary="state transition bug",
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
            impact_refs=("api://customer/update",),
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
        fixed = self.service.detect_fix(
            "defect-1",
            fix_revision_ref="git://sha/fix",
            evidence_refs=("evidence://fix",),
        )

        verify_created = fixed.updated_at + 1
        self.control.add("work-verify", "git://sha/fix", verify_created)
        self._result("work-verify", "attempt-verify", "case-1")
        self.now = verify_created + 1
        verified = self.service.verify_fix(
            "defect-1",
            verification_work_item_id="work-verify",
        )

        regression_created = verified.updated_at + 1
        self.control.add(
            "work-regression", "git://sha/fix", regression_created
        )
        self._result(
            "work-regression",
            "attempt-regression",
            "case-impact-2",
        )
        self.now = regression_created + 1
        self.service.record_impact_regression(
            "defect-1",
            regression_work_item_id="work-regression",
        )
        self.now += 1
        expected = self.service.close(
            "defect-1", evidence_refs=("evidence://close",)
        )

        reconstructed = PostgresDefectClosureRepository(self.store)
        loaded = reconstructed.get_defect_case("defect-1")
        self.assertEqual(expected, loaded)
        self.assertEqual(DefectState.CLOSED, loaded.state)
        self.assertTrue(loaded.disposition_complete)
        self.assertEqual("work-verify", loaded.fix_verification_work_item_id)
        self.assertEqual("attempt-verify", loaded.fix_verification_attempt_id)
        self.assertEqual(
            "work-regression", loaded.impact_regression_work_item_id
        )
        self.assertEqual(
            "attempt-regression", loaded.impact_regression_attempt_id
        )
        self.assertEqual("case-impact-2", loaded.impact_regression_case_id)
        self.assertEqual(
            "defect-1",
            reconstructed.by_route_decision("route-1").defect_case_id,
        )


if __name__ == "__main__":
    unittest.main()
