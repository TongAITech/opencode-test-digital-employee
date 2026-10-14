from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from rc6_release.mcp_server import handle


def call(name, arguments):
    response = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
    result = response["result"]
    text = result["content"][0]["text"]
    return result.get("isError", False), json.loads(text) if text.startswith(("{", "[")) else text


def intent():
    return {
        "id": "INT-001",
        "release_id": "BLOAN-PF1.2.0",
        "requirement_id": "STBB19-320",
        "sst_id": "STB915-7489",
        "objective": "verify version behavior",
        "source_refs": ["source://req/STBB19-320/1"],
        "artifact_version": 1,
    }


def case(layer="L3"):
    return {
        "tc_id": "TC-001",
        "case_version": 1,
        "release_id": "BLOAN-PF1.2.0",
        "requirement_id": "STBB19-320",
        "sst_id": "STB915-7489",
        "condition_id": "COND-001",
        "layer": layer,
        "objective": "API contract",
        "preconditions": ["target ready"],
        "test_data": {"id": "D1"},
        "steps": ["invoke API"],
        "expected": "business response is correct",
        "oracle": {"type": "business", "assert": "expected state"},
        "evidence_requirements": ["actual_result", "tool_call_ref"],
        "status": "CANDIDATE",
    }


class McpGovernedControlPlaneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.old_home = os.environ.get("PFC_AITEST_HOME")
        cls.old_state = os.environ.get("PFC_AITEST_STATE_DIR")
        os.environ["PFC_AITEST_HOME"] = cls.tmp.name
        os.environ["PFC_AITEST_STATE_DIR"] = str(Path(cls.tmp.name) / "state")

    @classmethod
    def tearDownClass(cls):
        if cls.old_home is None:
            os.environ.pop("PFC_AITEST_HOME", None)
        else:
            os.environ["PFC_AITEST_HOME"] = cls.old_home
        if cls.old_state is None:
            os.environ.pop("PFC_AITEST_STATE_DIR", None)
        else:
            os.environ["PFC_AITEST_STATE_DIR"] = cls.old_state
        cls.tmp.cleanup()

    def test_control_surface_is_not_only_prompt_or_mission_tools(self):
        listed = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        names = {tool["name"] for tool in listed["result"]["tools"]}
        required = {
            "worker_issue", "lease_issue", "tool_authorize", "artifact_record", "truth_inventory", "truth_query",
            "reality_upsert", "reality_reconcile", "target_build", "capability_admit", "capability_record_call",
        }
        self.assertTrue(required.issubset(names))
        self.assertGreaterEqual(len(names), 20)

    def test_coordinator_cannot_elevate_lease_to_requirement_analysis(self):
        err, worker = call("worker_issue", {"role": "COORDINATOR", "phase": "REQUIREMENT_ANALYSIS", "layer": None, "generation": 0, "session_id": "s-coord"})
        self.assertFalse(err)
        err, message = call("lease_issue", {"worker_id": worker["worker_id"], "scope_ref": "M-1", "allowed_artifact_types": ["requirement_analysis"], "allowed_tools": []})
        self.assertTrue(err)
        self.assertEqual(message, "LEASE_ARTIFACT_SCOPE_EXCEEDS_ROLE")

    def test_fusion_worker_can_atomically_record_intent_and_query_it(self):
        err, worker = call("worker_issue", {"role": "TEST_FUSION", "phase": "FUSION", "layer": None, "generation": 0, "session_id": "s-fusion"})
        self.assertFalse(err)
        err, lease = call("lease_issue", {"worker_id": worker["worker_id"], "scope_ref": "STBB19-320", "allowed_artifact_types": ["test_intent"], "allowed_tools": []})
        self.assertFalse(err)
        err, receipt = call("artifact_record", {"worker_id": worker["worker_id"], "lease_id": lease["lease_id"], "authorization_artifact_type": "test_intent", "payload": intent()})
        self.assertFalse(err)
        self.assertEqual(receipt["status"], "PERSISTENCE_VERIFIED")
        err, rows = call("truth_query", {"artifact_type": "test_intent", "filters": {"requirement_id": "STBB19-320"}, "limit": 20})
        self.assertFalse(err)
        self.assertEqual(rows["total"], 1)

    def test_layer_authority_rejects_cross_layer_case(self):
        err, worker = call("worker_issue", {"role": "L3_DESIGN", "phase": "TEST_DESIGN", "layer": "L3", "generation": 0, "session_id": "s-l3"})
        self.assertFalse(err)
        err, lease = call("lease_issue", {"worker_id": worker["worker_id"], "scope_ref": "COND-001", "allowed_artifact_types": ["case_candidate_l3"], "allowed_tools": []})
        self.assertFalse(err)
        err, message = call("artifact_record", {"worker_id": worker["worker_id"], "lease_id": lease["lease_id"], "authorization_artifact_type": "case_candidate_l3", "payload": case("L2")})
        self.assertTrue(err)
        self.assertEqual(message, "CASE_LAYER_AUTHORITY_MISMATCH")
        err, receipt = call("artifact_record", {"worker_id": worker["worker_id"], "lease_id": lease["lease_id"], "authorization_artifact_type": "case_candidate_l3", "payload": case("L3")})
        self.assertFalse(err)
        self.assertEqual(receipt["status"], "PERSISTENCE_VERIFIED")

    def test_capability_admission_fails_closed_when_tool_not_proven(self):
        err, admission = call("capability_admit", {"worker_id": "wrk-unbound", "required_tools": ["codegraph"], "target_id": "TARGET-x"})
        self.assertFalse(err)
        self.assertFalse(admission["ready"])
        self.assertIn("codegraph", admission["blocked"])

    def test_reality_plaintext_secret_is_rejected_through_mcp(self):
        err, message = call("reality_upsert", {"kind": "account", "fact_id": "bad", "attributes": {"username": "u", "password": "plaintext"}, "status": "READY"})
        self.assertTrue(err)
        self.assertIn("SECRET", message.upper())


if __name__ == "__main__":
    unittest.main()
