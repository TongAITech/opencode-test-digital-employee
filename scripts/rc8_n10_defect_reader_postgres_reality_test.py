"""Real PostgreSQL proof for N10 reading N9 defect truth by test_run_id."""
from __future__ import annotations

import os

from rc8_center.defect_closure import DefectCase, DefectState
from rc8_center.infrastructure.postgres import PostgresStore, build_engine
from rc8_center.infrastructure.postgres_defect_closure import PostgresDefectClosureRepository


def _case(defect_case_id: str, test_run_id: str, route_id: str, created_at: int) -> DefectCase:
    return DefectCase(
        defect_case_id=defect_case_id,
        test_run_id=test_run_id,
        route_decision_id=route_id,
        source_observation_id="obs:%s" % defect_case_id,
        source_case_id="case:%s" % defect_case_id,
        source_attempt_id="attempt:%s" % defect_case_id,
        state=DefectState.CANDIDATE,
        candidate_evidence_refs=("evidence://%s" % defect_case_id,),
        created_at=created_at,
        updated_at=created_at,
    )


def main() -> int:
    database_url = os.environ.get("RC8_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("RC8_DATABASE_URL_REQUIRED")

    engine = build_engine(database_url)
    try:
        store = PostgresStore(engine)
        repository = PostgresDefectClosureRepository(store)
        repository.save_defect_case(_case("n10-defect-a-2", "n10-run-a", "n10-route-a-2", 20))
        repository.save_defect_case(_case("n10-defect-b-1", "n10-run-b", "n10-route-b-1", 15))
        repository.save_defect_case(_case("n10-defect-a-1", "n10-run-a", "n10-route-a-1", 10))

        reconstructed = PostgresDefectClosureRepository(store)
        rows = reconstructed.list_for_test_run("n10-run-a")
        ids = tuple(item.defect_case_id for item in rows)
        if ids != ("n10-defect-a-1", "n10-defect-a-2"):
            raise AssertionError("N10_DEFECT_READER_ORDER_OR_ISOLATION_FAILED:%r" % (ids,))
        if any(item.test_run_id != "n10-run-a" for item in rows):
            raise AssertionError("N10_DEFECT_READER_CROSS_RUN_LEAK")
        if reconstructed.list_for_test_run("n10-run-missing") != ():
            raise AssertionError("N10_DEFECT_READER_MISSING_RUN_NOT_EMPTY")

        print("RC8_N10_DEFECT_READER_POSTGRES_REALITY_PASS")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
