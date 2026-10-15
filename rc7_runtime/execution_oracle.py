"""Deterministic RC7 runtime Oracle evaluation.

Generated scripts may collect observations, but they cannot be the only Oracle
authority. RC7 evaluates a frozen TestCase ``oracle.runtime_checks`` against the
runner's observed ``actual_result`` and emits a stable assertion identity.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Dict, Mapping, Sequence, Tuple


class RuntimeOracleError(RuntimeError):
    pass


_ALLOWED_OPERATORS = {
    "EQ", "NE", "IN", "NOT_IN", "EXISTS", "NOT_EXISTS",
    "GT", "GTE", "LT", "LTE", "CONTAINS", "MATCHES",
}
_MISSING = object()


@dataclass(frozen=True)
class RuntimeOracleCheckResult:
    check_id: str
    operator: str
    actual_path: str
    passed: bool
    actual_value: Any
    expected_value: Any
    reason: str


@dataclass(frozen=True)
class RuntimeOracleResult:
    assertion_ref: str
    passed: bool
    check_results: Tuple[RuntimeOracleCheckResult, ...]


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _resolve_path(root: Any, path: str) -> Any:
    if path in {"$", ""}:
        return root
    current = root
    normalized = path[2:] if path.startswith("$.") else path
    for token in normalized.split("."):
        if isinstance(current, Mapping):
            if token not in current:
                return _MISSING
            current = current[token]
            continue
        if isinstance(current, (list, tuple)):
            try:
                index = int(token)
            except ValueError:
                return _MISSING
            if index < 0 or index >= len(current):
                return _MISSING
            current = current[index]
            continue
        return _MISSING
    return current


def _compare(operator: str, actual: Any, expected: Any) -> Tuple[bool, str]:
    if operator == "EXISTS":
        return actual is not _MISSING, "PATH_EXISTS" if actual is not _MISSING else "PATH_MISSING"
    if operator == "NOT_EXISTS":
        return actual is _MISSING, "PATH_MISSING" if actual is _MISSING else "PATH_EXISTS"
    if actual is _MISSING:
        return False, "ACTUAL_PATH_MISSING"
    if operator == "EQ":
        return actual == expected, "EQ"
    if operator == "NE":
        return actual != expected, "NE"
    if operator == "IN":
        if not isinstance(expected, (list, tuple, set)):
            raise RuntimeOracleError("ORACLE_IN_EXPECTED_COLLECTION_REQUIRED")
        return actual in expected, "IN"
    if operator == "NOT_IN":
        if not isinstance(expected, (list, tuple, set)):
            raise RuntimeOracleError("ORACLE_NOT_IN_EXPECTED_COLLECTION_REQUIRED")
        return actual not in expected, "NOT_IN"
    if operator in {"GT", "GTE", "LT", "LTE"}:
        if not isinstance(actual, (int, float)) or isinstance(actual, bool) or not isinstance(expected, (int, float)) or isinstance(expected, bool):
            raise RuntimeOracleError("ORACLE_NUMERIC_OPERANDS_REQUIRED")
        if operator == "GT":
            return actual > expected, "GT"
        if operator == "GTE":
            return actual >= expected, "GTE"
        if operator == "LT":
            return actual < expected, "LT"
        return actual <= expected, "LTE"
    if operator == "CONTAINS":
        if isinstance(actual, str):
            return str(expected) in actual, "CONTAINS"
        if isinstance(actual, (list, tuple, set, dict)):
            return expected in actual, "CONTAINS"
        raise RuntimeOracleError("ORACLE_CONTAINS_ACTUAL_COLLECTION_REQUIRED")
    if operator == "MATCHES":
        if not isinstance(actual, str) or not isinstance(expected, str):
            raise RuntimeOracleError("ORACLE_MATCHES_STRING_REQUIRED")
        return re.search(expected, actual) is not None, "MATCHES"
    raise RuntimeOracleError("ORACLE_OPERATOR_UNSUPPORTED:%s" % operator)


class RuntimeOracleEvaluator:
    def validate(self, oracle: Mapping[str, Any]) -> Tuple[Dict[str, Any], ...]:
        if not isinstance(oracle, Mapping):
            raise RuntimeOracleError("ORACLE_OBJECT_REQUIRED")
        checks = oracle.get("runtime_checks")
        if not isinstance(checks, list) or not checks:
            raise RuntimeOracleError("ORACLE_RUNTIME_CHECKS_REQUIRED")
        normalized = []
        seen = set()
        for raw in checks:
            if not isinstance(raw, dict):
                raise RuntimeOracleError("ORACLE_RUNTIME_CHECK_OBJECT_REQUIRED")
            check_id = raw.get("id")
            operator = str(raw.get("operator") or "").upper()
            actual_path = raw.get("actual_path")
            if not isinstance(check_id, str) or not check_id.strip() or check_id in seen:
                raise RuntimeOracleError("ORACLE_CHECK_ID_INVALID")
            if operator not in _ALLOWED_OPERATORS:
                raise RuntimeOracleError("ORACLE_OPERATOR_INVALID:%s" % operator)
            if not isinstance(actual_path, str) or not actual_path.strip():
                raise RuntimeOracleError("ORACLE_ACTUAL_PATH_REQUIRED")
            if operator not in {"EXISTS", "NOT_EXISTS"} and "expected" not in raw:
                raise RuntimeOracleError("ORACLE_EXPECTED_REQUIRED:%s" % check_id)
            seen.add(check_id)
            row = dict(raw)
            row["id"] = check_id.strip()
            row["operator"] = operator
            row["actual_path"] = actual_path.strip()
            normalized.append(row)
        return tuple(normalized)

    def evaluate(self, oracle: Mapping[str, Any], actual_result: Mapping[str, Any]) -> RuntimeOracleResult:
        if not isinstance(actual_result, Mapping):
            raise RuntimeOracleError("ACTUAL_RESULT_OBJECT_REQUIRED")
        checks = self.validate(oracle)
        results = []
        for check in checks:
            actual = _resolve_path(actual_result, check["actual_path"])
            expected = check.get("expected")
            passed, reason = _compare(check["operator"], actual, expected)
            results.append(
                RuntimeOracleCheckResult(
                    check_id=check["id"],
                    operator=check["operator"],
                    actual_path=check["actual_path"],
                    passed=passed,
                    actual_value=None if actual is _MISSING else actual,
                    expected_value=expected,
                    reason=reason if passed else "ORACLE_%s_FAILED:%s" % (check["operator"], reason),
                )
            )
        identity = {
            "oracle": list(checks),
            "actual_result": dict(actual_result),
            "results": [
                {"id": item.check_id, "passed": item.passed, "actual": item.actual_value, "expected": item.expected_value}
                for item in results
            ],
        }
        return RuntimeOracleResult(
            assertion_ref="assertion://rc7/" + sha256(_canonical(identity).encode("utf-8")).hexdigest()[:32],
            passed=all(item.passed for item in results),
            check_results=tuple(results),
        )
