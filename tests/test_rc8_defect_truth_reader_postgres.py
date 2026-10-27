import unittest

from sqlalchemy import create_engine

from rc8_center.defect_closure import DefectCase, DefectClosureError, DefectState
from rc8_center.infrastructure.postgres import Base, PostgresStore
from rc8_center.infrastructure.postgres_defect_closure import PostgresDefectClosureRepository


class PostgresDefectTruthReaderTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.store = PostgresStore(self.engine)
        self.repo = PostgresDefectClosureRepository(self.store)

    @staticmethod
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

    def test_list_for_test_run_is_deterministic_and_isolated(self):
        self.repo.save_defect_case(self._case("defect-a-2", "run-a", "route-a-2", 20))
        self.repo.save_defect_case(self._case("defect-b-1", "run-b", "route-b-1", 15))
        self.repo.save_defect_case(self._case("defect-a-1", "run-a", "route-a-1", 10))

        reconstructed = PostgresDefectClosureRepository(self.store)
        rows = reconstructed.list_for_test_run("run-a")

        self.assertEqual(("defect-a-1", "defect-a-2"), tuple(item.defect_case_id for item in rows))
        self.assertEqual({"run-a"}, {item.test_run_id for item in rows})
        self.assertEqual((), reconstructed.list_for_test_run("run-missing"))

    def test_blank_test_run_id_is_rejected(self):
        with self.assertRaisesRegex(DefectClosureError, "TEST_RUN_ID_REQUIRED"):
            self.repo.list_for_test_run("   ")


if __name__ == "__main__":
    unittest.main()
