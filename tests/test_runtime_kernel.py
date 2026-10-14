import tempfile
import unittest

from rc6_runtime.authority import AuthorityError, AuthorityRuntime
from rc6_runtime.budget import ContextBudget, ProviderBudget
from rc6_runtime.mission import MissionRuntime
from rc6_runtime.stages import StageMachine, StageViolation


class AuthorityTests(unittest.TestCase):
    def setUp(self):
        self.rt = AuthorityRuntime(b"0123456789abcdef-rc6")

    def test_role_spoof_cannot_write_case(self):
        w = self.rt.issue_identity("REQUIREMENT_ANALYZER", "REQUIREMENT_ANALYSIS", None, 0, "s1")
        with self.assertRaises(AuthorityError) as ctx:
            self.rt.issue_lease(w.worker_id, "REQ-1", ["case_candidate_l3"], [])
        self.assertEqual(str(ctx.exception), "LEASE_ARTIFACT_SCOPE_EXCEEDS_ROLE")

    def test_coordinator_cannot_write_professional_artifact(self):
        w = self.rt.issue_identity("COORDINATOR", "REQUIREMENT_ANALYSIS", None, 0, "s1")
        lease = self.rt.issue_lease(w.worker_id, "M1", ["mission_checkpoint"], [])
        with self.assertRaises(AuthorityError):
            self.rt.authorize_artifact(w.worker_id, lease.lease_id, "requirement_analysis")

    def test_same_role_rotation_preserves_role_and_layer(self):
        w1 = self.rt.issue_identity("L3_DESIGN", "TEST_DESIGN", "L3", 0, "s1")
        w2 = self.rt.rotate_same_role(w1.worker_id, "s2")
        self.assertEqual(w1.role, w2.role)
        self.assertEqual(w1.layer, w2.layer)
        self.assertEqual(w2.generation, 1)

    def test_tool_acl(self):
        w = self.rt.issue_identity("CODE_ANALYZER", "CODE_ANALYSIS", None, 0, "s1")
        lease = self.rt.issue_lease(w.worker_id, "REQ-1", ["code_analysis"], ["git", "codegraph"])
        self.rt.authorize_tool(w.worker_id, lease.lease_id, "codegraph")
        with self.assertRaises(AuthorityError):
            self.rt.authorize_tool(w.worker_id, lease.lease_id, "browser")


class BudgetTests(unittest.TestCase):
    def test_context_pre_request_guard(self):
        b = ContextBudget(1000, 0.70, 0.85)
        self.assertTrue(b.decide(300, 100, 100).allowed)
        self.assertEqual(b.decide(650, 60, 30).action, "ARTIFACTIZE_OR_SPLIT")
        self.assertEqual(b.decide(800, 40, 20).action, "ROTATE_SESSION")

    def test_provider_window_backpressure(self):
        b = ProviderBudget(2, 600, max_inflight=2)
        self.assertTrue(b.admit("dsh", now=0).allowed)
        b.complete()
        self.assertTrue(b.admit("dsh", now=1).allowed)
        b.complete()
        d = b.admit("dsh", now=2)
        self.assertFalse(d.allowed)
        self.assertEqual(d.reason, "GLOBAL_REQUEST_WINDOW_EXHAUSTED")

    def test_429_cooldown_prevents_retry_storm(self):
        b = ProviderBudget(100, 600)
        self.assertTrue(b.admit("dsh", now=0).allowed)
        b.complete()
        b.provider_error("dsh", 429, retry_after_seconds=30, now=1)
        d = b.admit("dsh", now=2)
        self.assertFalse(d.allowed)
        self.assertEqual(d.reason, "PROVIDER_COOLDOWN")


class MissionTests(unittest.TestCase):
    def test_checkpoint_resume_has_no_chat_history(self):
        with tempfile.TemporaryDirectory() as d:
            rt = MissionRuntime(d)
            s = rt.create("M-1", "BLOAN-PF1.2.0")
            s.artifact_refs = ["artifact://req/1", "artifact://code/1"]
            s.open_gaps = ["gap-1"]
            env = rt.checkpoint(s)
            self.assertEqual(env.coordinator_generation, 1)
            self.assertFalse(hasattr(env, "messages"))
            self.assertFalse(hasattr(env, "conversation"))
            loaded = rt.load("M-1")
            self.assertEqual(loaded.checkpoint_seq, 1)


class StageTests(unittest.TestCase):
    def test_fail_closed_gate(self):
        sm = StageMachine()
        with self.assertRaises(StageViolation):
            sm.enter("CODE_ANALYSIS", "FUSION", ["REQUIREMENT_SUFFICIENT"])
        self.assertEqual(
            sm.enter("CODE_ANALYSIS", "FUSION", ["REQUIREMENT_SUFFICIENT", "CODE_SUFFICIENT"]),
            "FUSION",
        )


if __name__ == "__main__":
    unittest.main()
