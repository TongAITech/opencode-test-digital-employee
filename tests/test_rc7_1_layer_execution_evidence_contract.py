from __future__ import annotations

from copy import deepcopy

import pytest

from rc6_runtime.execution import ExecutionRecord
from rc7_runtime.execution_loop import ExecutionClosedLoop
from rc7_runtime.models import EvaluationResult


MISSION_ID = "MISSION-RC7-1-EVIDENCE"
CURRENT_REFS = ("EVD-ACTION", "EVD-ASSERT", "EVD-LAYER")


def _layer_evidence(layer: str):
    evidence = {
        "layer": layer,
        "case_id": "TC-001",
        "target_id": "TARGET-001",
        "mission_id": MISSION_ID,
        "attempt_id": "ATTEMPT-001",
        "worker_id": "WORKER-001",
        "session_id": "SESSION-001",
        "started_at": "2026-10-23T08:00:00Z",
        "finished_at": "2026-10-23T08:00:05Z",
        "preconditions": ["target is reachable"],
        "test_data": {"customer_id": "C001"},
        "steps": ["execute the case"],
        "expected_results": ["business assertion is true"],
        "actual_results": ["business assertion is true"],
        "assertions": [
            {
                "assertion_id": "ASSERT-001",
                "expected": "OK",
                "actual": "OK",
                "result": "PASS",
                "evidence_refs": ["EVD-ASSERT"],
            }
        ],
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
        evidence.update(
            {
                "browser": {
                    "page_open": ["/login", "/cfg/version"],
                    "actions": ["login", "query version"],
                    "state_reads": ["version row visible"],
                    "evidence_types": ["screenshot", "dom", "trace", "network"],
                    "evidence_refs": ["EVD-ACTION", "EVD-LAYER"],
                },
                "auth": {
                    "required_4a": True,
                    "method": "foura_auth.py",
                    "fresh_login": True,
                    "historical_cookie_fallback": False,
                    "expiry_relogin_supported": True,
                },
            }
        )
    elif layer == "L5":
        evidence["api_calls"] = [
            {
                "url": "/api/version/query",
                "method": "POST",
                "request": {"version": "1.2.0"},
                "response": {"code": "0000", "rows": 1},
                "status_code": 200,
                "business_code": "0000",
                "route_source": "browser_network_capture",
                "endpoint_guessed": False,
                "evidence_refs": ["EVD-ACTION"],
            }
        ]
    elif layer == "L6":
        evidence["capability"] = {
            "status": "AVAILABLE",
            "tool_name": "database-runtime",
            "evidence_refs": ["EVD-ACTION"],
        }
    elif layer == "L7":
        evidence.update(
            {
                "real_runtime_execution": True,
                "E2E_VERIFIED_REQUIRES_REAL_RUNTIME_EXECUTION": True,
                "e2e_chain": {
                    "entry": "browser entry",
                    "frontend": "page state",
                    "api": "captured request/response",
                    "service": "service result",
                    "data_or_state": "persisted state",
                    "business_result": "business result",
                    "oracle": "oracle assertion",
                    "evidence_refs": ["EVD-ACTION", "EVD-ASSERT", "EVD-LAYER"],
                },
            }
        )
    return evidence


def _record(layer: str, evidence=None) -> ExecutionRecord:
    actual = {"business_result": "OK"}
    if evidence is not None:
        actual["layer_evidence"] = evidence
    return ExecutionRecord(
        attempt_id="ATTEMPT-001",
        tc_id="TC-001",
        case_version=1,
        target_id="TARGET-001",
        layer=layer,
        worker_id="WORKER-001",
        lease_id="LEASE-001",
        status="PASS",
        integrity_passed=True,
        actual_result=actual,
        tool_call_refs=("CALL-001",),
        evidence_refs=CURRENT_REFS,
        assertion_ref="ASSERT-001",
        assertion_passed=True,
        reason=None,
    )


def _evaluate(record: ExecutionRecord):
    return ExecutionClosedLoop().evaluate(
        mission_id=MISSION_ID,
        artifact_ref="ART-EXEC-001",
        record=record,
    )


def test_l4_to_l7_generic_pass_without_layer_evidence_is_not_conclusive() -> None:
    for layer in ("L4", "L5", "L6", "L7"):
        result = _evaluate(_record(layer))
        assert result.evaluation.result == EvaluationResult.REPAIR_REQUIRED
        assert result.conclusive is False
        assert result.test_result == "INCONCLUSIVE"
        assert [gap.category for gap in result.gaps] == ["LAYER_EVIDENCE_CONTRACT_INCOMPLETE"]
        assert result.evaluation.dimensions["layer_evidence_contract_passed"] is False


@pytest.mark.parametrize("layer", ["L4", "L5", "L6", "L7"])
def test_complete_current_run_layer_evidence_can_pass(layer: str) -> None:
    result = _evaluate(_record(layer, _layer_evidence(layer)))
    assert result.evaluation.result == EvaluationResult.PASS
    assert result.conclusive is True
    assert result.test_result == "PASS"
    assert result.gaps == ()
    assert result.evaluation.dimensions["layer_evidence_contract_passed"] is True


def test_assertion_evidence_must_belong_to_current_execution() -> None:
    evidence = _layer_evidence("L5")
    evidence["assertions"][0]["evidence_refs"] = ["EVD-HISTORICAL"]
    result = _evaluate(_record("L5", evidence))
    assert result.evaluation.result == EvaluationResult.REPAIR_REQUIRED
    assert result.conclusive is False
    assert "assertions[0].evidence_refs_current_execution" in result.evaluation.dimensions["layer_evidence_contract_missing"]


def test_l4_rejects_historical_cookie_fallback_for_required_4a() -> None:
    evidence = _layer_evidence("L4")
    evidence["auth"]["historical_cookie_fallback"] = True
    result = _evaluate(_record("L4", evidence))
    assert result.evaluation.result == EvaluationResult.REPAIR_REQUIRED
    assert "auth.historical_cookie_fallback=false" in result.evaluation.dimensions["layer_evidence_contract_missing"]


def test_l5_rejects_guessed_route_even_when_http_result_looks_successful() -> None:
    evidence = _layer_evidence("L5")
    evidence["api_calls"][0]["route_source"] = "guessed"
    evidence["api_calls"][0]["endpoint_guessed"] = True
    result = _evaluate(_record("L5", evidence))
    assert result.evaluation.result == EvaluationResult.REPAIR_REQUIRED
    missing = result.evaluation.dimensions["layer_evidence_contract_missing"]
    assert "api_calls[0].route_source=browser_network_capture" in missing
    assert "api_calls[0].endpoint_guessed=false" in missing


@pytest.mark.parametrize("status", ["BLOCKED_ENVIRONMENT", "HUMAN_REQUIRED"])
def test_l6_unavailable_capability_cannot_be_degraded_to_pass(status: str) -> None:
    evidence = _layer_evidence("L6")
    evidence["capability"]["status"] = status
    result = _evaluate(_record("L6", evidence))
    assert result.evaluation.result == EvaluationResult.REPAIR_REQUIRED
    assert result.conclusive is False
    assert "capability.status_not_passable:%s" % status in result.evaluation.dimensions["layer_evidence_contract_missing"]


def test_l7_requires_real_runtime_execution_invariant() -> None:
    evidence = _layer_evidence("L7")
    evidence["real_runtime_execution"] = False
    evidence["E2E_VERIFIED_REQUIRES_REAL_RUNTIME_EXECUTION"] = False
    result = _evaluate(_record("L7", evidence))
    assert result.evaluation.result == EvaluationResult.REPAIR_REQUIRED
    missing = result.evaluation.dimensions["layer_evidence_contract_missing"]
    assert "real_runtime_execution=true" in missing
    assert "E2E_VERIFIED_REQUIRES_REAL_RUNTIME_EXECUTION=true" in missing


def test_l1_to_l3_behavior_is_unchanged_by_rc7_1_layer_gate() -> None:
    for layer in ("L1", "L2", "L3"):
        result = _evaluate(_record(layer))
        assert result.evaluation.result == EvaluationResult.PASS
        assert result.conclusive is True
        assert result.test_result == "PASS"
        assert result.evaluation.dimensions["layer_evidence_contract_required"] is False
