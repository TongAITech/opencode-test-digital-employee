import tempfile
from pathlib import Path

from rc6_runtime import TruthRuntime


RELEASE = "BLOAN-PF1.2.0"
REQ = "STBB19-320"
TC = "TC-L3-R1"


def test_execution_closure_artifacts_share_canonical_r1_and_replay_deterministically():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "r1" / "event-stream.jsonl"
        truth = TruthRuntime(path)
        spec = {
            "spec_id": "XSPEC-1", "release_id": RELEASE, "requirement_id": REQ,
            "sst_id": "STB915-7489", "tc_id": TC, "case_version": 1, "layer": "L3",
            "case_fingerprint": "case-fp", "oracle_fingerprint": "oracle-fp",
            "target_requirements": ["TARGET-READY"], "preconditions": [],
            "test_data_refs": ["data://1"], "ordered_actions": [{"order": 1, "action": "call"}],
            "oracle_refs": ["oracle://1"], "evidence_requirements": ["response"],
            "cleanup_policy": {"mode": "NONE"}, "runner_type": "PYTEST",
            "automation_mapping": {"reuse": {}}, "status": "EXECUTABLE_SPEC",
        }
        truth.append_atomic("EXECUTABLE_TEST_SPEC_UPSERTED", spec)
        script = {
            "script_id": "SCRIPT-1", "release_id": RELEASE, "requirement_id": REQ,
            "tc_id": TC, "case_version": 1, "layer": "L3", "spec_id": "XSPEC-1",
            "runner_type": "PYTEST", "source_ref": "file://test_l3.py", "test_symbol": "test_l3",
            "case_fingerprint": "case-fp", "oracle_fingerprint": "oracle-fp",
            "reuse_refs": ["api-client://cfg-data"], "builder_evidence_refs": ["evidence://builder"],
            "revision": 1, "status": "SCRIPT_GENERATED",
        }
        truth.append_atomic("SCRIPT_ARTIFACT_UPSERTED", script)
        validation = {
            "validation_id": "VAL-1", "release_id": RELEASE, "script_id": "SCRIPT-1",
            "runner_type": "PYTEST", "test_symbol": "test_l3",
            "steps": [{"name": "collect", "exit_code": 0, "passed": True}],
            "evidence_refs": ["stdout://collect"], "status": "SCRIPT_READY",
        }
        truth.append_atomic("SCRIPT_VALIDATION_UPSERTED", validation)
        diagnosis = {
            "diagnosis_id": "DIAG-1", "release_id": RELEASE, "attempt_id": "ATT-1",
            "failure_class": "ROUTE", "evidence_refs": ["evidence://route-404"],
            "classifier_ref": "classifier://deterministic", "rationale": "authoritative route mismatch",
            "failure_signature_id": "FSIG-1", "root_cause_candidate_id": "RCA-1",
        }
        truth.append_atomic("FAILURE_DIAGNOSIS_UPSERTED", diagnosis)
        rca = {
            "candidate_id": "RCA-1", "release_id": RELEASE, "attempt_id": "ATT-1",
            "symbol": "CfgDataController.apply", "call_path": ["gateway", "CfgDataController.apply"],
            "git_change_refs": ["git://diff/abc"], "requirement_refs": [REQ, "STB915-7489"],
            "evidence_refs": ["codegraph://call/1", "git://diff/abc"], "confidence": 0.91,
        }
        truth.append_atomic("ROOT_CAUSE_CANDIDATE_UPSERTED", rca)
        recovery = {
            "recovery_action_id": "REC-1", "release_id": RELEASE, "action": "RECONCILE_ROUTE_BINDING",
            "prior_attempt_id": "ATT-1", "next_attempt_id": "ATT-2", "status": "RECOVERY_EXECUTED",
            "evidence_refs": ["evidence://route/reconciled"], "output_refs": ["route-binding://v2"],
            "verified": True, "terminal_status": None,
        }
        truth.append_atomic("RECOVERY_ACTION_UPSERTED", recovery)

        before = truth.full_inventory()
        projection = truth.replay()
        after = truth.full_inventory()
        assert before == after
        assert projection.state["executable_test_specs"]["XSPEC-1"]["oracle_fingerprint"] == "oracle-fp"
        assert projection.state["script_artifacts"]["SCRIPT-1"]["spec_id"] == "XSPEC-1"
        assert projection.state["script_validations"]["VAL-1"]["status"] == "SCRIPT_READY"
        assert projection.state["failure_diagnoses"]["DIAG-1"]["root_cause_candidate_id"] == "RCA-1"
        assert projection.state["recovery_actions"]["REC-1"]["next_attempt_id"] == "ATT-2"
