"""V4 C2/F04 pre-provider Context Admission product regressions."""
from __future__ import annotations
import tempfile
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "workspace-template/ai-test/runtime"))

from aitest_runtime.autonomous_orchestration import FakeOpenCodeSessionProvider
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.context_admission import admit, evaluate
from aitest_runtime.control_loop import _primary_session_tick
from aitest_runtime.durable_core import RuntimeError, canonical_sha256
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
from aitest_runtime.g2_1.supervisor import RotationPolicy, SessionObservation, durable_pressure
from aitest_runtime.primary_sessions import PrimarySessionOwner, RECORD, transition, now


def request(intake_id: str, version: str):
    return {
        "intake_id": intake_id,
        "operation": "CREATE",
        "scope": {"mode": "EXPLICIT_SET", "project_id": "PFC", "version": version, "requirements": ["REQ-F04"]},
        "goal": {"title": "F04", "intent": "prove pre-provider context admission", "constraints": []},
        "source": {"kind": "USER", "source_ref": "f04:" + intake_id,
                   "source_digest": canonical_sha256({"id": intake_id}),
                   "observed_at": "2026-09-13T12:00:00Z", "valid_until": None, "source_precedence": 1},
        "actor": {"type": "USER", "id": "f04-test"},
        "resolution": {"resolution_id": "resolution:" + intake_id,
                       "request_digest": canonical_sha256({"resolution": intake_id}),
                       "snapshot_id": "snapshot:" + intake_id,
                       "fact_set_digest": canonical_sha256({"facts": []}),
                       "status": "RESOLVED", "reason_code": None,
                       "source_refs": ["f04:" + intake_id],
                       "valid_until": "2026-09-14T12:00:00Z"},
    }


def one_task():
    return {
        "objective": "one worker",
        "tasks": [{
            "task_key": "worker",
            "intent": "bounded analysis",
            "acceptance_criteria": [{"id": "done", "description": "worker complete"}],
            "routing": {"role": "EXECUTOR",
                        "required_capabilities": ["OPENCODE_AGENT_SESSION", "TASK_OUTCOME_REPORT"],
                        "isolation_policy": "DEDICATED_TASK_SESSION",
                        "parallelism_policy": "SERIAL"},
        }],
        "dependencies": [],
    }


def blocked_payload(session_id: str, agent: str, *, user_text: str | None = None):
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
        **({
            "current_user_text": user_text,
            "current_user_replay_safe": True,
            "current_user_identity_exact": True,
            "current_user_part_types": ["text"],
        } if user_text is not None else {}),
    }


class CrashAfterAcceptProvider(FakeOpenCodeSessionProvider):
    def __init__(self, directory):
        super().__init__(directory)
        self.crash_once = True

    def send_context(self, *, session_id: str, agent: str, text: str):
        result = super().send_context(session_id=session_id, agent=agent, text=text)
        if self.crash_once:
            self.crash_once = False
            raise OSError("SIMULATED_CRASH_AFTER_HOST_ACCEPT")
        return result


class CrashBeforeAcceptProvider(FakeOpenCodeSessionProvider):
    def __init__(self, directory):
        super().__init__(directory)
        self.crash_once = True

    def send_context(self, *, session_id: str, agent: str, text: str):
        if self.crash_once:
            self.crash_once = False
            raise OSError("SIMULATED_CRASH_BEFORE_HOST_ACCEPT")
        return super().send_context(session_id=session_id, agent=agent, text=text)


class ContextAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "workspace"
        self.root.mkdir()
        self.runtime = create_canonical_runtime(self.root, db_path=Path(self.tmp.name) / "state/spine.db")
        self.provider = FakeOpenCodeSessionProvider(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_budget_allows_small_and_blocks_full_request_before_provider(self):
        allowed = evaluate({
            "context_limit": 128000, "max_output_tokens": 8192,
            "system_bytes": 5000, "messages_bytes": 12000,
            "tools_bytes": 6000, "extra_bytes": 1000,
            "message_count": 16, "tool_count": 8,
        })
        self.assertEqual(allowed["status"], "ALLOW")
        self.assertLessEqual(allowed["request_upper_bound"], allowed["input_budget"])
        blocked = evaluate(blocked_payload("ses_old", "aitest-director", user_text="测试 BLOAN"))
        self.assertEqual(blocked["status"], "BLOCK")
        self.assertGreater(blocked["request_upper_bound"], blocked["input_budget"])
        self.assertEqual(blocked["estimation_method"], "UTF8_BYTES_AS_TOKEN_UPPER_BOUND_PLUS_FRAMING")

    def test_large_output_reserve_is_never_shrunk_to_make_input_fit(self):
        decision = evaluate({
            "context_limit": 128000,
            "max_output_tokens": 100000,
            "system_bytes": 12000,
            "messages_bytes": 12000,
            "tools_bytes": 1000,
            "extra_bytes": 500,
            "message_count": 8,
            "tool_count": 2,
        })
        self.assertEqual(decision["output_reserve"], 100000)
        self.assertEqual(decision["context_input_limit"], 28000)
        self.assertEqual(decision["status"], "BLOCK")

    def test_independent_model_input_limit_caps_budget_before_context_window(self):
        decision = evaluate({
            "context_limit": 128000,
            "input_limit": 16384,
            "max_output_tokens": 4096,
            "system_bytes": 7000,
            "messages_bytes": 9000,
            "tools_bytes": 1200,
            "extra_bytes": 500,
            "message_count": 6,
            "tool_count": 2,
        })
        self.assertEqual(decision["model_input_limit"], 16384)
        self.assertEqual(decision["effective_input_limit"], 16384)
        self.assertEqual(decision["status"], "BLOCK")

    def test_each_final_request_component_can_independently_block(self):
        base = {
            "context_limit": 128000, "max_output_tokens": 8192,
            "system_bytes": 0, "messages_bytes": 0, "tools_bytes": 0,
            "extra_bytes": 0, "message_count": 1, "tool_count": 1,
        }
        for component in ("system_bytes", "messages_bytes", "tools_bytes", "extra_bytes"):
            payload = dict(base)
            payload[component] = 120000
            with self.subTest(component=component):
                decision = evaluate(payload)
                self.assertEqual(decision["status"], "BLOCK")
                self.assertGreater(decision["request_upper_bound"], decision["input_budget"])

    def test_invalid_or_unknown_model_limit_fails_closed(self):
        for value in (None, 0, 4096, "128000"):
            payload = {"context_limit": value}
            with self.subTest(value=value):
                with self.assertRaises((ValueError, TypeError)):
                    evaluate(payload)


    def test_primary_missing_exact_host_message_identity_never_replays_previous_turn(self):
        owner = PrimarySessionOwner(self.runtime, self.root, self.provider)
        old = owner.ensure_current()
        payload = blocked_payload(old["session_id"], "aitest-director", user_text="上一轮文本绝不能被猜测重放")
        payload["current_user_identity_exact"] = False
        with self.assertRaisesRegex(RuntimeError, "PRIMARY_CONTEXT_REPLAY_IDENTITY_UNRESOLVED"):
            admit(payload, runtime=self.runtime, provider=self.provider, root=self.root)
        state = owner.state()
        self.assertEqual(state.epoch, old["epoch"])
        self.assertEqual(state.bindings[str(old["epoch"])]["state"], "BOUND")
        self.assertNotIn("context_recovery", state.bindings[str(old["epoch"])])
        self.assertEqual(self.provider.messages, [])

    def test_primary_non_text_turn_fails_closed_before_fence_or_successor(self):
        owner = PrimarySessionOwner(self.runtime, self.root, self.provider)
        old = owner.ensure_current()
        payload = blocked_payload(old["session_id"], "aitest-director", user_text="分析这个附件")
        payload["current_user_replay_safe"] = False
        payload["current_user_part_types"] = ["text", "file"]
        with self.assertRaisesRegex(RuntimeError, "PRIMARY_CONTEXT_REPLAY_NON_TEXT_UNSUPPORTED"):
            admit(payload, runtime=self.runtime, provider=self.provider, root=self.root)
        state = owner.state()
        self.assertEqual(state.epoch, old["epoch"])
        self.assertEqual(state.bindings[str(old["epoch"])]["state"], "BOUND")
        self.assertNotIn("context_recovery", state.bindings[str(old["epoch"])])
        self.assertEqual(len(self.provider.sessions), 1)
        self.assertEqual(self.provider.messages, [])

    def test_primary_tui_follow_failure_never_replays_before_retry(self):
        owner = PrimarySessionOwner(self.runtime, self.root, self.provider)
        old = owner.ensure_current()
        payload = blocked_payload(old["session_id"], "aitest-director", user_text="继续当前任务")
        original = self.provider.select_tui_session
        with patch.object(self.provider, "select_tui_session", side_effect=OSError("tui unavailable")):
            with self.assertRaisesRegex(RuntimeError, "PRIMARY_CONTEXT_REPLAY_RECONCILIATION_REQUIRED"):
                admit(payload, runtime=self.runtime, provider=self.provider, root=self.root)
        state = owner.state()
        self.assertEqual(state.epoch, 2)
        recovery = state.bindings["1"]["context_recovery"]
        self.assertEqual(recovery["state"], "CLAIMED")
        self.assertEqual(recovery["target_session_id"], state.bindings["2"]["session_id"])
        self.assertEqual(self.provider.messages, [], "replay must not race ahead of TUI successor follow")

        restarted = PrimarySessionOwner(self.runtime, self.root, self.provider)
        accepted = restarted.recover_pending_context()
        self.assertEqual(accepted["status"], "ACCEPTED")
        self.assertEqual(len(self.provider.messages), 1)
        self.assertEqual(self.provider.messages[0]["text"], "继续当前任务")
        self.assertEqual(self.provider.tui_selections[-1], accepted["successor_session_id"])

    def test_primary_recovery_transition_is_pure_for_nested_journal(self):
        owner = PrimarySessionOwner(self.runtime, self.root, self.provider)
        old = owner.ensure_current()
        digest = "a" * 64
        recovery_id = owner.claim_context_recovery(old["session_id"], "aitest-director", "继续当前任务", digest)
        owner.fence("TEST_CONTEXT_RECOVERY")
        successor = owner.ensure_current()
        owner.record("RECOVERY_TARGET", {
            "predecessor_epoch": 1,
            "recovery_id": recovery_id,
            "successor_epoch": successor["epoch"],
            "successor_session_id": successor["session_id"],
            "observed_at": now(),
        })
        before = owner.state()
        self.assertEqual(before.bindings["1"]["context_recovery"]["state"], "CLAIMED")
        payload = {
            "subject": owner.subject.to_dict(),
            "operation": "RECOVERY_BEGIN_SEND",
            "data": {
                "predecessor_epoch": 1,
                "recovery_id": recovery_id,
                "successor_session_id": successor["session_id"],
                "observed_at": now(),
            },
        }
        after = transition(before, RECORD, payload)
        self.assertEqual(before.bindings["1"]["context_recovery"]["state"], "CLAIMED",
                         "transition must never mutate its input state")
        self.assertEqual(after.bindings["1"]["context_recovery"]["state"], "SENDING")


    def test_primary_block_fences_predecessor_replays_current_turn_and_follows_tui(self):
        owner = PrimarySessionOwner(self.runtime, self.root, self.provider)
        old = owner.ensure_current()
        text = "测试 BLOAN-PF1.1.0，继续当前目标，不要重放旧会话历史。"
        result = admit(blocked_payload(old["session_id"], "aitest-director", user_text=text),
                       runtime=self.runtime, provider=self.provider, root=self.root)
        self.assertEqual(result["status"], "BLOCK")
        recovery = result["recovery"]
        self.assertEqual(recovery["kind"], "PRIMARY")
        self.assertEqual(recovery["status"], "ROTATED")
        self.assertEqual(recovery["epoch"], 2)
        self.assertNotEqual(recovery["successor_session_id"], old["session_id"])
        self.assertEqual(self.provider.tui_selections[-1], recovery["successor_session_id"])
        replay = [m for m in self.provider.messages if m["session_id"] == recovery["successor_session_id"]]
        self.assertEqual(len(replay), 1)
        self.assertEqual(replay[0]["agent"], "aitest-director")
        self.assertEqual(replay[0]["text"], text)
        with self.assertRaisesRegex(RuntimeError, "STALE_CALLER"):
            owner.current(old["session_id"])

    def test_primary_replay_crash_after_host_accept_reconciles_without_duplicate_send(self):
        provider = CrashAfterAcceptProvider(self.root)
        owner = PrimarySessionOwner(self.runtime, self.root, provider)
        old = owner.ensure_current()
        text = "继续当前任务；验证 Host 已接收后的崩溃恢复。"
        with self.assertRaisesRegex(RuntimeError, "PRIMARY_CONTEXT_REPLAY_RECONCILIATION_REQUIRED"):
            admit(blocked_payload(old["session_id"], "aitest-director", user_text=text),
                  runtime=self.runtime, provider=provider, root=self.root)

        state = owner.state()
        self.assertEqual(state.epoch, 2)
        recovery = state.bindings["1"]["context_recovery"]
        self.assertEqual(recovery["state"], "SENDING")
        successor = state.bindings["2"]["session_id"]
        sent = [m for m in provider.messages if m["session_id"] == successor and m["text"] == text]
        self.assertEqual(len(sent), 1)

        result = _primary_session_tick(self.runtime, self.root, provider)
        self.assertEqual(result["status"], "RECOVERED")
        state = owner.state()
        self.assertEqual(state.bindings["1"]["context_recovery"]["state"], "ACCEPTED")
        sent = [m for m in provider.messages if m["session_id"] == successor and m["text"] == text]
        self.assertEqual(len(sent), 1, "readback reconciliation must not resend the accepted turn")
        self.assertTrue(self.runtime.verify_projection(owner.subject.subject_id)["ok"])

    def test_primary_replay_unknown_effect_never_blindly_resends(self):
        provider = CrashBeforeAcceptProvider(self.root)
        owner = PrimarySessionOwner(self.runtime, self.root, provider)
        old = owner.ensure_current()
        text = "继续当前任务；验证未知副作用不盲目重发。"
        with self.assertRaisesRegex(RuntimeError, "PRIMARY_CONTEXT_REPLAY_RECONCILIATION_REQUIRED"):
            admit(blocked_payload(old["session_id"], "aitest-director", user_text=text),
                  runtime=self.runtime, provider=provider, root=self.root)

        state = owner.state()
        self.assertEqual(state.bindings["1"]["context_recovery"]["state"], "SENDING")
        successor = state.bindings["2"]["session_id"]
        self.assertEqual([m for m in provider.messages if m["session_id"] == successor], [])

        result = _primary_session_tick(self.runtime, self.root, provider)
        self.assertEqual(result["status"], "WAIT")
        self.assertEqual(result["reason"], "PRIMARY_RECOVERY_EFFECT_UNKNOWN")
        self.assertEqual([m for m in provider.messages if m["session_id"] == successor], [],
                         "an unknown side effect must not be replayed blindly")
        self.assertEqual(owner.state().epoch, 2)

    def test_mission_block_is_durable_pressure_and_survives_fresh_host_observation(self):
        service = G21AutonomousOrchestrationService(self.runtime, self.root, session_provider=self.provider)
        mission = service.start_test(request("mission-pressure", "BLOAN-1.9.4"))["intake"]["intake"]["mission_id"]
        first = service.propose_plan(mission, one_task())["next"]
        sid = first["external_session"]["session_id"]
        result = admit(blocked_payload(sid, "aitest-executor"),
                       runtime=self.runtime, provider=self.provider, root=self.root)
        self.assertEqual(result["status"], "BLOCK")
        self.assertEqual(result["recovery"]["status"], "PRESSURE_RECORDED")
        record = service.session_control.state(mission).observation(sid)
        self.assertIsNotNone(record)
        self.assertTrue(record.provider_state["pressure"]["final_request_admission_blocked"])

        # The control loop receives a fresh Host raw shape, then merges the
        # prior durable observation before evaluating policy.  Do not feed the
        # R1 record serialization back through from_provider as if it were Host raw.
        fresh = durable_pressure({
            "session_id": sid, "observed_at": "2026-09-13T12:01:00Z",
            "reachable": True, "healthy": True, "message_count": 1,
            "compaction_count": 0, "context_used": 1000, "context_limit": 8192,
            "context_utilization": 0.12, "provider": "OPENCODE",
            "pressure": {"metrics_source": "MESSAGE_API"},
        }, record)
        self.assertTrue(fresh["pressure"]["final_request_admission_blocked"])
        self.assertEqual(fresh["pressure"]["admission_digest"],
                         record.provider_state["pressure"]["admission_digest"])
        self.assertIn("FINAL_REQUEST_ADMISSION",
                      RotationPolicy().evaluate(SessionObservation.from_provider(sid, fresh)))


if __name__ == "__main__":
    unittest.main()
