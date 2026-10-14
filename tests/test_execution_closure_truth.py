import tempfile
from copy import deepcopy
from pathlib import Path

from rc6_runtime import TruthRuntime


RELEASE = "BLOAN-PF1.2.0"
REQ = "STBB19-320"
SST = "STB915-7489"
TC = "TC-L3-R1"


def test_execution_closure_artifacts_share_canonical_r1_and_replay_deterministically():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "r1" / "event-stream.jsonl"
        truth = TruthRuntime(path)

        case = {
            "tc_id": TC, "case_version": 1, "release_id": RELEASE, "requirement_id": REQ,
            "sst_id": SST, "condition_id": "COND-R1", "objective": "trace execution closure",
            "layer": "L3", "preconditions": [], "test_data": {}, "steps": ["call API"],
            "expected": "code 0000", "oracle": {"type": "field_equals", "field": "code", "value": "0000"},
            "evidence_requirements": ["request", "response", "oracle"], "status": "FROZEN",
        }
        truth.append_atomic("TEST_CASE_UPSERTED", case)

        spec = {
            "spec_id": "XSPEC-1", "release_id": RELEASE, "requirement_id": REQ,
            "sst_id": SST, "tc_id": TC, "case_version": 1, "layer": "L3",
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
            "sst_id": SST, "tc_id": TC, "case_version": 1, "layer": "L3", "spec_id": "XSPEC-1",
            "runner_type": "PYTEST", "source_ref": "file://test_l3.py", "test_symbol": "test_l3",
            "case_fingerprint": "case-fp", "oracle_fingerprint": "oracle-fp",
            "reuse_refs": ["api-client://cfg-data"], "builder_evidence_refs": ["evidence://builder"],
            "revision": 1, "status": "SCRIPT_GENERATED",
        }
        truth.append_atomic("SCRIPT_ARTIFACT_UPSERTED", script)

        validation = {
            "validation_id": "VAL-1", "release_id": RELEASE, "requirement_id": REQ,
            "sst_id": SST, "tc_id": TC, "case_version": 1, "spec_id": "XSPEC-1", "script_id": "SCRIPT-1",
            "runner_type": "PYTEST", "test_symbol": "test_l3",
            "steps": [{"name": "collect", "exit_code": 0, "passed": True}],
            "evidence_refs": ["stdout://collect"], "status": "SCRIPT_READY",
        }
        truth.append_atomic("SCRIPT_VALIDATION_UPSERTED", validation)

        attempt = {
            "attempt_id": "ATT-1", "release_id": RELEASE, "requirement_id": REQ, "sst_id": SST,
            "tc_id": TC, "case_version": 1, "target_id": "TARGET-R1", "layer": "L3", "status": "FAIL",
            "actual_result": {"http_status": 200, "code": "9999"},
            "tool_call_refs": ["toolcall://api/ATT-1"], "evidence_refs": ["evidence://actual/ATT-1"],
            "spec_id": "XSPEC-1", "script_id": "SCRIPT-1", "validation_id": "VAL-1",
        }
        truth.append_atomic("EXECUTION_ATTEMPT_UPSERTED", attempt)

        assertion = {
            "id": "ASSERT-1", "release_id": RELEASE, "attempt_id": "ATT-1", "tc_id": TC,
            "oracle_ref": "oracle://1", "passed": False, "evidence_refs": ["evidence://oracle/ATT-1"],
            "spec_id": "XSPEC-1", "oracle_fingerprint": "oracle-fp",
        }
        truth.append_atomic("ASSERTION_UPSERTED", assertion)

        evidence = {
            "id": "EVID-1", "release_id": RELEASE, "kind": "EXECUTION", "ref": "evidence://actual/ATT-1",
            "source_artifact_ref": "attempt://ATT-1", "requirement_id": REQ, "tc_id": TC, "attempt_id": "ATT-1",
            "metadata": {"spec_id": "XSPEC-1", "script_id": "SCRIPT-1", "validation_id": "VAL-1"},
        }
        truth.append_atomic("EVIDENCE_UPSERTED", evidence)

        diagnosis = {
            "diagnosis_id": "DIAG-1", "release_id": RELEASE, "attempt_id": "ATT-1",
            "failure_class": "PRODUCT", "evidence_refs": ["evidence://actual/ATT-1", "evidence://oracle/ATT-1"],
            "classifier_ref": "classifier://deterministic", "rationale": "test side verified; product response violates oracle",
            "failure_signature_id": "FSIG-1", "root_cause_candidate_id": "RCA-1",
        }
        truth.append_atomic("FAILURE_DIAGNOSIS_UPSERTED", diagnosis)

        rca = {
            "candidate_id": "RCA-1", "release_id": RELEASE, "attempt_id": "ATT-1",
            "symbol": "CfgDataService.apply", "call_path": ["CfgDataController.apply", "CfgDataService.apply"],
            "git_change_refs": ["git://diff/abc"], "requirement_refs": [REQ, SST],
            "evidence_refs": ["codegraph://call/1", "git://diff/abc"], "confidence": 0.91,
        }
        truth.append_atomic("ROOT_CAUSE_CANDIDATE_UPSERTED", rca)

        recovery = {
            "recovery_action_id": "REC-1", "release_id": RELEASE, "action": "PRODUCT_DEFECT",
            "prior_attempt_id": "ATT-1", "next_attempt_id": None, "status": "TERMINAL",
            "evidence_refs": ["evidence://actual/ATT-1", "evidence://oracle/ATT-1"],
            "output_refs": ["defect-candidate://ATT-1/FSIG-1"],
            "verified": True, "terminal_status": "PRODUCT_DEFECT_CONFIRMED",
        }
        truth.append_atomic("RECOVERY_ACTION_UPSERTED", recovery)

        defect = {
            "id": "DEFECT-1", "release_id": RELEASE, "requirement_id": REQ, "sst_id": SST,
            "tc_id": TC, "attempt_id": "ATT-1", "title": "SUT response violates frozen oracle",
            "severity": "MEDIUM", "status": "CANDIDATE",
            "evidence_refs": ["evidence://actual/ATT-1", "evidence://oracle/ATT-1", "codegraph://call/1"],
            "failure_diagnosis_ref": "diagnosis://DIAG-1", "root_cause_candidate_ref": "root-cause://RCA-1",
            "recovery_action_ref": "recovery://REC-1", "defect_candidate_ref": "defect-candidate://ATT-1/FSIG-1",
        }
        truth.append_atomic("DEFECT_UPSERTED", defect)

        before_inventory = deepcopy(truth.full_inventory())
        before_snapshot = deepcopy(truth.projection.snapshot())
        replay_snapshot = truth.rebuild_projection()
        after_inventory = truth.full_inventory()
        second_replay_snapshot = truth.rebuild_projection()

        assert before_inventory == after_inventory
        assert replay_snapshot == before_snapshot
        assert second_replay_snapshot == replay_snapshot
        assert truth.projection.cases[TC]["status"] == "FROZEN"
        assert truth.projection.executable_test_specs["XSPEC-1"]["oracle_fingerprint"] == "oracle-fp"
        assert truth.projection.script_artifacts["SCRIPT-1"]["spec_id"] == "XSPEC-1"
        assert truth.projection.script_validations["VAL-1"]["script_id"] == "SCRIPT-1"
        assert truth.projection.execution_attempts["ATT-1"]["spec_id"] == "XSPEC-1"
        assert truth.projection.assertions["ASSERT-1"]["attempt_id"] == "ATT-1"
        assert truth.projection.evidence["EVID-1"]["source_artifact_ref"] == "attempt://ATT-1"
        assert truth.projection.failure_diagnoses["DIAG-1"]["root_cause_candidate_id"] == "RCA-1"
        assert truth.projection.recovery_actions["REC-1"]["output_refs"] == ["defect-candidate://ATT-1/FSIG-1"]
        assert truth.projection.defects["DEFECT-1"]["attempt_id"] == "ATT-1"
        assert truth.projection.defects["DEFECT-1"]["defect_candidate_ref"] == "defect-candidate://ATT-1/FSIG-1"
