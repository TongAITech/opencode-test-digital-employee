from __future__ import annotations

import pytest

from rc7_runtime.execution_oracle import RuntimeOracleError, RuntimeOracleEvaluator


def test_runtime_oracle_evaluates_real_actual_result_independently():
    oracle = {
        "runtime_checks": [
            {"id": "O-1", "actual_path": "http.status", "operator": "EQ", "expected": 200},
            {"id": "O-2", "actual_path": "body.business_code", "operator": "EQ", "expected": "ACCEPTED"},
            {"id": "O-3", "actual_path": "db.rate", "operator": "GTE", "expected": 0.01},
        ]
    }
    actual = {
        "http": {"status": 200},
        "body": {"business_code": "ACCEPTED"},
        "db": {"rate": 0.035},
    }

    result = RuntimeOracleEvaluator().evaluate(oracle, actual)

    assert result.passed is True
    assert result.assertion_ref.startswith("assertion://rc7/")
    assert all(item.passed for item in result.check_results)


def test_worker_success_claim_cannot_hide_oracle_mismatch():
    oracle = {
        "runtime_checks": [
            {"id": "O-1", "actual_path": "body.business_code", "operator": "EQ", "expected": "ACCEPTED"}
        ]
    }
    actual = {"body": {"business_code": "REJECTED"}, "worker_claim": "PASS"}

    result = RuntimeOracleEvaluator().evaluate(oracle, actual)

    assert result.passed is False
    assert result.check_results[0].reason.startswith("ORACLE_EQ_FAILED")


def test_missing_actual_path_fails_closed():
    result = RuntimeOracleEvaluator().evaluate(
        {"runtime_checks": [{"id": "O-1", "actual_path": "db.rate", "operator": "EQ", "expected": 0.03}]},
        {"body": {}},
    )

    assert result.passed is False
    assert result.check_results[0].reason == "ORACLE_EQ_FAILED:ACTUAL_PATH_MISSING"


def test_oracle_schema_requires_runtime_checks_not_only_narrative_expected():
    with pytest.raises(RuntimeOracleError, match="ORACLE_RUNTIME_CHECKS_REQUIRED"):
        RuntimeOracleEvaluator().validate({"checks": [{"type": "BUSINESS_RULE", "expected": "UPDATED"}]})
