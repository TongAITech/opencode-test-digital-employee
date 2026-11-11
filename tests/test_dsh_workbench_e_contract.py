"""E W0 DESIGN contract tests. These are NOT product/HTTP/R1/SSE QA."""
import copy
import hashlib
import unittest

from tools.dsh_workbench.e_contract_oracle import (
    BatchReplayOracle,
    ContractRejection,
    InMemoryCommandOracle,
    authorized_mission,
    evidence_defect_trace,
    publication_oracle,
    verified_sha256,
)


class EContractFixture(unittest.TestCase):
    def setUp(self):
        self.projects = {"alice": ["P1"], "bob": ["P2"]}
        self.missions = {"M1": ("P1", "B1"), "M2": ("P2", "B2")}
        self.commands = InMemoryCommandOracle(self.projects, self.missions)
        self.body = {
            "command_id": "cmd-1", "idempotency_key": "idem-1",
            "expected_state_revision": 4,
            "scope_ref": {"project_id": "P1", "batch_id": "B1", "mission_id": "M1"},
            "action": "pause", "reason": "controlled interruption",
        }
        self.evt = {
            "event_id": "evt-5", "project_id": "P1", "batch_id": "B1",
            "type": "nodegate.updated", "revision": 5, "truth_revision": 93,
            "source_ref": "r1:event:93", "timestamp": "2026-11-09T12:00:00+08:00",
        }

    def reject(self, code, fn):
        with self.assertRaises(ContractRejection) as caught:
            fn()
        self.assertEqual(code, caught.exception.code)

    def test_authorized_project_and_mission(self):
        self.assertEqual(("P1", "B1"), authorized_mission(
            "alice", self.projects, "P1", "M1", self.missions, "B1"))

    def test_unauthorized_before_missing_resource_lookup(self):
        self.reject("FORBIDDEN", lambda: authorized_mission(
            "alice", self.projects, "P2", "does-not-exist", self.missions, "B2"))

    def test_cross_project_mission_rejected(self):
        self.reject("FORBIDDEN", lambda: authorized_mission(
            "alice", self.projects, "P1", "M2", self.missions, "B2"))

    def test_authorized_missing_mission_is_not_found(self):
        self.reject("RESOURCE_NOT_FOUND", lambda: authorized_mission(
            "alice", self.projects, "P1", "missing", self.missions, "B1"))

    def test_cross_batch_mission_is_not_inferred_by_name(self):
        self.reject("ILLEGAL_ASSOCIATION", lambda: authorized_mission(
            "alice", self.projects, "P1", "M1", self.missions, "B2"))

    def test_trusted_principal_not_request_body(self):
        for field in ("principal", "authorization"):
            with self.subTest(field=field):
                body = dict(self.body, **{field: "root"})
                self.reject("UNTRUSTED_CLIENT_FIELDS", lambda: self.commands.submit(
                    "alice", "P1", "M1", "B1", body, 4))

    def test_forbidden_publish_and_nodegate_override(self):
        for action in ("publish", "override_nodegate", "force_pass", "execute_without_lease"):
            with self.subTest(action=action):
                body = dict(self.body, action=action)
                self.reject("FORBIDDEN_ACTION", lambda: self.commands.submit(
                    "alice", "P1", "M1", "B1", body, 4))

    def test_command_scope_and_revision_conflicts(self):
        bad = copy.deepcopy(self.body)
        bad["scope_ref"]["batch_id"] = "B2"
        self.reject("ILLEGAL_ASSOCIATION", lambda: self.commands.submit(
            "alice", "P1", "M1", "B1", bad, 4))
        self.reject("STATE_REVISION_CONFLICT", lambda: self.commands.submit(
            "alice", "P1", "M1", "B1", self.body, 5))

    def test_idempotent_replay_same_payload_and_conflicting_payload(self):
        first = self.commands.submit("alice", "P1", "M1", "B1", self.body, 4)
        replay = self.commands.submit("alice", "P1", "M1", "B1", self.body, 999)
        self.assertEqual("accepted", first["outcome"])
        self.assertEqual(first["command_ref"], replay["command_ref"])
        self.assertEqual("replay", replay["idempotency"])
        changed = dict(self.body, action="resume")
        self.reject("IDEMPOTENCY_CONFLICT", lambda: self.commands.submit(
            "alice", "P1", "M1", "B1", changed, 4))

    def test_in_memory_receipt_is_not_R1_evidence(self):
        result = self.commands.submit("alice", "P1", "M1", "B1", self.body, 4)
        self.assertTrue(result["command_ref"].startswith("fixture:"))
        self.assertNotIn("evidence_id", result)
        self.assertNotIn("nodegate", result)
        self.assertNotIn("attempt_id", result)

    def test_sse_watermark_happy_path_and_duplicate(self):
        cursor = BatchReplayOracle("P1", "B1", access_scope_revision=2,
                                   snapshot_watermark=4)
        self.assertEqual("accepted", cursor.accept(self.evt, "P1", "B1", 2))
        self.assertEqual("duplicate_ignored", cursor.accept(self.evt, "P1", "B1", 2))
        self.assertEqual(5, cursor.revision)

    def test_sse_cross_project_or_batch_cursor_forbidden(self):
        cursor = BatchReplayOracle("P1", "B1", 2, 4)
        self.reject("CURSOR_SCOPE_MISMATCH", lambda: cursor.accept(self.evt, "P2", "B1", 2))
        self.reject("CURSOR_SCOPE_MISMATCH", lambda: cursor.accept(self.evt, "P1", "B2", 2))
        bad = dict(self.evt, batch_id="B2")
        self.reject("CROSS_BATCH_EVENT", lambda: cursor.accept(bad, "P1", "B1", 2))

    def test_sse_revoked_acl_and_watermark_gap(self):
        cursor = BatchReplayOracle("P1", "B1", 2, 4)
        self.reject("ACCESS_SCOPE_REVOKED", lambda: cursor.accept(self.evt, "P1", "B1", 3))
        future = dict(self.evt, revision=7)
        self.reject("EVENT_WATERMARK_GAP", lambda: cursor.accept(future, "P1", "B1", 2))
        self.assertEqual(4, cursor.revision)

    def test_sse_duplicate_id_payload_mutation_rejected(self):
        cursor = BatchReplayOracle("P1", "B1", 2, 4)
        cursor.accept(self.evt, "P1", "B1", 2)
        forged = dict(self.evt, truth_revision=999)
        self.reject("EVENT_ID_MUTATED", lambda: cursor.accept(forged, "P1", "B1", 2))

    def test_sse_naive_timestamp_and_missing_fields_denied(self):
        cursor = BatchReplayOracle("P1", "B1", 2, 4)
        self.reject("TIMEZONE_REQUIRED", lambda: cursor.accept(
            dict(self.evt, timestamp="2026-11-09T12:00:00"), "P1", "B1", 2))
        missing = dict(self.evt)
        missing.pop("source_ref")
        self.reject("MALFORMED_EVENT", lambda: cursor.accept(missing, "P1", "B1", 2))

    def test_evidence_sha256_requires_actual_bytes(self):
        raw = b"observed-real-content"
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        self.assertTrue(verified_sha256(raw, digest))
        self.assertFalse(verified_sha256(None, digest))
        self.assertFalse(verified_sha256(raw, None))
        self.assertFalse(verified_sha256(b"tampered", digest))
        self.assertFalse(verified_sha256(raw, "0" * 64))

    def test_nodegate_pass_alone_not_publish(self):
        gate = {"decision": "PASS"}
        n10 = {"state": "COMPLETED", "convergence": "CONVERGED"}
        approval = {"decision": "APPROVED", "reviewer_id": "human-1"}
        self.assertEqual("ELIGIBLE_TO_REQUEST_ONLY",
                         publication_oracle(gate, n10, approval, [True]))
        self.assertEqual("HOLD", publication_oracle(gate, n10, approval, []))
        self.assertEqual("HOLD", publication_oracle(gate, n10, approval, [False]))
        self.assertEqual("HOLD", publication_oracle(gate, n10,
                                                   {"decision": "PENDING"}, [True]))
        self.assertEqual("HOLD", publication_oracle(gate,
                           {"state": "RUNNING", "convergence": "CONVERGED"},
                           approval, [True]))

    def test_nodegate_negative_states_never_green(self):
        n10 = {"state": "COMPLETED", "convergence": "CONVERGED"}
        approval = {"decision": "APPROVED", "reviewer_id": "human-1"}
        for state in ("NEEDS_REVISION", "BLOCKED", "HUMAN_GATE", "STALE",
                      "RUNNING", "INCONCLUSIVE", "WARN"):
            with self.subTest(state=state):
                self.assertEqual("HOLD", publication_oracle(
                    {"decision": state}, n10, approval, [True]))
        self.assertEqual("UNKNOWN", publication_oracle(
            {"decision": "PASS"}, n10, approval, [True],
            truth_available=False))

    def test_trace_requires_attempt_lease_and_verified_hash(self):
        attempt = {"mission_id": "M1", "batch_id": "B1", "attempt_id": "A1",
                   "etu_id": "E1", "workitem_id": "W1", "case_id": "C1",
                   "task_lease_ref": "lease:R1"}
        evidence = {"mission_id": "M1", "attempt_id": "A1",
                    "evidence_id": "EV1", "hash_verified": True}
        defect = {"mission_id": "M1", "batch_id": "B1",
                  "evidence_refs": ["EV1"]}
        self.assertTrue(evidence_defect_trace(attempt, evidence, defect))
        bad = dict(evidence, hash_verified=False)
        self.assertFalse(evidence_defect_trace(attempt, bad, defect))
        bad = dict(defect, batch_id="B2")
        self.assertFalse(evidence_defect_trace(attempt, evidence, bad))
        bad = dict(attempt, task_lease_ref=None)
        self.assertFalse(evidence_defect_trace(bad, evidence, defect))


if __name__ == "__main__":
    unittest.main()
