import unittest

from rc8_center.mission_service import CenterMissionService
from rc8_runtime import RC8ContractError
from rc8_runtime.mission_graph import MissionStageType, validate_edge


class _MissionRepository:
    def __init__(self):
        self.stages = {}
        self.touched = False

    def get_stage(self, stage_instance_id):
        self.touched = True
        return self.stages.get(stage_instance_id)

    def list_stages(self, test_run_id):
        self.touched = True
        return [stage for stage in self.stages.values() if stage.test_run_id == test_run_id]

    def list_evaluations(self, test_run_id):
        self.touched = True
        return []

    def upsert_stage(self, stage):
        self.touched = True
        self.stages[stage.stage_instance_id] = stage


class N8RouteAuthorityTest(unittest.TestCase):
    def test_generic_registration_rejects_n8_controlled_recovery_stages_before_repository_access(self):
        for stage_type in (
            MissionStageType.DELTA_REPAIR,
            MissionStageType.TARGETED_REEXECUTION,
        ):
            repo = _MissionRepository()
            service = CenterMissionService(repo)
            with self.assertRaisesRegex(
                RC8ContractError,
                "N8_ROUTE_AUTHORITY_REQUIRED:%s" % stage_type.value,
            ):
                service.register_stage(
                    test_run_id="run-1",
                    stage_instance_id="stage-%s" % stage_type.value.lower(),
                    stage_type=stage_type,
                    scope_version="scope:v1",
                    attempt_no=1,
                )
            self.assertFalse(repo.touched, "N8 authority must fail closed before repository mutation/read")

    def test_normal_stage_registration_remains_available(self):
        repo = _MissionRepository()
        service = CenterMissionService(repo)
        stage = service.register_stage(
            test_run_id="run-1",
            stage_instance_id="stage-scope",
            stage_type=MissionStageType.SCOPE_INTAKE,
            scope_version="scope:v1",
            attempt_no=1,
        )
        self.assertEqual(MissionStageType.SCOPE_INTAKE.value, stage.stage_type)
        self.assertIs(stage, repo.stages[stage.stage_instance_id])

    def test_graph_keeps_recovery_semantics_while_center_registration_is_n8_controlled(self):
        validate_edge(
            MissionStageType.FAILURE_COVERAGE_EVALUATION.value,
            MissionStageType.DELTA_REPAIR.value,
        )
        validate_edge(
            MissionStageType.DELTA_REPAIR.value,
            MissionStageType.TARGETED_REEXECUTION.value,
        )
        validate_edge(
            MissionStageType.TARGETED_REEXECUTION.value,
            MissionStageType.FAILURE_COVERAGE_EVALUATION.value,
        )


if __name__ == "__main__":
    unittest.main()
