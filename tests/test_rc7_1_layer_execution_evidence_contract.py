from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from rc6_runtime.execution import ExecutionRecord
from rc7_runtime.authority import execution_session_id
from rc7_runtime.execution_loop import ExecutionClosedLoop
from rc7_runtime.models import EvaluationResult


MISSION_ID = "MISSION-RC7-1-EVIDENCE"
CURRENT_REFS = ("EVD-ACTION", "EVD-ASSERT", "EVD-LAYER", "EVD-2", "EVD-3", "EVD-4", "EVD-5", "EVD-6")


def _layer_evidence(layer: str):
    evidence = {
        "layer": layer,
        "case_id": "TC-001",
        "target_id": "TARGET-001",
        "mission_id": MISSION_ID,
        "attempt_id": "ATTEMPT-001",
        "worker_id": "WORKER-001",
        "session_id": execution_session_id("WORKER-001"),
        "started_at": "2026-10-23T08:00:00Z",
        "finished_at": "2026-10-23T08:00:05Z",
        "status": "PASS",
        "preconditions": ["target is reachable"],
        "test_data": {"customer_id": "C001"},
        "steps": ["execute the case"],
        "expected_results": ["business assertion is true"],
        "actual_results": ["business assertion is true"],
        "assertions": [{
            "assertion_id": "ASSERT-001",
            "expected": "OK",
            "actual": "OK",
            "result": "PASS",
            "evidence_refs": ["EVD-ASSERT"],
        }],
        "evidence_refs": ["EVD-LAYER", "EVD-ASSERT"],
        "execution_receipt": {
            "receipt_id": "RECEIPT-001",
            "case_id": "TC-001",
            "attempt_id": "ATTEMPT-001",
            "target_id": "TARGET-001",
            "status": "PASS",
        },
    }
    if layer == "L4":
        evidence.update({
            "browser": {
                "page_open": ["/login", "/cfg/version"],
                "actions": ["login", "query version"],
                "state_reads": ["version row visible"],
                "evidence_types": ["screenshot", "dom", "trace", "network"],
                "artifacts": {
                    "screenshot": ["EVD-ACTION"], "dom": ["EVD-LAYER"],
                    "trace": ["EVD-ACTION"], "network": ["EVD-LAYER"],
                },
                "evidence_refs": ["EVD-ACTION", "EVD-LAYER"],
            },
            "auth": {
                "required_4a": True,
                "method": "foura_auth.py",
                "fresh_login": True,
                "historical_cookie_fallback": False,
                "expiry_relogin_supported": True,
                "evidence_refs": ["EVD-ACTION"],
            },
        })
    elif layer == "L5":
        evidence.update({
            "real_runtime_execution": True,
            "E2E_VERIFIED_REQUIRES_REAL_RUNTIME_EXECUTION": True,
            "e2e_chain": {
                "entry": "browser entry", "frontend": "page state", "api": "captured request",
                "service": "service result", "data_or_state": "persisted state",
                "business_result": "business result", "oracle": "oracle assertion",
                "evidence_refs": ["EVD-ACTION", "EVD-LAYER"],
            },
        })
    elif layer == "L6":
        evidence["performance"] = {
            "tool_name": "k6", "tool_version": "0.51.0", "script_sha256": "a" * 64,
            "scenario_ref": "EVD-ACTION", "threshold_ref": "EVD-2",
            "summary_ref": "EVD-3", "stdout_ref": "EVD-4", "exit_code": 0,
            "evidence_refs": ["EVD-ACTION", "EVD-2", "EVD-3", "EVD-4"],
        }
    elif layer == "L7":
        evidence["security"] = {
            "tool_name": "zap", "tool_version": "2.15.0", "target_ref": "TARGET-001",
            "scan_config_ref": "EVD-ACTION", "spider_ref": "EVD-2",
            "passive_scan_ref": "EVD-3", "active_scan_ref": "EVD-4",
            "html_report_ref": "EVD-5", "json_report_ref": "EVD-6", "exit_code": 0,
            "evidence_refs": ["EVD-ACTION", "EVD-2", "EVD-3", "EVD-4", "EVD-5", "EVD-6"],
        }
    return evidence


def _record(layer: str, evidence=None, evidence_refs=CURRENT_REFS) -> ExecutionRecord:
    actual = {"business_result": "OK"}
    if evidence is not None:
        actual["layer_evidence"] = evidence
    return ExecutionRecord(
        attempt_id="ATTEMPT-001", tc_id="TC-001", case_version=1, target_id="TARGET-001",
        layer=layer, worker_id="WORKER-001", lease_id="LEASE-001", status="PASS",
        integrity_passed=True, actual_result=actual, tool_call_refs=("CALL-001",),
        evidence_refs=tuple(evidence_refs), assertion_ref="ASSERT-001", assertion_passed=True, reason=None,
    )


def _evaluate(record: ExecutionRecord):
    return ExecutionClosedLoop().evaluate(mission_id=MISSION_ID, artifact_ref="ART-EXEC-001", record=record)


def _canonical_runtime_evidence_id(raw_ref: str) -> str:
    digest = ""
    if raw_ref.startswith("file://"):
        path = Path(raw_ref[len("file://"):])
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
    payload = "\x1f".join((MISSION_ID, "ATTEMPT-001", raw_ref, digest)).encode("utf-8")
    return "EVD-EXEC-RUNTIME-%s" % hashlib.sha256(payload).hexdigest()[:20]


def test_l4_to_l7_generic_pass_without_layer_evidence_is_not_conclusive() -> None:
    for layer in ("L4", "L5", "L6", "L7"):
        result = _evaluate(_record(layer))
        assert result.evaluation.result == EvaluationResult.REPAIR_REQUIRED
        assert result.conclusive is False
        assert result.test_result == "INCONCLUSIVE"
        assert [gap.category for gap in result.gaps] == ["LAYER_EVIDENCE_CONTRACT_INCOMPLETE"]


@pytest.mark.parametrize("layer", ["L4", "L5", "L6", "L7"])
def test_complete_current_run_canonical_layer_evidence_can_pass(layer: str) -> None:
    result = _evaluate(_record(layer, _layer_evidence(layer)))
    assert result.evaluation.result == EvaluationResult.PASS
    assert result.conclusive is True
    assert result.test_result == "PASS"
    assert result.gaps == ()
    assert result.evaluation.dimensions["layer_evidence_contract_passed"] is True


def test_l4_rejects_historical_cookie_fallback() -> None:
    evidence = _layer_evidence("L4")
    evidence["auth"]["historical_cookie_fallback"] = True
    result = _evaluate(_record("L4", evidence))
    assert result.evaluation.result == EvaluationResult.REPAIR_REQUIRED
    assert "auth.historical_cookie_fallback=false" in result.evaluation.dimensions["layer_evidence_contract_missing"]


def test_l5_requires_real_cross_system_e2e_not_old_api_only_payload() -> None:
    evidence = _layer_evidence("L5")
    evidence.pop("e2e_chain")
    evidence["api_calls"] = [{"url": "/api/version/query", "status_code": 200}]
    result = _evaluate(_record("L5", evidence))
    assert result.evaluation.result == EvaluationResult.REPAIR_REQUIRED
    assert "e2e_chain" in result.evaluation.dimensions["layer_evidence_contract_missing"]


def test_l6_requires_k6_performance_evidence_not_old_capability_payload() -> None:
    evidence = _layer_evidence("L6")
    evidence.pop("performance")
    evidence["capability"] = {"status": "AVAILABLE", "tool_name": "database-runtime", "evidence_refs": ["EVD-ACTION"]}
    result = _evaluate(_record("L6", evidence))
    assert result.evaluation.result == EvaluationResult.REPAIR_REQUIRED
    assert "performance" in result.evaluation.dimensions["layer_evidence_contract_missing"]


def test_l7_requires_zap_security_evidence_not_old_e2e_payload() -> None:
    evidence = _layer_evidence("L7")
    evidence.pop("security")
    evidence["real_runtime_execution"] = True
    evidence["E2E_VERIFIED_REQUIRES_REAL_RUNTIME_EXECUTION"] = True
    evidence["e2e_chain"] = {key: "x" for key in ("entry", "frontend", "api", "service", "data_or_state", "business_result", "oracle")}
    evidence["e2e_chain"]["evidence_refs"] = ["EVD-ACTION"]
    result = _evaluate(_record("L7", evidence))
    assert result.evaluation.result == EvaluationResult.REPAIR_REQUIRED
    assert "security" in result.evaluation.dimensions["layer_evidence_contract_missing"]


def test_file_backed_performance_evidence_must_resolve_to_current_attempt(tmp_path: Path) -> None:
    refs = []
    canonical = []
    for name in ("scenario", "threshold", "summary", "stdout"):
        proof = tmp_path / (name + ".json")
        proof.write_text('{"captured":true}\n', encoding="utf-8")
        raw = "file://" + str(proof.resolve())
        refs.append(raw)
        canonical.append(_canonical_runtime_evidence_id(raw))
    evidence = _layer_evidence("L6")
    evidence["evidence_refs"] = refs
    evidence["assertions"][0]["evidence_refs"] = [refs[0]]
    perf = evidence["performance"]
    perf.update({
        "scenario_ref": refs[0], "threshold_ref": refs[1], "summary_ref": refs[2], "stdout_ref": refs[3],
        "evidence_refs": refs,
    })
    result = _evaluate(_record("L6", evidence, evidence_refs=tuple(canonical)))
    assert result.evaluation.result == EvaluationResult.PASS

    stale = _evaluate(_record("L6", evidence, evidence_refs=("EVD-EXEC-RUNTIME-HISTORICAL",)))
    assert stale.evaluation.result == EvaluationResult.REPAIR_REQUIRED


def test_l1_to_l3_behavior_is_unchanged_by_layer_gate() -> None:
    for layer in ("L1", "L2", "L3"):
        result = _evaluate(_record(layer))
        assert result.evaluation.result == EvaluationResult.PASS
        assert result.conclusive is True
        assert result.test_result == "PASS"
        assert result.evaluation.dimensions["layer_evidence_contract_required"] is False
