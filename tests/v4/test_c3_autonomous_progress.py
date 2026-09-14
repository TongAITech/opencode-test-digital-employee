"""C3 autonomous Mission progress / no-progress replanning regressions."""
from __future__ import annotations

import tempfile
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "workspace-template/ai-test/runtime"))

from aitest_runtime.autonomous_orchestration import FakeOpenCodeSessionProvider
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.dispatch_receipts import business_cursor
from aitest_runtime.durable_core import canonical_sha256
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService


def request(key: str):
    return {
        "intake_id": key,
        "operation": "CREATE",
        "scope": {"mode": "EXPLICIT_SET", "project_id": "PFC", "version": "C3-" + key, "requirements": ["REQ-C3"]},
        "goal": {"title": "C3 autonomous progress", "intent": "continue without user clock", "constraints": []},
        "source": {"kind": "USER", "source_ref": "c3:" + key,
                   "source_digest": canonical_sha256({"key": key}),
                   "observed_at": "2026-09-14T01:00:00Z", "valid_until": None, "source_precedence": 1},
        "actor": {"type": "USER", "id": "c3-test"},
        "resolution": {"resolution_id": "resolution:" + key,
                       "request_digest": canonical_sha256({"resolution": key}),
                       "snapshot_id": "snapshot:" + key,
                       "fact_set_digest": canonical_sha256({"facts": []}),
                       "status": "RESOLVED", "reason_code": None,
                       "source_refs": ["c3:" + key], "valid_until": "2026-09-15T01:00:00Z"},
    }


def one_task():
    return {
        "objective": "one bounded worker",
        "tasks": [{
            "task_key": "worker",
            "intent": "perform bounded execution",
            "acceptance_criteria": [{"id": "done", "description": "complete work"}],
            "routing": {"role": "EXECUTOR",
                        "required_capabilities": ["OPENCODE_AGENT_SESSION", "TASK_OUTCOME_REPORT"],
                        "isolation_policy": "DEDICATED_TASK_SESSION",
                        "parallelism_policy": "SERIAL"},
        }],
        "dependencies": [],
    }


class C3AutonomousProgressTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runtime = create_canonical_runtime(self.root, db_path=self.root / "runtime-spine.db")
        self.provider = FakeOpenCodeSessionProvider(self.root)
        self.service = G21AutonomousOrchestrationService(self.runtime, self.root, session_provider=self.provider)

    def tearDown(self):
        self.tmp.cleanup()

    def _active_worker(self, key: str):
        started = self.service.start_test(request(key))
        mission = started["intake"]["intake"]["mission_id"]
        planned = self.service.propose_plan(mission, one_task())
        worker = planned["next"]
        return mission, worker

    def test_same_no_progress_cursor_opens_one_replanning_session_and_survives_restart(self):
        mission, worker = self._active_worker("dedupe")
        _composed_before, graph_before, _goal_before, plan_before = self.service._active_plan_context(mission)
        self.assertIsNotNone(plan_before)
        revision = plan_before.current_revision_id
        task_ids = [
            task.task_id for task in graph_before.tasks
            if task.plan_id == plan_before.plan_id and task.plan_revision_id == plan_before.current_revision_id
        ]
        cursor = business_cursor(self.runtime, mission)

        first = self.service._handle_no_progress(
            mission, task_id=worker["task_id"], session_id=worker["external_session"]["session_id"],
            reason="AUTO_CONTINUE_NO_BUSINESS_PROGRESS", cursor=cursor,
        )
        self.assertEqual(first["status"], "REPLAN_DISPATCHED")
        self.assertEqual(first["truth_source"], "R1_EVENT_STREAM")
        self.assertEqual(first["agent"], "aitest-planner")

        state = self.service.session_control.state(mission)
        records = list(state.progress_records)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].phase, "REPLANNING")
        replans = [x for x in state.provisions if x.phase == "REPLANNING"]
        self.assertEqual(len(replans), 1)
        self.assertEqual(replans[0].status, "BOUND")
        first_session = replans[0].external_session_id
        self.assertIsNotNone(first_session)

        again = self.service._handle_no_progress(
            mission, task_id=worker["task_id"], session_id=worker["external_session"]["session_id"],
            reason="AUTO_CONTINUE_NO_BUSINESS_PROGRESS", cursor=cursor,
        )
        self.assertEqual(again["status"], "REPLAN_IN_PROGRESS")
        self.assertEqual(again["session_id"], first_session)
        self.assertEqual(len([x for x in self.service.session_control.state(mission).provisions if x.phase == "REPLANNING"]), 1)

        restarted = G21AutonomousOrchestrationService(
            create_canonical_runtime(self.root, db_path=self.root / "runtime-spine.db"),
            self.root, session_provider=self.provider,
        )
        recovered = restarted._handle_no_progress(
            mission, task_id=worker["task_id"], session_id=worker["external_session"]["session_id"],
            reason="AUTO_CONTINUE_NO_BUSINESS_PROGRESS", cursor=cursor,
        )
        self.assertEqual(recovered["status"], "REPLAN_IN_PROGRESS")
        self.assertEqual(recovered["session_id"], first_session)
        self.assertEqual(len([x for x in self.provider.list_sessions() if "Replan" in x.title]), 1)

        _composed_after, graph_after, _goal_after, plan_after = restarted._active_plan_context(mission)
        self.assertIsNotNone(plan_after)
        self.assertEqual(plan_after.current_revision_id, revision,
                         "Runtime must not author a semantic PlanRevision")
        after_task_ids = [
            task.task_id for task in graph_after.tasks
            if task.plan_id == plan_after.plan_id and task.plan_revision_id == plan_after.current_revision_id
        ]
        self.assertEqual(after_task_ids, task_ids,
                         "Runtime must not invent a Diagnosis Task; Planner owns WHAT")
        messages = [m for m in self.provider.messages if m["session_id"] == first_session]
        self.assertEqual(len(messages), 1, "same no-progress generation must not duplicate Planner prompt")
        self.assertTrue(messages[0]["text"].startswith("AITEST_CANONICAL_REPLANNING_CONTEXT\n"))
        self.assertIn('"required_next_action": "AUTHOR_PLAN_REVISION"', messages[0]["text"])


    def test_replanning_session_rotates_under_pressure_and_reuses_successor(self):
        mission, worker = self._active_worker("replan-rotation")
        cursor = business_cursor(self.runtime, mission)
        first = self.service._handle_no_progress(
            mission, task_id=worker["task_id"], session_id=worker["external_session"]["session_id"],
            reason="AUTO_CONTINUE_NO_BUSINESS_PROGRESS", cursor=cursor,
        )
        predecessor = first["session_id"]
        progress_id = first["progress_id"]
        before = self.service.session_control.state(mission).progress(progress_id)
        self.assertEqual(before.phase, "REPLANNING")
        lineage = before.replan_lineage
        self.assertTrue(lineage.startswith("replanning:"))

        self.provider.set_observation(
            predecessor, activity_state="idle", reachable=True, healthy=True,
            context_used=92000, context_limit=100000, context_utilization=0.92,
            message_count=20, compaction_count=0,
        )
        tick = self.service.supervise_once()
        rotated = [
            item for item in tick["supervision"]
            if item.get("phase") == "REPLANNING"
               and item.get("result", {}).get("status") == "ROTATED"
        ]
        self.assertEqual(len(rotated), 1)
        rotation = rotated[0]["result"]
        self.assertEqual(rotation["predecessor_session_id"], predecessor)
        successor = rotation["successor_session_id"]
        self.assertNotEqual(successor, predecessor)
        self.assertNotIn(predecessor, self.provider.sessions)
        self.assertIn(successor, self.provider.sessions)

        state = self.service.session_control.state(mission)
        progress = state.progress(progress_id)
        self.assertEqual(progress.phase, "REPLANNING")
        self.assertEqual(progress.replan_lineage, lineage)
        self.assertEqual(progress.replan_session_id, successor)
        replanning_provisions = [x for x in state.provisions if x.phase in {"REPLANNING","REPLANNING_ROTATION"}]
        self.assertEqual(len([x for x in replanning_provisions if x.status == "BOUND"]), 2)
        self.assertEqual(
            {x.root_attempt_id for x in replanning_provisions},
            {lineage},
            "rotation must preserve the progress-bound replanning lineage",
        )

        # Re-running the same no-progress generation must continue the rotated
        # successor, not resurrect the initial replanning Session.
        again = self.service._handle_no_progress(
            mission, task_id=worker["task_id"], session_id=worker["external_session"]["session_id"],
            reason="AUTO_CONTINUE_NO_BUSINESS_PROGRESS", cursor=cursor,
        )
        self.assertEqual(again["status"], "REPLAN_IN_PROGRESS")
        self.assertEqual(again["session_id"], successor)
        self.assertEqual(len([x for x in self.provider.list_sessions() if "Replan" in x.title]), 1)



    def test_successful_plan_revision_advances_business_cursor_and_resolves_stalled_generation(self):
        mission, worker = self._active_worker("replan-progress")
        stalled_cursor = business_cursor(self.runtime, mission)
        first = self.service._handle_no_progress(
            mission, task_id=worker["task_id"], session_id=worker["external_session"]["session_id"],
            reason="AUTO_CONTINUE_NO_BUSINESS_PROGRESS", cursor=stalled_cursor,
        )
        progress_id = first["progress_id"]
        replan_session = first["session_id"]
        self.assertEqual(self.service.session_control.state(mission).progress(progress_id).phase, "REPLANNING")

        revised = self.service.propose_plan(mission, {
            "objective": "replace stalled execution with a bounded diagnosis step",
            "tasks": [{
                "task_key": "diagnose-stall",
                "intent": "diagnose why the prior execution made no business progress",
                "acceptance_criteria": [{"id": "diagnosed", "description": "produce a bounded diagnosis"}],
                "routing": {
                    "role": "DIAGNOSIS",
                    "required_capabilities": ["OPENCODE_AGENT_SESSION", "TASK_OUTCOME_REPORT"],
                    "isolation_policy": "DEDICATED_TASK_SESSION",
                    "parallelism_policy": "SERIAL",
                },
            }],
            "dependencies": [],
        })
        self.assertEqual(revised["status"], "PASS")
        advanced = business_cursor(self.runtime, mission)
        self.assertGreater(advanced, stalled_cursor, "a governed PlanRevision is real business progress")
        progress = self.service.session_control.state(mission).progress(progress_id)
        self.assertEqual(progress.phase, "RESOLVED")
        self.assertEqual(progress.replan_session_id, replan_session)
        self.assertNotIn(replan_session, self.provider.sessions)




    def test_replan_no_change_is_not_business_progress_and_does_not_resolve_stall(self):
        mission, worker = self._active_worker("replan-no-change")
        stalled_cursor = business_cursor(self.runtime, mission)
        first = self.service._handle_no_progress(
            mission, task_id=worker["task_id"], session_id=worker["external_session"]["session_id"],
            reason="AUTO_CONTINUE_NO_BUSINESS_PROGRESS", cursor=stalled_cursor,
        )
        progress_id = first["progress_id"]
        replan_session = first["session_id"]

        same = self.service.propose_plan(mission, one_task())
        self.assertEqual(same["status"], "PASS")
        self.assertTrue(same["stalled_replan_no_change"])
        self.assertFalse(same["semantic_business_progress"])
        self.assertIsNone(same["autonomous_handoff"])
        self.assertEqual(business_cursor(self.runtime, mission), stalled_cursor)
        progress = self.service.session_control.state(mission).progress(progress_id)
        self.assertEqual(progress.phase, "REPLANNING")
        self.assertEqual(progress.replan_session_id, replan_session)
        self.assertIn(replan_session, self.provider.sessions)


    def test_replanner_gets_one_auto_wake_then_rotates_and_retry_does_not_consume_budget(self):
        mission, worker = self._active_worker("replanner-wake")
        cursor = business_cursor(self.runtime, mission)
        first = self.service._handle_no_progress(
            mission, task_id=worker["task_id"], session_id=worker["external_session"]["session_id"],
            reason="AUTO_CONTINUE_NO_BUSINESS_PROGRESS", cursor=cursor,
        )
        predecessor = first["session_id"]
        progress_id = first["progress_id"]
        self.assertEqual(len([m for m in self.provider.messages if m["session_id"] == predecessor]), 1)

        wake = self.service.progress_once(mission)
        self.assertEqual(wake["status"], "AUTO_CONTINUE_REPLANNING")
        self.assertTrue(wake["retry_budget_consumed"])
        self.assertEqual(len([m for m in self.provider.messages if m["session_id"] == predecessor]), 2)

        rotated = self.service.progress_once(mission)
        self.assertEqual(rotated["status"], "ROTATED")
        self.assertEqual(rotated["phase"], "REPLANNING")
        self.assertEqual(rotated["predecessor_session_id"], predecessor)
        successor = rotated["successor_session_id"]
        self.assertNotEqual(successor, predecessor)
        self.assertNotIn(predecessor, self.provider.sessions)
        self.assertEqual(self.service.session_control.state(mission).progress(progress_id).replan_session_id, successor)
        self.assertEqual(len([m for m in self.provider.messages if m["session_id"] == successor]), 1)

        # Host/provider retry is an external backoff barrier. It must not spend
        # the successor's one AUTO_CONTINUE allowance.
        self.provider.set_observation(successor, activity_state="retry")
        before_messages = len(self.provider.messages)
        before_rotations = len(self.service.session_control.state(mission).rotations)
        waiting = self.service.progress_once(mission)
        self.assertEqual(waiting["status"], "WAIT")
        self.assertEqual(waiting["reason"], "WAIT_BACKOFF")
        self.assertFalse(waiting["retry_budget_consumed"])
        self.assertEqual(len(self.provider.messages), before_messages)
        self.assertEqual(len(self.service.session_control.state(mission).rotations), before_rotations)

        self.provider.set_observation(successor, activity_state="idle")
        next_wake = self.service.progress_once(mission)
        self.assertEqual(next_wake["status"], "AUTO_CONTINUE_REPLANNING")
        self.assertEqual(next_wake["session_id"], successor)

    def test_replanner_repeated_failure_budget_blocks_after_three_clean_successors(self):
        mission, worker = self._active_worker("replanner-budget")
        cursor = business_cursor(self.runtime, mission)
        first = self.service._handle_no_progress(
            mission, task_id=worker["task_id"], session_id=worker["external_session"]["session_id"],
            reason="AUTO_CONTINUE_NO_BUSINESS_PROGRESS", cursor=cursor,
        )
        progress_id = first["progress_id"]

        successors = [first["session_id"]]
        for _ in range(3):
            wake = self.service.progress_once(mission)
            self.assertEqual(wake["status"], "AUTO_CONTINUE_REPLANNING")
            rotated = self.service.progress_once(mission)
            self.assertEqual(rotated["status"], "ROTATED")
            successors.append(rotated["successor_session_id"])

        final_wake = self.service.progress_once(mission)
        self.assertEqual(final_wake["status"], "AUTO_CONTINUE_REPLANNING")
        exhausted = self.service.progress_once(mission)
        self.assertEqual(exhausted["status"], "WAIT")
        self.assertEqual(exhausted["reason"], "DIAGNOSIS_REQUIRED_REPEATED_REPLANNER_FAILURE")
        self.assertTrue(exhausted["retry_budget_exhausted"])
        self.assertEqual(exhausted["recovery_count"], 3)
        progress = self.service.session_control.state(mission).progress(progress_id)
        self.assertEqual(progress.phase, "BLOCKED")
        self.assertEqual(progress.failure_signature, exhausted["failure_signature"])
        self.assertEqual(len(set(successors)), 4)
        self.assertEqual(len(self.service.session_control.state(mission).rotations), 3)


    def test_busy_and_retry_workers_do_not_create_replanning_session(self):
        for activity in ("busy", "retry"):
            with self.subTest(activity=activity):
                with tempfile.TemporaryDirectory() as td:
                    root = Path(td)
                    runtime = create_canonical_runtime(root, db_path=root / "spine.db")
                    provider = FakeOpenCodeSessionProvider(root)
                    service = G21AutonomousOrchestrationService(runtime, root, session_provider=provider)
                    started = service.start_test(request("barrier-" + activity))
                    mission = started["intake"]["intake"]["mission_id"]
                    worker = service.propose_plan(mission, one_task())["next"]
                    sid = worker["external_session"]["session_id"]
                    provider.set_observation(sid, activity_state=activity, reachable=True, healthy=True)
                    tick = service.progress_once(mission)
                    self.assertEqual(tick["status"], "PROGRESS_CHECKED")
                    reasons = [x.get("reason") for x in tick["wakes"]]
                    self.assertIn("WAIT_BUSY" if activity == "busy" else "WAIT_BACKOFF", reasons)
                    self.assertEqual(service.session_control.state(mission).progress_records, ())
                    self.assertEqual([x for x in service.session_control.state(mission).provisions if x.phase == "REPLANNING"], [])


if __name__ == "__main__":
    unittest.main()
