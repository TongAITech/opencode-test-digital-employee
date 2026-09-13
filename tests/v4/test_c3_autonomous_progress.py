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
        before = self.service.status(mission)
        revision = before["plan"]["current_revision_id"]
        task_ids = [x["task_id"] for x in before["tasks"]]
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

        after = restarted.status(mission)
        self.assertEqual(after["plan"]["current_revision_id"], revision,
                         "Runtime must not author a semantic PlanRevision")
        self.assertEqual([x["task_id"] for x in after["tasks"]], task_ids,
                         "Runtime must not invent a Diagnosis Task; Planner owns WHAT")
        messages = [m for m in self.provider.messages if m["session_id"] == first_session]
        self.assertEqual(len(messages), 1, "same no-progress generation must not duplicate Planner prompt")
        self.assertTrue(messages[0]["text"].startswith("AITEST_CANONICAL_REPLANNING_CONTEXT\n"))
        self.assertIn('"required_next_action": "AUTHOR_PLAN_REVISION"', messages[0]["text"])

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
