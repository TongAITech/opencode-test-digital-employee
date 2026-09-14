"""C3 PLAN_COMPLETE quality convergence regressions.

These tests use the canonical R1 WorkGraph, real G3 coverage fact path, final
G4 service/controller and Core Mission transitions. FakeOpenCode replaces only
the external Host transport.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "workspace-template/ai-test/runtime"))

from aitest_runtime.autonomous_orchestration import FakeOpenCodeSessionProvider
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.durable_core import MissionStatus, canonical_sha256
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
from aitest_runtime.g3.coverage import CoverageProviderResult, MappingCoveragePlatformProvider
from aitest_runtime.g3.service import G3TestingIntelligenceService
from aitest_runtime.g4 import G4RealExecutionService


def request(key: str):
    return {
        "intake_id": key,
        "operation": "CREATE",
        "scope": {"mode": "EXPLICIT_SET", "project_id": "PFC", "version": "C3Q-" + key, "requirements": ["REQ-C3-Q"]},
        "goal": {"title": "C3 quality convergence", "intent": "complete only after real quality convergence", "constraints": []},
        "source": {"kind": "USER", "source_ref": "c3q:" + key,
                   "source_digest": canonical_sha256({"key": key}),
                   "observed_at": "2026-09-14T02:00:00Z", "valid_until": None, "source_precedence": 1},
        "actor": {"type": "USER", "id": "c3-quality-test"},
        "resolution": {"resolution_id": "resolution:" + key,
                       "request_digest": canonical_sha256({"resolution": key}),
                       "snapshot_id": "snapshot:" + key,
                       "fact_set_digest": canonical_sha256({"facts": []}),
                       "status": "RESOLVED", "reason_code": None,
                       "source_refs": ["c3q:" + key], "valid_until": "2026-09-15T02:00:00Z"},
    }


def one_task():
    return {
        "objective": "one bounded execution task",
        "tasks": [{
            "task_key": "quality-worker",
            "intent": "produce execution result before quality convergence",
            "acceptance_criteria": [{"id": "done", "description": "execution completes"}],
            "routing": {
                "role": "EXECUTOR",
                "required_capabilities": ["OPENCODE_AGENT_SESSION", "TASK_OUTCOME_REPORT"],
                "isolation_policy": "DEDICATED_TASK_SESSION",
                "parallelism_policy": "SERIAL",
            },
        }],
        "dependencies": [],
    }


def coverage_snapshot(pct: float, seq: int):
    return {
        "snapshot_id": f"c3-quality:{seq}",
        "application_id": "cfg-data",
        "target_version": "V2",
        "baseline_label": "master",
        "baseline_commit": "UNKNOWN",
        "target_commit": f"{seq:040x}",
        "observed_at": f"2026-09-14T02:{seq:02d}:00Z",
        "coverage_semantics": "BANK_EFFECTIVE_INCREMENTAL",
        "source_identity": f"bank:cfg-data:V2:{seq}",
        "effective_incremental_coverage_pct": pct,
        "effective_changed_lines_total": 100,
        "covered_changed_lines": int(pct),
        "uncovered_changed_lines": 100 - int(pct),
        "details": [{"level": "APPLICATION", "application_id": "cfg-data", "coverage_pct": pct}],
    }


class C3PlanCompleteConvergenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runtime = create_canonical_runtime(self.root, db_path=self.root / "runtime-spine.db")
        self.provider = FakeOpenCodeSessionProvider(self.root)
        self.service = G21AutonomousOrchestrationService(self.runtime, self.root, session_provider=self.provider)

    def tearDown(self):
        self.tmp.cleanup()

    def _mission(self, key: str):
        started = self.service.start_test(request(key))
        mission = started["intake"]["intake"]["mission_id"]
        worker = self.service.propose_plan(mission, one_task())["next"]
        return mission, worker

    def _finish_worker(self, mission: str, worker: dict):
        return self.service.report_task_outcome(
            mission,
            task_id=worker["task_id"],
            attempt_id=worker["attempt"]["attempt_id"],
            session_id=worker["external_session"]["session_id"],
            outcome="SUCCEEDED",
            summary="execution completed; quality convergence remains separate",
        )

    def _goal(self, mission: str, goal_id: str = "quality"):
        g4 = G4RealExecutionService(self.runtime, orchestration=self.service)
        g4.create_goal(mission, {
            "goal_id": goal_id,
            "project_id": "PFC",
            "release_id": "R2",
            "affected_applications": ["cfg-data"],
            "affected_application_target_versions": {"cfg-data": "V2"},
            "coverage_policy": {"target_pct": 95},
        })
        return g4

    def _coverage(self, mission: str, g4: G4RealExecutionService, pct: float, seq: int):
        g3 = G3TestingIntelligenceService(
            self.runtime,
            coverage_provider=MappingCoveragePlatformProvider(
                CoverageProviderResult("AVAILABLE", ("AGGREGATE",), snapshot=coverage_snapshot(pct, seq))
            ),
            orchestration=self.service,
        )
        acquired = g3.acquire_coverage(
            mission,
            {"platform_profile_id": "bankcov", "authenticated_context_ref": "auth", "method": "API"},
            {"application_id": "cfg-data", "target_version": "V2", "baseline_label": "master"},
        )
        g4.record_coverage_from_g3(mission, {
            "measurement_id": f"m{seq}",
            "goal_id": "quality",
            "state": "AVAILABLE",
            "g3_snapshot_fact_id": acquired["snapshot"]["fact_id"],
        })

    def test_plan_complete_without_testing_goal_replans_and_dedupes_generation(self):
        mission, worker = self._mission("missing-goal")
        self.assertEqual(self._finish_worker(mission, worker)["next"]["status"], "PLAN_COMPLETE")

        first = self.service.progress_once(mission)
        self.assertEqual(first["status"], "REPLAN_DISPATCHED")
        self.assertEqual(first["reason"] if "reason" in first else "PLAN_COMPLETE_TESTING_GOAL_MISSING",
                         "PLAN_COMPLETE_TESTING_GOAL_MISSING")
        self.assertEqual(self.runtime.replay_composed(mission).core_state.mission.status, MissionStatus.ACTIVE)
        state = self.service.session_control.state(mission)
        progress = [p for p in state.progress_records if p.reason == "PLAN_COMPLETE_TESTING_GOAL_MISSING"]
        self.assertEqual(len(progress), 1)
        session = progress[0].replan_session_id
        self.assertTrue(session)

        again = self.service.progress_once(mission)
        self.assertEqual(again["status"], "REPLAN_IN_PROGRESS")
        self.assertEqual(again["session_id"], session)
        state2 = self.service.session_control.state(mission)
        self.assertEqual(len([p for p in state2.progress_records if p.reason == "PLAN_COMPLETE_TESTING_GOAL_MISSING"]), 1)

    def test_plan_complete_missing_measurement_waits_without_self_exciting_replan(self):
        mission, worker = self._mission("missing-measurement")
        g4 = self._goal(mission)
        self._finish_worker(mission, worker)

        first = self.service.progress_once(mission)
        self.assertEqual(first["status"], "WAIT")
        self.assertEqual(first["reason"], "QUALITY_MEASUREMENT_REQUIRED")
        self.assertEqual(first["g4_status"], "WAITING_MEASUREMENT")
        self.assertEqual(self.service.session_control.state(mission).progress_records, ())
        before_control = len(g4.state(mission).by_kind("GOAL_EVALUATION")) + len(g4.state(mission).by_kind("TESTING_GOAL_STATUS"))

        second = self.service.progress_once(mission)
        self.assertEqual(second["status"], "WAIT")
        self.assertEqual(second["reason"], "QUALITY_MEASUREMENT_REQUIRED")
        self.assertEqual(second["quality_cursor"], first["quality_cursor"])
        self.assertEqual(self.service.session_control.state(mission).progress_records, ())
        after_control = len(g4.state(mission).by_kind("GOAL_EVALUATION")) + len(g4.state(mission).by_kind("TESTING_GOAL_STATUS"))
        self.assertEqual(after_control, before_control, "same quality generation must not emit endless control facts")

    def test_below_target_coverage_replans_and_reuses_same_quality_generation(self):
        mission, worker = self._mission("coverage-gap")
        g4 = self._goal(mission)
        self._coverage(mission, g4, 80, 1)
        self._finish_worker(mission, worker)

        first = self.service.progress_once(mission)
        self.assertEqual(first["status"], "REPLAN_DISPATCHED")
        self.assertEqual(first["g4_status"], "REPLANNING")
        self.assertEqual(self.runtime.replay_composed(mission).core_state.mission.status, MissionStatus.ACTIVE)
        progress = [p for p in self.service.session_control.state(mission).progress_records
                    if p.reason == "PLAN_COMPLETE_G4_REPLANNING"]
        self.assertEqual(len(progress), 1)
        successor = progress[0].replan_session_id

        second = self.service.progress_once(mission)
        self.assertEqual(second["status"], "REPLAN_IN_PROGRESS")
        self.assertEqual(second["session_id"], successor)
        self.assertEqual(second["quality_cursor"], first["quality_cursor"])
        self.assertEqual(len([p for p in self.service.session_control.state(mission).progress_records
                              if p.reason == "PLAN_COMPLETE_G4_REPLANNING"]), 1)

    def test_satisfied_quality_marks_core_goal_achieved_then_completes_mission(self):
        mission, worker = self._mission("satisfied")
        g4 = self._goal(mission)
        self._coverage(mission, g4, 96, 1)
        self._finish_worker(mission, worker)

        result = self.service.progress_once(mission)
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["reason"], "TEST_SUFFICIENT")
        self.assertEqual(result["g4_status"], "SATISFIED")
        composed = self.runtime.replay_composed(mission)
        self.assertEqual(composed.core_state.mission.status, MissionStatus.COMPLETED)
        achieved = [goal for goal in composed.core_state.goals if goal.status.value == "ACHIEVED"]
        self.assertEqual(len(achieved), 1)

        again = self.service.progress_once(mission)
        self.assertEqual(again["status"], "WAIT")
        self.assertEqual(again["reason"], "MISSION_NOT_ACTIVE")


if __name__ == "__main__":
    unittest.main()
