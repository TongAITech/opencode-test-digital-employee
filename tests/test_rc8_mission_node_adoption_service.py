import unittest
from dataclasses import replace

from rc8_center.control_plane import CenterControlError
from rc8_center.mission_node_adoption_service import CenterMissionNodeAdoptionService
from rc8_center.reality_snapshot import (
    CapabilitySnapshot,
    MemoryRealitySnapshotRepository,
    MissionNodeRealityBinding,
    RealitySnapshot,
)
from rc8_runtime.contracts import CapabilityState
from rc8_runtime.governance import StageInstance, StageState, StatusScope, SufficiencyEvaluation, SufficiencyResult
from rc8_runtime.mission_graph import MissionStageType
from rc8_runtime.mission_nodes import MissionNodeAdoptionGraph, MissionNodeState, MissionNodeType


class FakeGovernanceRepository:
    def __init__(self, stages=(), evaluations=()):
        self.stages = list(stages)
        self.evaluations = list(evaluations)

    def list_stages(self, test_run_id):
        return [value for value in self.stages if value.test_run_id == test_run_id]

    def list_evaluations(self, test_run_id):
        return [value for value in self.evaluations if value.test_run_id == test_run_id]


class MissionNodeAdoptionServiceTest(unittest.TestCase):
    def setUp(self):
        self.reality_repo = MemoryRealitySnapshotRepository()
        self.snapshot = RealitySnapshot(
            snapshot_id="reality:run-1:scope-v1:v1",
            test_run_id="run-1",
            scope_version="scope-v1",
            snapshot_version=1,
            source_revision="sha-1",
            environment_refs=("env://pfc/test",),
            capabilities=(
                CapabilitySnapshot(
                    requirement_id="req-dsh",
                    capability_id="dsh",
                    execution_node_id="pc-a",
                    state=CapabilityState.VERIFIED,
                    probe_ref="probe://dsh/1",
                    evidence_refs=("evidence://dsh/1",),
                    verified_at=10,
                ),
            ),
            blockers=(),
            fingerprint="f" * 64,
            created_at=20,
        )
        self.reality_repo.save_reality_snapshot(self.snapshot)

    def _node(self, node_type):
        node = MissionNodeAdoptionGraph("run-1", "scope-v1").node(node_type)
        return replace(node, state=MissionNodeState.IN_PROGRESS)

    def _binding(self, node, snapshot=None):
        snapshot = snapshot or self.snapshot
        return MissionNodeRealityBinding(
            binding_id="binding:%s" % node.node_type.value,
            test_run_id=node.test_run_id,
            mission_node_id=node.mission_node_id,
            mission_node_type=node.node_type,
            reality_snapshot_id=snapshot.snapshot_id,
            reality_fingerprint=snapshot.fingerprint,
        )

    def _stage(self, stage_type, attempt_no=1, state=StageState.COMPLETED, output_refs=None):
        if output_refs is None:
            output_refs = () if stage_type in {
                MissionStageType.REQUIREMENT_SUFFICIENCY,
                MissionStageType.CODE_SUFFICIENCY,
                MissionStageType.DESIGN_SUFFICIENCY,
            } else ("evidence://%s/%s" % (stage_type.value.lower(), attempt_no),)
        return StageInstance(
            stage_instance_id="stage:%s:%s" % (stage_type.value, attempt_no),
            test_run_id="run-1",
            stage_type=stage_type.value,
            scope_version="scope-v1",
            attempt_no=attempt_no,
            state=state,
            output_refs=tuple(output_refs),
        )

    def _evaluation(self, stage, *, authoritative=True, result=SufficiencyResult.SUFFICIENT, evaluated_at=30):
        return SufficiencyEvaluation(
            evaluation_id="eval:%s:%s" % (stage.stage_instance_id, evaluated_at),
            test_run_id="run-1",
            scope=StatusScope.STAGE,
            subject_id=stage.stage_instance_id,
            evaluator_id="RC8_CENTER_SUFFICIENCY_LEDGER" if authoritative else "worker-1",
            policy_version="center-ledger:v1" if authoritative else "worker:v1",
            result=result,
            dimension_refs=("dimension://1",),
            evidence_refs=("ledger:%s" % stage.stage_instance_id,) if authoritative else ("evidence://worker/claim",),
            explanation="evidence-backed sufficiency",
            evaluated_at=evaluated_at,
        )

    def _service(self, stages, evaluations):
        return CenterMissionNodeAdoptionService(FakeGovernanceRepository(stages, evaluations), self.reality_repo)

    def test_n2_reuses_existing_requirement_stages_and_center_gate_truth(self):
        analysis = self._stage(MissionStageType.REQUIREMENT_ANALYSIS)
        suff = self._stage(MissionStageType.REQUIREMENT_SUFFICIENCY)
        service = self._service((analysis, suff), (self._evaluation(suff),))
        node = self._node(MissionNodeType.N2_REQUIREMENT_ANALYSIS)
        result = service.build_delivery(
            node=node,
            reality_binding=self._binding(node),
            package_id="pkg-n2",
            attempt_ref="attempt-n2-1",
        )
        self.assertEqual((analysis.stage_instance_id, suff.stage_instance_id), result.stage_instance_ids)
        self.assertIn("ledger:%s" % suff.stage_instance_id, result.package.evidence_refs)
        self.assertIn("reality-snapshot:%s" % self.snapshot.snapshot_id, result.package.output_refs)

    def test_n3_rejects_worker_claimed_code_sufficiency(self):
        analysis = self._stage(MissionStageType.CODE_ANALYSIS)
        suff = self._stage(MissionStageType.CODE_SUFFICIENCY)
        service = self._service((analysis, suff), (self._evaluation(suff, authoritative=False),))
        node = self._node(MissionNodeType.N3_CODE_ANALYSIS)
        with self.assertRaisesRegex(CenterControlError, "NOT_CENTER_AUTHORITATIVE"):
            service.build_delivery(
                node=node,
                reality_binding=self._binding(node),
                package_id="pkg-n3",
                attempt_ref="attempt-n3-1",
            )

    def test_latest_stage_attempt_must_be_completed_even_if_older_attempt_was_green(self):
        old_analysis = self._stage(MissionStageType.CODE_ANALYSIS, attempt_no=1)
        new_analysis = self._stage(MissionStageType.CODE_ANALYSIS, attempt_no=2, state=StageState.EXECUTING)
        suff = self._stage(MissionStageType.CODE_SUFFICIENCY)
        service = self._service((old_analysis, new_analysis, suff), (self._evaluation(suff),))
        node = self._node(MissionNodeType.N3_CODE_ANALYSIS)
        with self.assertRaisesRegex(CenterControlError, "LATEST_STAGE_NOT_COMPLETED"):
            service.build_delivery(
                node=node,
                reality_binding=self._binding(node),
                package_id="pkg-n3",
                attempt_ref="attempt-n3-2",
            )

    def test_stale_reality_binding_cannot_create_delivery(self):
        analysis = self._stage(MissionStageType.REQUIREMENT_ANALYSIS)
        suff = self._stage(MissionStageType.REQUIREMENT_SUFFICIENCY)
        service = self._service((analysis, suff), (self._evaluation(suff),))
        node = self._node(MissionNodeType.N2_REQUIREMENT_ANALYSIS)
        old_binding = self._binding(node)
        newer = replace(
            self.snapshot,
            snapshot_id="reality:run-1:scope-v1:v2",
            snapshot_version=2,
            fingerprint="e" * 64,
            source_revision="sha-2",
        )
        self.reality_repo.save_reality_snapshot(newer)
        with self.assertRaisesRegex(CenterControlError, "STALE_REALITY_BINDING"):
            service.build_delivery(
                node=node,
                reality_binding=old_binding,
                package_id="pkg-n2",
                attempt_ref="attempt-n2-1",
            )

    def test_n4_requires_risk_design_and_center_design_sufficiency(self):
        risk = self._stage(MissionStageType.RISK_TEST_MODEL)
        design = self._stage(MissionStageType.TEST_DESIGN)
        suff = self._stage(MissionStageType.DESIGN_SUFFICIENCY)
        service = self._service((risk, design, suff), (self._evaluation(suff),))
        node = self._node(MissionNodeType.N4_TEST_DESIGN)
        result = service.build_delivery(
            node=node,
            reality_binding=self._binding(node),
            package_id="pkg-n4",
            attempt_ref="attempt-n4-1",
        )
        self.assertEqual(3, len(result.stage_instance_ids))
        self.assertEqual(("eval:%s:30" % suff.stage_instance_id,), result.sufficiency_evaluation_ids)

    def test_missing_required_stage_and_missing_activity_evidence_fail_closed(self):
        suff = self._stage(MissionStageType.REQUIREMENT_SUFFICIENCY)
        node = self._node(MissionNodeType.N2_REQUIREMENT_ANALYSIS)
        service = self._service((suff,), (self._evaluation(suff),))
        with self.assertRaisesRegex(CenterControlError, "REQUIRED_STAGE_MISSING"):
            service.build_delivery(node=node, reality_binding=self._binding(node), package_id="p", attempt_ref="a")

        analysis = self._stage(MissionStageType.REQUIREMENT_ANALYSIS, output_refs=())
        service = self._service((analysis, suff), (self._evaluation(suff),))
        with self.assertRaisesRegex(CenterControlError, "ACTIVITY_STAGE_EVIDENCE_MISSING"):
            service.build_delivery(node=node, reality_binding=self._binding(node), package_id="p", attempt_ref="a")

    def test_non_green_sufficiency_never_builds_delivery(self):
        analysis = self._stage(MissionStageType.REQUIREMENT_ANALYSIS)
        suff = self._stage(MissionStageType.REQUIREMENT_SUFFICIENCY)
        evaluation = self._evaluation(suff, result=SufficiencyResult.INSUFFICIENT)
        service = self._service((analysis, suff), (evaluation,))
        node = self._node(MissionNodeType.N2_REQUIREMENT_ANALYSIS)
        with self.assertRaisesRegex(CenterControlError, "SUFFICIENCY_NOT_GREEN"):
            service.build_delivery(node=node, reality_binding=self._binding(node), package_id="p", attempt_ref="a")

    def test_only_n2_n3_n4_are_supported_by_this_adapter(self):
        service = self._service((), ())
        node = self._node(MissionNodeType.N5_TEST_DATA_PRECONDITIONS)
        with self.assertRaisesRegex(CenterControlError, "ADOPTION_UNSUPPORTED"):
            service.build_delivery(node=node, reality_binding=self._binding(node), package_id="p", attempt_ref="a")


if __name__ == "__main__":
    unittest.main()
