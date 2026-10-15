"""Deterministic RC7 execution Oracle runtime.

Test Design may describe business meaning, but formal Execution needs a machine
check that does not ask a model to reinterpret expected results after seeing the
actual result. Every executable Oracle check therefore binds an ``actual_path``
to a fixed operator and expected value. The runtime evaluates all checks and
emits a content-addressed assertion reference/evidence reference.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Tuple


class DeterministicOracleError(RuntimeError):
    pass


OPERATORS = {
    "EQ", "NE", "GT", "GTE", "LT", "LTE", "IN", "NOT_IN",
    "CONTAINS", "EXISTS", "NOT_EXISTS",
}

_MISSING = object()


def _fingerprint(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _resolve_path(value: Any, path: str) -> Any:
    if not isinstance(path, str) or not path.strip():
        raise DeterministicOracleError("ORACLE_ACTUAL_PATH_REQUIRED")
    current = value
    for token in path.strip().split("."):
        if not token:
            raise DeterministicOracleError("ORACLE_ACTUAL_PATH_INVALID")
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


def _compare(operator: str, actual: Any, expected: Any) -> bool:
    if operator == "EXISTS":
        return actual is not _MISSING
    if operator == "NOT_EXISTS":
        return actual is _MISSING
    if actual is _MISSING:
        return False
    if operator == "EQ":
        return actual == expected
    if operator == "NE":
        return actual != expected
    if operator == "GT":
        return actual > expected
    if operator == "GTE":
        return actual >= expected
    if operator == "LT":
        return actual < expected
    if operator == "LTE":
        return actual <= expected
    if operator == "IN":
        return isinstance(expected, (list, tuple, set)) and actual in expected
    if operator == "NOT_IN":
        return isinstance(expected, (list, tuple, set)) and actual not in expected
    if operator == "CONTAINS":
        try:
            return expected in actual
        except TypeError:
            return False
    raise DeterministicOracleError("ORACLE_OPERATOR_UNSUPPORTED:%s" % operator)


@dataclass(frozen=True)
class OracleCheckResult:
    check_id: str
    check_type: str
    actual_path: str
    operator: str
    expected: Any
    actual: Any
    passed: bool


class DeterministicOracleRuntime:
    """Callable compatible with ``ExecutionRuntime.oracle_evaluator``."""

    @staticmethod
    def validate_contract(oracle_snapshot: object) -> Tuple[Dict[str, Any], ...]:
        if not isinstance(oracle_snapshot, dict):
            raise DeterministicOracleError("ORACLE_SNAPSHOT_OBJECT_REQUIRED")
        checks = oracle_snapshot.get("checks")
        if not isinstance(checks, list) or not checks:
            raise DeterministicOracleError("ORACLE_CHECKS_REQUIRED")
        normalized = []
        seen = set()
        for index, raw in enumerate(checks):
            if not isinstance(raw, dict):
                raise DeterministicOracleError("ORACLE_CHECK_OBJECT_REQUIRED")
            check_id = raw.get("id") or "oracle-check-%d" % (index + 1)
            check_type = raw.get("type")
            actual_path = raw.get("actual_path")
            operator = str(raw.get("operator") or "").upper()
            if not isinstance(check_id, str) or not check_id.strip() or check_id in seen:
                raise DeterministicOracleError("ORACLE_CHECK_ID_INVALID")
            if not isinstance(check_type, str) or not check_type.strip():
                raise DeterministicOracleError("ORACLE_CHECK_TYPE_REQUIRED")
            if not isinstance(actual_path, str) or not actual_path.strip():
                raise DeterministicOracleError("ORACLE_ACTUAL_PATH_REQUIRED")
            if operator not in OPERATORS:
                raise DeterministicOracleError("ORACLE_OPERATOR_UNSUPPORTED:%s" % operator)
            if operator not in {"EXISTS", "NOT_EXISTS"} and "expected" not in raw:
                raise DeterministicOracleError("ORACLE_EXPECTED_REQUIRED")
            seen.add(check_id)
            row = deepcopy(raw)
            row["id"] = check_id
            row["type"] = check_type.strip().upper()
            row["actual_path"] = actual_path.strip()
            row["operator"] = operator
            normalized.append(row)
        return tuple(normalized)

    def evaluate(
        self,
        oracle_snapshot: Dict[str, Any],
        actual_result: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not isinstance(actual_result, dict) or not actual_result:
            raise DeterministicOracleError("ORACLE_ACTUAL_RESULT_REQUIRED")
        if not isinstance(context, dict):
            raise DeterministicOracleError("ORACLE_CONTEXT_REQUIRED")
        checks = self.validate_contract(oracle_snapshot)
        results = []
        for check in checks:
            actual = _resolve_path(actual_result, check["actual_path"])
            expected = check.get("expected")
            try:
                passed = _compare(check["operator"], actual, expected)
            except (TypeError, ValueError) as exc:
                raise DeterministicOracleError(
                    "ORACLE_COMPARISON_TYPE_ERROR:%s" % check["id"]
                ) from exc
            results.append(
                OracleCheckResult(
                    check_id=check["id"],
                    check_type=check["type"],
                    actual_path=check["actual_path"],
                    operator=check["operator"],
                    expected=deepcopy(expected),
                    actual=None if actual is _MISSING else deepcopy(actual),
                    passed=passed,
                )
            )
        details = {
            "checks": [
                {
                    "id": item.check_id,
                    "type": item.check_type,
                    "actual_path": item.actual_path,
                    "operator": item.operator,
                    "expected": item.expected,
                    "actual": item.actual,
                    "passed": item.passed,
                }
                for item in results
            ],
            "context": deepcopy(context),
        }
        identity = {
            "oracle": checks,
            "actual_result": actual_result,
            "context": context,
            "results": details["checks"],
        }
        digest = _fingerprint(identity)
        return {
            "passed": all(item.passed for item in results),
            "assertion_ref": "oracle-assertion://" + digest,
            # ExecutionRuntime's stable oracle boundary is a JSON/list contract.
            "evidence_refs": ["oracle-runtime://" + digest],
            "details": details,
        }

    def __call__(
        self,
        oracle_snapshot: Dict[str, Any],
        actual_result: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        return self.evaluate(oracle_snapshot, actual_result, context)
