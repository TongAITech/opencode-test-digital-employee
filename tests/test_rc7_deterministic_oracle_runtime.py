from __future__ import annotations

import pytest

from rc7_runtime.oracle_runtime import DeterministicOracleError, DeterministicOracleRuntime


def test_oracle_uses_fixed_path_operator_and_expected_value():
    oracle = {
        "checks": [
            {
                "id": "CHK-CODE",
                "type": "BUSINESS_RULE",
                "actual_path": "response.business_code",
                "operator": "EQ",
                "expected": "OK",
                "evidence_ref": "design-evidence://business-code",
            },
            {
                "id": "CHK-BALANCE",
                "type": "BUSINESS_RULE",
                "actual_path": "db.after.balance",
                "operator": "GTE",
                "expected": 0,
                "evidence_ref": "design-evidence://balance",
            },
        ]
    }
    result = DeterministicOracleRuntime().evaluate(
        oracle,
        {"response": {"business_code": "OK"}, "db": {"after": {"balance": 12}}},
        {"attempt_id": "ATT-1"},
    )
    assert result["passed"] is True
    assert result["assertion_ref"].startswith("oracle-assertion://")
    assert result["evidence_refs"][0].startswith("oracle-runtime://")
    assert all(item["passed"] for item in result["details"]["checks"])


def test_oracle_fail_is_deterministic_and_not_reinterpreted():
    oracle = {
        "checks": [
            {
                "id": "CHK-CODE",
                "type": "BUSINESS_RULE",
                "actual_path": "business_code",
                "operator": "EQ",
                "expected": "OK",
            }
        ]
    }
    result = DeterministicOracleRuntime().evaluate(
        oracle,
        {"business_code": "LIMIT_EXCEEDED"},
        {"attempt_id": "ATT-2"},
    )
    assert result["passed"] is False
    check = result["details"]["checks"][0]
    assert check["expected"] == "OK"
    assert check["actual"] == "LIMIT_EXCEEDED"
    assert check["passed"] is False


def test_oracle_contract_without_actual_path_or_operator_is_rejected():
    with pytest.raises(DeterministicOracleError, match="ORACLE_ACTUAL_PATH_REQUIRED"):
        DeterministicOracleRuntime.validate_contract(
            {"checks": [{"id": "CHK-1", "type": "BUSINESS_RULE", "expected": "OK"}]}
        )

    with pytest.raises(DeterministicOracleError, match="ORACLE_OPERATOR_UNSUPPORTED"):
        DeterministicOracleRuntime.validate_contract(
            {
                "checks": [
                    {
                        "id": "CHK-1",
                        "type": "BUSINESS_RULE",
                        "actual_path": "business_code",
                        "operator": "ASK_AI",
                        "expected": "OK",
                    }
                ]
            }
        )
