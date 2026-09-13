"""C2 all-role pre-provider admission recovery through the real R1/G2.1 control path.

No model output is synthesized here. Only the external OpenCode transport is
replaced; Mission/Plan/Task/Attempt/Session/Observation/Rotation truth is the
canonical runtime.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "workspace-template/ai-test/runtime"))

from aitest_runtime.autonomous_orchestration import FakeOpenCodeSessionProvider
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.context_admission import admit
from aitest_runtime.durable_core import canonical_sha256
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService


def request(key: str):
    return {
        "intake_id": key,
        "operation": "CREATE",
        "scope": {"mode": "EXPLICIT_SET", "project_id": "PFC", "version": "C2-" + key, "requirements": ["REQ-C2"]},
        "goal": {"title": "C2 multirole", "intent": "prove context successor recovery", "constraints": []},
        "source": {"kind": "USER", "source_ref": "c2:" + key,
                   "source_digest": canonical_sha256({"key": key}),
                   "observed_at": "2026-09-14T00:00:00Z", "valid_until": None, "source_precedence": 1},
        "actor": {"type": "USER", "id": "c2-multirole"},
        "resolution": {"resolution_id": "resolution:" + key,
                       "request_digest": canonical_sha256({"resolution": key}),
                       "snapshot_id": "snapshot:" + key,
                       "fact_set_digest": canonical_sha256({"facts": []}),
                       "status": "RESOLVED", "reason_code": None,
                       "source_refs": ["c2:" + key], "valid_until": "2026-09-15T00:00:00Z"},
    }


def one_task(role: str):
    return {
        "objective": "one " + role + " work unit",
        "tasks": [{
            "task_key": "work-" + role.lower(),
            "intent": "perform bounded " + role + " work",
            "acceptance_criteria": [{"id": "done", "description": "durable task survives session replacement"}],
            "routing": {
                "role": role,
                "required_capabilities": ["OPENCODE_AGENT_SESSION", "TASK_OUTCOME_REPORT"],
                "isolation_policy": "DEDICATED_TASK_SESSION",
                "parallelism_policy": "SERIAL",
            },
        }],
        "dependencies": [],
    }


def blocked(session_id: str, agent: str):
    return {
        "session_id": session_id,
        "agent": agent,
        "context_limit": 8192,
        "max_output_tokens": 1024,
        "system_bytes": 1800,
        "messages_bytes": 4300,
        "tools_bytes": 900,
        "extra_bytes": 200,
        "message_count": 12,
        "tool_count": 4,
    }


def planning_rotation(tick):
    return next(
        item["result"] for item in tick["supervision"]
        if item.get("phase") == "PLANNING" and item.get("result", {}).get("status") == "ROTATED"
    )


def worker_rotation(tick, task_id: str):
    return next(
        item["result"]["rotation"] for item in tick["supervision"]
        if item.get("task_id") == task_id and item.get("result", {}).get("status") == "ROTATED"
    )


class ContextAdmissionMultiRoleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "workspace"
        self.root.mkdir()
        self.runtime = create_canonical_runtime(self.root, db_path=Path(self.tmp.name) / "state/spine.db")
        self.provider = FakeOpenCodeSessionProvider(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_planner_two_consecutive_admission_blocks_keep_same_logical_lineage(self):
        service = G21AutonomousOrchestrationService(self.runtime, self.root, session_provider=self.provider)
        started = service.start_test(request("planner"))
        mission = started["intake"]["intake"]["mission_id"]
        first = started["planner_session"]["external_session"]["session_id"]
        provision = next(p for p in service.session_control.state(mission).provisions if p.role == "PLANNER")
        logical_agent = provision.logical_agent_id

        current = first
        seen = [current]
        for _ in range(2):
            result = admit(blocked(current, "aitest-planner"),
                           runtime=self.runtime, provider=self.provider, root=self.root)
            self.assertEqual(result["status"], "BLOCK")
            self.assertEqual(result["recovery"]["status"], "PRESSURE_RECORDED")
            tick = service.supervise_once()
            rotation = planning_rotation(tick)
            self.assertEqual(rotation["predecessor_session_id"], current)
            current = rotation["successor_session_id"]
            seen.append(current)
            self.assertNotIn(rotation["predecessor_session_id"], self.provider.sessions)
            self.assertIn(current, self.provider.sessions)

        self.assertEqual(len(set(seen)), 3)
        current_provision = next(
            p for p in reversed(service.session_control.state(mission).provisions)
            if p.role == "PLANNER" and p.status == "BOUND"
        )
        self.assertEqual(current_provision.logical_agent_id, logical_agent)
        self.assertEqual(current_provision.external_session_id, current)
        self.assertEqual(len(service.session_control.state(mission).rotations), 2)

    def test_worker_roles_each_survive_two_context_admission_rotations(self):
        roles = (
            "REQUIREMENT_ANALYST",
            "CODE_ANALYST",
            "TEST_STRATEGIST",
            "CASE_DESIGNER",
            "EXECUTOR",
            "EVALUATOR",
        )
        agent_by_role = {
            "REQUIREMENT_ANALYST": "aitest-requirement-analyst",
            "CODE_ANALYST": "aitest-code-analyst",
            "TEST_STRATEGIST": "aitest-test-strategist",
            "CASE_DESIGNER": "aitest-case-designer",
            "EXECUTOR": "aitest-executor",
            "EVALUATOR": "aitest-evaluator",
        }

        for role in roles:
            with self.subTest(role=role):
                # Use an isolated R1 spine per role so one role's lifecycle
                # cannot make another role's result accidentally pass.
                with tempfile.TemporaryDirectory() as td:
                    root = Path(td)
                    runtime = create_canonical_runtime(root, db_path=root / "spine.db")
                    provider = FakeOpenCodeSessionProvider(root)
                    service = G21AutonomousOrchestrationService(runtime, root, session_provider=provider)
                    started = service.start_test(request("role-" + role.lower()))
                    mission = started["intake"]["intake"]["mission_id"]
                    first = service.propose_plan(mission, one_task(role))["next"]
                    task_id = first["task_id"]
                    attempt = first["attempt"]
                    root_attempt_id = attempt["root_attempt_id"]
                    current = first["external_session"]["session_id"]
                    seen = [current]

                    for _ in range(2):
                        result = admit(blocked(current, agent_by_role[role]),
                                       runtime=runtime, provider=provider, root=root)
                        self.assertEqual(result["status"], "BLOCK")
                        self.assertEqual(result["recovery"]["status"], "PRESSURE_RECORDED")
                        tick = service.supervise_once()
                        rotation = worker_rotation(tick, task_id)
                        self.assertEqual(rotation["predecessor_session_id"], current)
                        self.assertEqual(rotation["root_attempt_id"], root_attempt_id)
                        current = rotation["successor_session_id"]
                        seen.append(current)
                        status = service.status(mission)
                        latest = status["execution"]["attempts"][-1]
                        self.assertEqual(latest["root_attempt_id"], root_attempt_id)
                        self.assertEqual(latest["task_id"], task_id)
                        self.assertEqual(latest["runtime_session_id"], current)
                        self.assertNotIn(rotation["predecessor_session_id"], provider.sessions)
                        self.assertIn(current, provider.sessions)

                    self.assertEqual(len(set(seen)), 3)
                    rotations = service.session_control.state(mission).rotations
                    self.assertEqual(len(rotations), 2)
                    self.assertTrue(all(r.status == "COMPLETED" for r in rotations))


if __name__ == "__main__":
    unittest.main()
