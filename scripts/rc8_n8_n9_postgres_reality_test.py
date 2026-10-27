from __future__ import annotations

import os

from sqlalchemy import inspect

from rc8_center.defect_closure import CenterDefectClosureService, DefectState
from rc8_center.failure_diagnosis import CenterFailureDiagnosisService, FailureClassification
from rc8_center.infrastructure.postgres import PostgresStore, build_engine
from rc8_center.infrastructure.postgres_defect_closure import PostgresDefectClosureRepository
from rc8_center.infrastructure.postgres_failure_diagnosis import PostgresFailureDiagnosisRepository


REQUIRED_TABLES = {
    "rc8_failure_observation",
    "rc8_diagnostic_evidence",
    "rc8_gap_route_decision",
    "rc8_repair_work_order",
    "rc8_repair_receipt",
    "rc8_successor_attempt",
    "rc8_defect_case",
}


def main() -> None:
    database_url = os.environ.get("RC8_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("RC8_DATABASE_URL_REQUIRED")

    engine = build_engine(database_url)
    try:
        actual_tables = set(inspect(engine).get_table_names())
        missing = sorted(REQUIRED_TABLES.difference(actual_tables))
        if missing:
            raise AssertionError("N8_N9_ALEMBIC_TABLES_MISSING:%s" % ",".join(missing))

        store = PostgresStore(engine)
        diagnosis_repo = PostgresFailureDiagnosisRepository(store)
        defect_repo = PostgresDefectClosureRepository(store)
        diagnosis = CenterFailureDiagnosisService(diagnosis_repo, now_fn=lambda: 100)
        defects = CenterDefectClosureService(defect_repo, diagnosis_repo, now_fn=lambda: 200)

        observation = diagnosis.observe(
            observation_id="reality-obs-1",
            test_run_id="reality-run-1",
            source_mission_node_id="reality-run-1:scope:N7",
            source_attempt_id="reality-attempt-1",
            source_case_id="reality-case-1",
            summary="real PostgreSQL product mismatch",
            evidence_refs=("artifact:reality-failure-evidence",),
        )
        diagnostic = diagnosis.diagnose(
            diagnostic_id="reality-diag-1",
            observation_id=observation.observation_id,
            classification=FailureClassification.PRODUCT,
            classifier_ref="center://deterministic-n8",
            reason_code="PRODUCT_SEMANTIC_MISMATCH",
            evidence_refs=("artifact:reality-diagnosis-evidence",),
        )
        route = diagnosis.route(
            decision_id="reality-route-1",
            diagnostic_id=diagnostic.diagnostic_id,
            gap_id="reality-gap-1",
        )
        defect = defects.create_candidate(
            defect_case_id="reality-defect-1",
            route_decision_id=route.decision_id,
            evidence_refs=("artifact:reality-defect-candidate",),
        )
        if defect.state != DefectState.CANDIDATE:
            raise AssertionError("N9_CANDIDATE_STATE_NOT_PERSISTED")

        reconstructed_diagnosis = PostgresFailureDiagnosisRepository(store)
        reconstructed_defects = PostgresDefectClosureRepository(store)
        persisted_route = reconstructed_diagnosis.get_route(route.decision_id)
        persisted_defect = reconstructed_defects.get_defect_case(defect.defect_case_id)
        if persisted_route != route:
            raise AssertionError("N8_ROUTE_POSTGRES_ROUNDTRIP_FAILED")
        if persisted_defect != defect:
            raise AssertionError("N9_DEFECT_POSTGRES_ROUNDTRIP_FAILED")
        if reconstructed_defects.by_route_decision(route.decision_id) != defect:
            raise AssertionError("N9_ROUTE_TO_DEFECT_BINDING_FAILED")

        print("N8_N9_POSTGRES_REALITY=PASS")
        print("N8_ROUTE_AUTHORITY=%s" % route.authority)
        print("N9_DEFECT_STATE=%s" % defect.state.value)
        print("TRUTH_NOTE=REAL_POSTGRESQL_ALEMBIC_PERSISTENCE_NOT_BANK_REALITY")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
