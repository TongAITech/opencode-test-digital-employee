"""RC6 Execution Closure Overlay: immutable executable test specification.

A frozen TestCase is design truth, not an executable program.  This module
compiles that frozen design truth into a deterministic ExecutableTestSpec that
binds the exact case version/fingerprint, immutable oracle fingerprint, target
requirements, preparation inputs, ordered actions, evidence requirements and
runner/automation mapping.  Later script generation/repair must preserve those
fingerprints; otherwise the runtime fails closed.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any, Dict, Mapping, Optional, Tuple


class ExecutableSpecError(RuntimeError):
    pass


def canonical_fingerprint(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _require_text(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExecutableSpecError(code)
    return value.strip()


def _tuple_of_dicts(value: Any, code: str, *, nonempty: bool = False) -> Tuple[Dict[str, Any], ...]:
    if not isinstance(value, list):
        raise ExecutableSpecError(code)
    if nonempty and not value:
        raise ExecutableSpecError(code)
    if not all(isinstance(item, dict) for item in value):
        raise ExecutableSpecError(code)
    return tuple(deepcopy(item) for item in value)


def _tuple_of_text(value: Any, code: str, *, nonempty: bool = False) -> Tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ExecutableSpecError(code)
    normalized = tuple(str(item).strip() for item in value if isinstance(item, str) and item.strip())
    if len(normalized) != len(value) or (nonempty and not normalized):
        raise ExecutableSpecError(code)
    return normalized


@dataclass(frozen=True)
class ExecutableTestSpec:
    spec_id: str
    tc_id: str
    case_version: int
    case_fingerprint: str
    oracle_fingerprint: str
    release_id: str
    requirement_id: str
    sst_id: Optional[str]
    layer: str
    target_requirements: Tuple[str, ...]
    preconditions: Tuple[Dict[str, Any], ...]
    test_data_refs: Tuple[str, ...]
    ordered_actions: Tuple[Dict[str, Any], ...]
    oracle_refs: Tuple[str, ...]
    evidence_requirements: Tuple[str, ...]
    cleanup_policy: Dict[str, Any]
    runner_type: str
    automation_mapping: Dict[str, Any]
    status: str = "EXECUTABLE_SPEC"

    def to_artifact(self) -> Dict[str, Any]:
        out = asdict(self)
        out["preconditions"] = [deepcopy(x) for x in self.preconditions]
        out["ordered_actions"] = [deepcopy(x) for x in self.ordered_actions]
        out["target_requirements"] = list(self.target_requirements)
        out["test_data_refs"] = list(self.test_data_refs)
        out["oracle_refs"] = list(self.oracle_refs)
        out["evidence_requirements"] = list(self.evidence_requirements)
        out["automation_mapping"] = deepcopy(self.automation_mapping)
        out["cleanup_policy"] = deepcopy(self.cleanup_policy)
        return out


class ExecutableSpecBuilder:
    """Compile a frozen TestCase into a deterministic executable contract."""

    VALID_RUNNERS = {"PYTEST", "JUNIT", "PLAYWRIGHT", "K6", "ZAP", "CAPABILITY"}

    @staticmethod
    def _oracle_source(case: Mapping[str, Any]) -> Dict[str, Any]:
        if case.get("oracle") in (None, "", [], {}):
            raise ExecutableSpecError("FROZEN_CASE_ORACLE_REQUIRED")
        expected = case.get("expected")
        if not isinstance(expected, str) or not expected.strip():
            raise ExecutableSpecError("FROZEN_CASE_EXPECTED_REQUIRED")
        return {"expected": expected, "oracle": deepcopy(case.get("oracle"))}

    @staticmethod
    def _case_identity(case: Mapping[str, Any]) -> Tuple[str, int, str, str, str, Optional[str]]:
        if str(case.get("status", "")).upper() != "FROZEN":
            raise ExecutableSpecError("CASE_MUST_BE_FROZEN")
        tc_id = _require_text(case.get("tc_id"), "TC_ID_REQUIRED")
        version = case.get("case_version")
        if not isinstance(version, int) or version < 1:
            raise ExecutableSpecError("CASE_VERSION_REQUIRED")
        release_id = _require_text(case.get("release_id"), "RELEASE_ID_REQUIRED")
        requirement_id = _require_text(case.get("requirement_id"), "REQUIREMENT_ID_REQUIRED")
        layer = _require_text(case.get("layer"), "LAYER_REQUIRED").upper()
        if layer not in {"L%d" % i for i in range(1, 8)}:
            raise ExecutableSpecError("SINGLE_VALID_LAYER_REQUIRED")
        sst_id = case.get("sst_id")
        if sst_id is not None:
            sst_id = _require_text(sst_id, "INVALID_SST_ID")
        return tc_id, version, release_id, requirement_id, layer, sst_id

    def build(
        self,
        *,
        case: Mapping[str, Any],
        target_requirements: Tuple[str, ...],
        test_data_refs: Tuple[str, ...],
        oracle_refs: Tuple[str, ...],
        cleanup_policy: Mapping[str, Any],
        runner_type: str,
        automation_mapping: Mapping[str, Any],
    ) -> ExecutableTestSpec:
        if not isinstance(case, Mapping):
            raise ExecutableSpecError("CASE_REQUIRED")
        tc_id, version, release_id, requirement_id, layer, sst_id = self._case_identity(case)
        runner = _require_text(runner_type, "RUNNER_TYPE_REQUIRED").upper()
        if runner not in self.VALID_RUNNERS:
            raise ExecutableSpecError("UNSUPPORTED_RUNNER_TYPE")
        if not isinstance(cleanup_policy, Mapping):
            raise ExecutableSpecError("CLEANUP_POLICY_REQUIRED")
        if not isinstance(automation_mapping, Mapping):
            raise ExecutableSpecError("AUTOMATION_MAPPING_REQUIRED")

        preconditions_raw = case.get("preconditions", [])
        if not isinstance(preconditions_raw, list):
            raise ExecutableSpecError("PRECONDITIONS_INVALID")
        normalized_preconditions = []
        for index, value in enumerate(preconditions_raw):
            if isinstance(value, dict):
                normalized_preconditions.append(deepcopy(value))
            elif isinstance(value, str) and value.strip():
                normalized_preconditions.append({"id": "precondition-%d" % index, "description": value.strip()})
            else:
                raise ExecutableSpecError("PRECONDITIONS_INVALID")

        actions_raw = case.get("steps")
        if not isinstance(actions_raw, list) or not actions_raw:
            raise ExecutableSpecError("ORDERED_ACTIONS_REQUIRED")
        normalized_actions = []
        for index, value in enumerate(actions_raw):
            if isinstance(value, dict):
                action = deepcopy(value)
            elif isinstance(value, str) and value.strip():
                action = {"description": value.strip()}
            else:
                raise ExecutableSpecError("ORDERED_ACTIONS_INVALID")
            action.setdefault("order", index + 1)
            normalized_actions.append(action)
        orders = [item.get("order") for item in normalized_actions]
        if orders != list(range(1, len(normalized_actions) + 1)):
            raise ExecutableSpecError("ORDERED_ACTION_SEQUENCE_INVALID")

        evidence_requirements = case.get("evidence_requirements")
        evidence_tuple = _tuple_of_text(evidence_requirements, "EVIDENCE_REQUIREMENTS_REQUIRED", nonempty=True)
        target_tuple = _tuple_of_text(target_requirements, "TARGET_REQUIREMENTS_REQUIRED", nonempty=True)
        data_tuple = _tuple_of_text(test_data_refs, "TEST_DATA_REFS_INVALID")
        oracle_tuple = _tuple_of_text(oracle_refs, "ORACLE_REFS_REQUIRED", nonempty=True)

        case_copy = deepcopy(dict(case))
        case_fp = canonical_fingerprint(case_copy)
        oracle_fp = canonical_fingerprint(self._oracle_source(case_copy))
        spec_identity = {
            "tc_id": tc_id,
            "case_version": version,
            "case_fingerprint": case_fp,
            "oracle_fingerprint": oracle_fp,
            "runner_type": runner,
            "target_requirements": target_tuple,
        }
        spec_id = "XSPEC-" + canonical_fingerprint(spec_identity)[:24]
        return ExecutableTestSpec(
            spec_id=spec_id,
            tc_id=tc_id,
            case_version=version,
            case_fingerprint=case_fp,
            oracle_fingerprint=oracle_fp,
            release_id=release_id,
            requirement_id=requirement_id,
            sst_id=sst_id,
            layer=layer,
            target_requirements=target_tuple,
            preconditions=tuple(normalized_preconditions),
            test_data_refs=data_tuple,
            ordered_actions=tuple(normalized_actions),
            oracle_refs=oracle_tuple,
            evidence_requirements=evidence_tuple,
            cleanup_policy=deepcopy(dict(cleanup_policy)),
            runner_type=runner,
            automation_mapping=deepcopy(dict(automation_mapping)),
        )

    @staticmethod
    def verify_case_binding(spec: ExecutableTestSpec, frozen_case: Mapping[str, Any]) -> None:
        if canonical_fingerprint(dict(frozen_case)) != spec.case_fingerprint:
            raise ExecutableSpecError("CASE_FINGERPRINT_DRIFT")
        oracle = ExecutableSpecBuilder._oracle_source(frozen_case)
        if canonical_fingerprint(oracle) != spec.oracle_fingerprint:
            raise ExecutableSpecError("ORACLE_FINGERPRINT_DRIFT")
        if frozen_case.get("tc_id") != spec.tc_id or frozen_case.get("case_version") != spec.case_version:
            raise ExecutableSpecError("CASE_IDENTITY_DRIFT")

    @staticmethod
    def verify_script_or_repair_binding(
        spec: ExecutableTestSpec,
        *,
        case_fingerprint: str,
        oracle_fingerprint: str,
    ) -> None:
        if case_fingerprint != spec.case_fingerprint:
            raise ExecutableSpecError("SCRIPT_CASE_BINDING_CHANGED")
        if oracle_fingerprint != spec.oracle_fingerprint:
            raise ExecutableSpecError("SCRIPT_OR_REPAIR_ORACLE_CHANGED")
