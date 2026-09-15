"""C3 autonomous Mission progress / no-progress replanning regressions."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "workspace-template/ai-test/runtime"))

from aitest_runtime.autonomous_orchestration import FakeOpenCodeSessionProvider
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.dispatch_receipts import business_cursor
from aitest_runtime.durable_core import ActorRef, canonical_sha256
from aitest_runtime.provider_binding import ProviderBindingApplicationService
from aitest_runtime.tool_execution import (
    ReconcileToolExecutionRequest, SideEffectPolicy, SideEffectState,
    ToolExecutionApplicationService, ToolExecutionOutcomeRequest, ToolExecutionRequest, ToolObservation,
)
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

    def test_idempotent_auto_continue_waits_before_no_progress_replan(self):
        mission, worker = self._active_worker("accepted-wake-grace")
        session_id = worker["external_session"]["session_id"]
        composed = self.runtime.replay_composed(mission)
        task = next(t for t in composed.extension_state("r1_2_work_graph").tasks if t.task_id == worker["task_id"])
        attempt = composed.extension_state("r1_3b_execution_resume").latest_attempt(task.task_id)
        route = self.service._route_task(mission, task.task_id)
        text = self.service._context_message(
            mission_id=mission, plan_id=task.plan_id, revision_id=task.plan_revision_id,
            task_id=task.task_id, attempt=attempt, agent=route.agent_name,
        )

        with patch("aitest_runtime.g2_1.managed_orchestration.POST_DISPATCH_GRACE_SECONDS", 0):
            first = self.service._wake_once(mission, session_id, route.agent_name, text)
            self.assertEqual(first["status"], "AUTO_CONTINUE")
            self.assertTrue(first["delivery"]["prompt_sent"])

            repeated = self.service._wake_once(mission, session_id, route.agent_name, text)
            self.assertEqual(repeated["status"], "WAIT")
            self.assertEqual(repeated["reason"], "AUTO_CONTINUE_PROGRESS_GRACE")
            self.assertEqual(repeated["delivery"]["status"], "ALREADY_ACCEPTED")
            self.assertFalse(repeated["delivery"]["prompt_sent"])
            self.assertFalse(self.service.session_control.state(mission).progress_records)
            self.assertFalse([
                p for p in self.service.session_control.state(mission).provisions
                if p.phase == "REPLANNING"
            ])

            with patch("aitest_runtime.g2_1.managed_orchestration.AUTO_CONTINUE_PROGRESS_GRACE_SECONDS", 0):
                stalled = self.service._wake_once(mission, session_id, route.agent_name, text)
            self.assertEqual(stalled["status"], "REPLAN_DISPATCHED")
            self.assertEqual(stalled["stalled_session_id"], session_id)
            self.assertEqual(stalled["delivery"]["status"], "ALREADY_ACCEPTED")
            self.assertEqual(len(self.service.session_control.state(mission).progress_records), 1)

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



    def test_routing_only_replan_is_real_governed_progress_not_semantic_no_change(self):
        mission, worker = self._active_worker("routing-change")
        stalled_cursor = business_cursor(self.runtime, mission)
        first = self.service._handle_no_progress(
            mission, task_id=worker["task_id"], session_id=worker["external_session"]["session_id"],
            reason="AUTO_CONTINUE_NO_BUSINESS_PROGRESS", cursor=stalled_cursor,
        )
        progress_id = first["progress_id"]
        original_revision = self.service._active_plan_context(mission)[3].current_revision_id

        routed = one_task()
        routed["tasks"][0]["routing"] = {
            "role": "EVALUATOR",
            "required_capabilities": ["OPENCODE_AGENT_SESSION", "TASK_OUTCOME_REPORT"],
            "isolation_policy": "DEDICATED_TASK_SESSION",
            "parallelism_policy": "SERIAL",
        }
        revised = self.service.propose_plan(mission, routed)
        self.assertEqual(revised["status"], "PASS")
        self.assertTrue(revised["semantic_business_progress"])
        self.assertFalse(revised["stalled_replan_no_change"])
        current = self.service._active_plan_context(mission)[3]
        self.assertNotEqual(current.current_revision_id, original_revision)
        next_item = revised["next"]
        self.assertIsNotNone(next_item)
        self.assertEqual(next_item["route"]["role"], "EVALUATOR")
        self.assertEqual(self.service.session_control.state(mission).progress(progress_id).phase, "RESOLVED")
        self.assertGreater(business_cursor(self.runtime, mission), stalled_cursor)


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
        blocked_session = successors[-1]
        self.assertNotIn(blocked_session, self.provider.sessions)
        core = self.runtime.replay_composed(mission).core_state.session(blocked_session)
        self.assertIsNotNone(core)
        self.assertEqual(core.status.value, "CLOSED")


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


    def test_unresolved_business_side_effect_fences_autonomous_wake_and_replan(self):
        mission, worker = self._active_worker("effect-fence")
        task_id = worker["task_id"]
        session_id = worker["external_session"]["session_id"]
        composed = self.runtime.replay_composed(mission)
        execution = composed.extension_state("r1_3b_execution_resume")
        attempt = execution.latest_attempt(task_id)
        self.assertIsNotNone(attempt)
        bindings = composed.extension_state("r1_3c_provider_binding")
        binding = bindings.binding(attempt.attempt_id)
        actor = ActorRef("SYSTEM", "c3-effect-fence-test")
        if binding is None:
            bound = ProviderBindingApplicationService(self.runtime).bind({
                "command_id": "c3:effect-fence:provider-binding",
                "idempotency_key": "c3:effect-fence:provider-binding",
                "mission_id": mission,
                "runtime_session_id": session_id,
                "expected_seq": self.runtime.get_head_seq(mission),
                "actor": actor,
                "correlation_id": "c3:effect-fence",
                "attempt_id": attempt.attempt_id,
                "provider": "c3-fixture-provider",
                "model": "c3-fixture-model",
                "configuration": {
                    "identity": "c3-effect-fixture",
                    "version": 1,
                    "digest": canonical_sha256({"provider": "c3-fixture-provider", "model": "c3-fixture-model"}),
                    "scope": {"purpose": "side-effect-recovery-regression"},
                    "provenance": {"kind": "TEST_FIXTURE"},
                },
            })
            binding = bound.binding
        self.assertIsNotNone(binding)

        tool_id = "tool-execution:effect-fence"
        tool_service = ToolExecutionApplicationService(self.runtime)
        request = ToolExecutionRequest(
            command_id="c3:effect-fence:request",
            idempotency_key="c3:effect-fence:request",
            mission_id=mission,
            plan_id=attempt.plan_id,
            plan_revision_id=attempt.plan_revision_id,
            task_id=task_id,
            attempt_id=attempt.attempt_id,
            runtime_session_id=session_id,
            expected_seq=self.runtime.get_head_seq(mission),
            actor=actor,
            correlation_id="c3:effect-fence",
            tool_execution_id=tool_id,
            capability_id="C3_SIDE_EFFECT_FIXTURE",
            capability_version=1,
            provider_binding_id=binding.attempt_id,
            provider_binding_digest=canonical_sha256(binding.to_dict()),
            context_cursor=attempt.context_cursor,
            input_digest=canonical_sha256({"operation": "create", "fixture": "effect-fence"}),
            side_effect_policy=SideEffectPolicy.REVERSIBLE,
            redacted_input={"operation": "create"},
        )
        started = tool_service.request(request)
        self.assertEqual(started.record.side_effect_state, SideEffectState.NOT_ATTEMPTED)
        self.assertIsNone(started.record.execution_fact)

        before_messages = len(self.provider.messages)
        before_progress = tuple(self.service.session_control.state(mission).progress_records)
        first = self.service.progress_once(mission)
        self.assertEqual(first["status"], "PROGRESS_CHECKED")
        barriers = [item for item in first["wakes"] if item.get("reason") == "BUSINESS_EFFECT_RECONCILIATION_REQUIRED"]
        self.assertEqual(len(barriers), 1)
        self.assertEqual(barriers[0]["tool_execution_refs"][0]["tool_execution_id"], tool_id)
        self.assertEqual(len(self.provider.messages), before_messages)
        self.assertEqual(tuple(self.service.session_control.state(mission).progress_records), before_progress)

        unknown = ToolExecutionOutcomeRequest(
            command_id="c3:effect-fence:unknown",
            idempotency_key="c3:effect-fence:unknown",
            mission_id=mission,
            runtime_session_id=session_id,
            expected_seq=self.runtime.get_head_seq(mission),
            actor=actor,
            correlation_id="c3:effect-fence",
            tool_execution_id=tool_id,
            observation=ToolObservation(
                SideEffectState.UNKNOWN,
                SideEffectState.UNKNOWN,
                error_code="FIXTURE_RECEIPT_LOST",
            ),
        )
        tool_service.record_outcome(unknown)
        second = self.service.progress_once(mission)
        second_barriers = [item for item in second["wakes"] if item.get("reason") == "BUSINESS_EFFECT_RECONCILIATION_REQUIRED"]
        self.assertEqual(len(second_barriers), 1)
        self.assertEqual(second_barriers[0]["tool_execution_refs"][0]["side_effect_state"], "UNKNOWN")
        self.assertEqual(len(self.provider.messages), before_messages)

        reconciled = ReconcileToolExecutionRequest(
            command_id="c3:effect-fence:reconcile",
            idempotency_key="c3:effect-fence:reconcile",
            mission_id=mission,
            runtime_session_id=session_id,
            expected_seq=self.runtime.get_head_seq(mission),
            actor=actor,
            correlation_id="c3:effect-fence",
            tool_execution_id=tool_id,
            reconciliation_id="reconciliation:effect-fence",
            observation=ToolObservation(
                SideEffectState.REJECTED,
                SideEffectState.REJECTED,
                error_code="FIXTURE_CONFIRMED_NOT_APPLIED",
            ),
        )
        tool_service.reconcile(reconciled)
        third = self.service.progress_once(mission)
        third_reasons = [item.get("reason") for item in third.get("wakes", [])]
        self.assertNotIn("BUSINESS_EFFECT_RECONCILIATION_REQUIRED", third_reasons)


    def test_planner_toolcontext_session_external_delete_is_deferred_until_reconciliation(self):
        started = self.service.start_test(request("planner-host-close"))
        mission = started["intake"]["intake"]["mission_id"]
        planner_id = started["planner_session"]["external_session"]["session_id"]

        with patch.dict(os.environ, {"AITEST_HOST_SESSION_ID": planner_id}, clear=False):
            planned = self.service.propose_plan(mission, one_task())

        self.assertEqual(planned["status"], "PASS")
        worker = planned["next"]
        self.assertIsInstance(worker, dict)
        self.assertEqual(worker["status"], "DISPATCHED")
        worker_id = worker["external_session"]["session_id"]

        planner_core = self.runtime.replay_composed(mission).core_state.session(planner_id)
        self.assertIsNotNone(planner_core)
        self.assertEqual(planner_core.status.value, "CLOSED")
        self.assertIn(
            planner_id,
            self.provider.sessions,
            "the currently executing Host Planner Session must survive until its tool call can return",
        )
        self.assertIn(worker_id, self.provider.sessions)

        # The real background Control Loop can reconcile concurrently with the
        # still-running Planner ToolContext. A terminal durable Session is not
        # permission to kill a Host Session that is still busy returning the
        # accepted tool call.
        self.provider.set_observation(planner_id, activity_state="busy")
        busy_reconcile = self.service.reconcile_external_sessions()
        self.assertEqual(busy_reconcile["status"], "PASS")
        self.assertIn(planner_id, self.provider.sessions)
        self.assertTrue(any(
            item.get("session_id") == planner_id
            and item.get("status") == "TERMINAL_EXTERNAL_BUSY_DEFERRED"
            for item in busy_reconcile["actions"]
        ))

        self.provider.set_observation(planner_id, activity_state="idle")
        reconciled = self.service.reconcile_external_sessions()
        self.assertEqual(reconciled["status"], "PASS")
        self.assertNotIn(planner_id, self.provider.sessions)
        self.assertIn(worker_id, self.provider.sessions)


if __name__ == "__main__":
    unittest.main()
