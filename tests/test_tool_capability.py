import unittest

from rc6_runtime.capability import ToolCapabilityBroker, ToolCapabilityError


class CapabilityBrokerTests(unittest.TestCase):
    def setUp(self):
        self.broker = ToolCapabilityBroker()
        self.tool = "codegraph"
        self.worker = "worker-code-1"
        self.target = "TARGET-abc"

    def test_binary_found_is_not_ready(self):
        self.broker.discover(self.tool, "D:/tools/codegraph.exe")
        self.broker.mark_executable(self.tool, "exec://codegraph")
        states = self.broker.readiness(self.tool, self.worker, self.target)
        self.assertTrue(states["DISCOVERED"])
        self.assertTrue(states["EXECUTABLE"])
        self.assertFalse(states["READY"])
        admission = self.broker.admit(self.worker, [self.tool], self.target)
        self.assertFalse(admission.ready)
        self.assertIn("REGISTERED", admission.blocked[self.tool])

    def test_probe_success_requires_real_evidence(self):
        self.broker.discover(self.tool, "D:/tools/codegraph.exe")
        self.broker.mark_executable(self.tool, "exec://codegraph")
        self.broker.register(self.tool, "mcp://codegraph")
        with self.assertRaises(ToolCapabilityError) as ctx:
            self.broker.record_probe(self.tool, success=True, tool_call_ref=None, evidence_ref=None)
        self.assertEqual(str(ctx.exception), "REAL_PROBE_EVIDENCE_REQUIRED")

    def test_full_staged_capability_passes_for_exact_worker_and_target(self):
        self.broker.discover(self.tool, "D:/tools/codegraph.exe")
        self.broker.mark_executable(self.tool, "exec://codegraph")
        self.broker.register(self.tool, "mcp://codegraph")
        self.broker.bind_worker(self.tool, self.worker, visible=True, permitted=True)
        self.broker.record_probe(
            self.tool,
            success=True,
            tool_call_ref="toolcall://probe/codegraph/1",
            evidence_ref="evidence://probe/codegraph/1",
        )
        self.broker.mark_target_ready(self.tool, self.target, "evidence://target/codegraph/1")
        states = self.broker.readiness(self.tool, self.worker, self.target)
        self.assertTrue(states["READY"])
        admission = self.broker.admit(self.worker, [self.tool], self.target)
        self.assertTrue(admission.ready)
        evidence = self.broker.record_tool_call(
            self.tool,
            worker_id=self.worker,
            target_id=self.target,
            call_ref="toolcall://codegraph/analyze/42",
            evidence_ref="evidence://codegraph/analyze/42",
        )
        self.assertEqual(evidence.tool_id, self.tool)

    def test_wrong_worker_visibility_blocks(self):
        self.broker.discover(self.tool, "D:/tools/codegraph.exe")
        self.broker.mark_executable(self.tool, "exec://codegraph")
        self.broker.register(self.tool, "mcp://codegraph")
        self.broker.bind_worker(self.tool, self.worker, visible=True, permitted=True)
        self.broker.record_probe(self.tool, success=True, tool_call_ref="c", evidence_ref="e")
        self.broker.mark_target_ready(self.tool, self.target, "target-e")
        admission = self.broker.admit("other-worker", [self.tool], self.target)
        self.assertFalse(admission.ready)
        self.assertIn("VISIBLE_TO_WORKER", admission.blocked[self.tool])

    def test_permission_denied_blocks_even_when_visible(self):
        self.broker.discover(self.tool, "D:/tools/codegraph.exe")
        self.broker.mark_executable(self.tool, "exec://codegraph")
        self.broker.register(self.tool, "mcp://codegraph")
        self.broker.bind_worker(self.tool, self.worker, visible=True, permitted=False)
        self.broker.record_probe(self.tool, success=True, tool_call_ref="c", evidence_ref="e")
        self.broker.mark_target_ready(self.tool, self.target, "target-e")
        admission = self.broker.admit(self.worker, [self.tool], self.target)
        self.assertFalse(admission.ready)
        self.assertIn("PERMISSION_OK", admission.blocked[self.tool])

    def test_wrong_target_blocks(self):
        self.broker.discover(self.tool, "D:/tools/codegraph.exe")
        self.broker.mark_executable(self.tool, "exec://codegraph")
        self.broker.register(self.tool, "mcp://codegraph")
        self.broker.bind_worker(self.tool, self.worker, visible=True, permitted=True)
        self.broker.record_probe(self.tool, success=True, tool_call_ref="c", evidence_ref="e")
        self.broker.mark_target_ready(self.tool, self.target, "target-e")
        admission = self.broker.admit(self.worker, [self.tool], "TARGET-other")
        self.assertFalse(admission.ready)
        self.assertIn("TARGET_READY", admission.blocked[self.tool])

    def test_missing_tool_fails_closed(self):
        admission = self.broker.admit(self.worker, ["browser-skill"], self.target)
        self.assertFalse(admission.ready)
        self.assertEqual(admission.blocked["browser-skill"], ["DISCOVERED"])


if __name__ == "__main__":
    unittest.main()
