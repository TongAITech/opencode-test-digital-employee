"""Adversarial observation budgets; no bank/provider success is implied."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT / "ai-test/runtime"))

from aitest_runtime.autonomous_orchestration import DirectoryScopedOpenCodeSessionProvider, FakeOpenCodeSessionProvider
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
from aitest_runtime.g2_1.supervisor import RotationPolicy, SessionObservation, durable_pressure
from aitest_runtime.session_pressure import message_metrics, ObservationBudgetExceeded
from test_g2_1_session_router_control_loop import request, one_task


def message(index=0, role="assistant", text="small", parts=None):
    return {"info": {"id": f"msg-{index}", "sessionID": "session-1", "role": role},
            "parts": parts if parts is not None else [{"type": "text", "text": text}]}


def reasons(pressure):
    return RotationPolicy().evaluate(SessionObservation.from_provider("session-1", {
        "reachable": True, "healthy": True, "pressure": pressure,
        "message_count": pressure.get("message_count"), "compaction_count": pressure.get("compaction_count"),
    }))


class PressureTests(unittest.TestCase):
    def test_control_write_retries_observation_race_but_rejects_semantic_race(self):
        from aitest_runtime.durable_core import ActorRef, CommandEnvelope
        from aitest_runtime.g2_1.contracts import REGISTER_TASK_ROUTE, TASK_ROUTE_REGISTERED
        for observation_only in (True, False):
            with self.subTest(observation_only=observation_only), tempfile.TemporaryDirectory() as directory:
                root=Path(directory);runtime=create_canonical_runtime(root,db_path=root/'runtime.db')
                service=G21AutonomousOrchestrationService(runtime,root,session_provider=FakeOpenCodeSessionProvider(root))
                mission=service.start_test(request('control-race','RACE'))['intake']['intake']['mission_id']
                sid=next(p.external_session_id for p in service.session_control.state(mission).provisions if p.role=='PLANNER')
                original=runtime.execute;injected=[]
                def racing_execute(command):
                    if isinstance(command,CommandEnvelope) and command.type==REGISTER_TASK_ROUTE and not injected:
                        injected.append(command)
                        if observation_only:
                            service.session_control.record_observation(mission,SessionObservation.from_provider(sid,{'reachable':True,'healthy':True,'message_count':1}).to_dict())
                        else:
                            changed=original(CommandEnvelope('semantic-close','CLOSE_SESSION',mission,runtime.get_head_seq(mission),ActorRef('SYSTEM','test'),{'reason':'SEMANTIC_CHANGE'},session_id=sid))
                            self.assertTrue(changed.ok)
                    return original(command)
                runtime.execute=racing_execute
                if observation_only:
                    self.assertEqual(service.propose_plan(mission,one_task())['status'],'PASS')
                    routes=[e for e in runtime.list_events(mission) if e.event_type==TASK_ROUTE_REGISTERED]
                    self.assertEqual(len(routes),1)
                    self.assertIn(':observation-cursor:',routes[0].command_id)
                    self.assertEqual(routes[0].correlation_id,injected[0].correlation_id)
                else:
                    with self.assertRaisesRegex(Exception,'EXPECTED_SEQ_MISMATCH'):
                        service.propose_plan(mission,one_task())
                    self.assertFalse(any(e.event_type==TASK_ROUTE_REGISTERED for e in runtime.list_events(mission)))

    def test_large_multilingual_tool_output_rotates_before_estimate_warning(self):
        pressure = message_metrics([message(parts=[{"type": "tool", "state": {"output": "业务内容" * 2000}}])], "session-1")
        self.assertIn("ESTIMATED_CONTEXT_PRESSURE", reasons(pressure))
        self.assertNotIn("业务内容", json.dumps(pressure, ensure_ascii=False))
        self.assertEqual(pressure["estimate_method"], "UTF8_BYTES_PLUS_FRAMING_AND_4096_RESERVE")

    def test_compaction_and_turn_and_tool_activity_are_independent(self):
        self.assertIn("CONTEXT_COMPACTED", reasons(message_metrics([message(parts=[{"type": "compaction"}])], "session-1")))
        self.assertIn("TURN_BUDGET", reasons(message_metrics([message(i) for i in range(24)], "session-1")))
        self.assertIn("ACTIVITY_BUDGET", reasons(message_metrics([message(parts=[{"type": "tool"}] * 48)], "session-1")))

    def test_duplicate_messages_do_not_inflate_counts(self):
        pressure = message_metrics([message()] * 60, "session-1")
        self.assertEqual(pressure["message_count"], 1)
        self.assertFalse(pressure["message_sample_saturated"])

    def test_invalid_shapes_and_cross_session_messages_fail_closed(self):
        for value in ({}, ["raw text"], [{"info": {}, "parts": []}], [message(parts=["raw part"])]):
            with self.assertRaises(ValueError):
                message_metrics(value, "session-1")
        with self.assertRaises(ValueError):
            message_metrics([message()], "other-session")

    def test_latest_real_token_usage_not_cumulative_spend(self):
        first, last = message(0), message(1)
        first["info"].update({"tokens": {"input": 500, "output": 20}, "time": {"created": 1}})
        last["info"].update({"tokens": {"input": 100, "output": 10, "cache": {"read": 50, "write": 5}}, "time": {"created": 2}})
        self.assertEqual(message_metrics([last, first], "session-1")["observed_message_tokens"], 165)
        streaming=message(2);streaming["info"].update({"tokens":{"input":0,"output":0},"time":{"created":3}})
        self.assertEqual(message_metrics([first,last,streaming],"session-1")["observed_message_tokens"],165)

    def test_actual_model_capacity_prevents_small_budget_rotation_loop(self):
        with tempfile.TemporaryDirectory() as directory:
            provider=DirectoryScopedOpenCodeSessionProvider(directory)
            item=message(text="synthetic planner analysis "*2000)
            item['info'].update(providerID='host',modelID='large-model')
            def transport(method,path,body=None):
                if '/message?' in path:return [item]
                if path.startswith('/provider?'):return {'all':[{'id':'host','models':{'large-model':{'limit':{'context':200000}}}}]}
                return {'id':'session-1'}
            provider._request=transport
            value=provider.observe_session('session-1')
            self.assertEqual(value['context_limit'],200000)
            self.assertNotIn('ESTIMATED_CONTEXT_PRESSURE',reasons(value['pressure']))
            self.assertEqual(value['pressure']['model_context_capacity']['source'],'OPENCODE_PROVIDER_MODEL_CATALOG')
            item['parts'][0]['text']='synthetic work '*15000
            self.assertIn('ESTIMATED_CONTEXT_PRESSURE',reasons(provider.observe_session('session-1')['pressure']))

    def test_unknown_model_catalog_does_not_relax_fallback_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            provider=DirectoryScopedOpenCodeSessionProvider(directory)
            item=message(text='synthetic work '*4000);item['info'].update(providerID='host',modelID='unavailable')
            provider._request=lambda method,path,body=None: [item] if '/message?' in path else {'all':[]} if path.startswith('/provider?') else {'id':'session-1'}
            value=provider.observe_session('session-1')
            self.assertIsNone(value['context_limit'])
            self.assertIn('ESTIMATED_CONTEXT_PRESSURE',reasons(value['pressure']))

    def test_provider_fallback_keeps_model_limit_unknown(self):
        provider = DirectoryScopedOpenCodeSessionProvider(WORKSPACE_ROOT)
        provider._request = lambda method, path, body=None: [message()] if "/message?" in path else {"id": "session-1"}
        value = provider.observe_session("session-1")
        self.assertEqual(value["message_count"], 1)
        self.assertIsNone(value["context_limit"])
        self.assertIsNone(value["context_utilization"])
        self.assertEqual(value["pressure"]["metrics_source"], "OPENCODE_MESSAGE_API")

    def test_oversize_observation_is_pressure_not_unreachable(self):
        provider = DirectoryScopedOpenCodeSessionProvider(WORKSPACE_ROOT)
        def transport(method, path, body=None):
            if "/message?" in path:
                raise ObservationBudgetExceeded("overflow")
            return {"id": "session-1"}
        provider._request = transport
        value = provider.observe_session("session-1")
        self.assertTrue(value["reachable"])
        self.assertIn("OBSERVATION_BYTE_BUDGET", reasons(value["pressure"]))

    def test_blind_budget_is_r1_durable_across_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            provider = FakeOpenCodeSessionProvider(root)
            service = G21AutonomousOrchestrationService(create_canonical_runtime(root, db_path=root / "runtime-spine.db"), root, session_provider=provider)
            mission = service.start_test(request("blind", "BLIND"))["intake"]["intake"]["mission_id"]
            task = service.propose_plan(mission, one_task())["next"]
            sid = task["external_session"]["session_id"]
            value = {"reachable": True, "healthy": True, "observed_at": "2026-09-08T00:00:00Z",
                     "raw_digest": "same", "pressure": {"metrics_source": "METADATA_ONLY"}}
            self.assertEqual(service.observe_session(mission, task_id=task["task_id"], observation=value)["status"], "KEEP")
            # Fresh runtime and service, with no in-memory counters.
            restored = G21AutonomousOrchestrationService(create_canonical_runtime(root, db_path=root / "runtime-spine.db"), root, session_provider=provider)
            value["observed_at"] = "2026-09-08T00:05:00Z"
            rotated = restored.observe_session(mission, task_id=task["task_id"], observation=value)
            self.assertEqual(rotated["status"], "ROTATED")
            self.assertIn("BLIND_TIME_BUDGET", rotated["rotation_reasons"])
            checkpoint = restored.session_control.state(mission).rotations[-1].checkpoint
            self.assertEqual(checkpoint["predecessor_session_id"], sid)
            recovered = restored.runtime.replay_composed(mission, through_seq=checkpoint["through_seq"])
            from aitest_runtime.durable_core import canonical_sha256
            self.assertEqual(canonical_sha256(recovered.to_dict()), checkpoint["state_digest"])
            self.assertFalse((root / "ai-test/state/aitest.db").exists())

    def test_unchanged_observation_does_not_spend_activity_budget(self):
        raw = {"reachable": True, "raw_digest": "same", "observed_at": "2026-09-08T00:00:00Z", "pressure": {"metrics_source": "METADATA_ONLY"}}
        previous = SessionObservation.from_provider("session-1", durable_pressure(raw))
        for _ in range(25):
            previous = SessionObservation.from_provider("session-1", durable_pressure(raw, previous))
        self.assertEqual(previous.provider_state["pressure"]["blind_activity_count"], 0)

    def test_large_bootstrap_is_bounded_and_canonical_body_is_referenced(self):
        envelope = {"mission_id": "mission", "task": {"intent": "业务需求" * 30000}, "goal": {"title": "goal"}}
        result = G21AutonomousOrchestrationService._bounded_bootstrap("CONTEXT\n", envelope)
        self.assertLessEqual(len(result.encode("utf-8")), 16384)
        self.assertTrue(json.loads(result.split("\n", 1)[1])["task"]["body_omitted"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
