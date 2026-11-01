from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

ARTIFACT_TYPE_N6_EXECUTABLE_CONTRACT = "rc72.n6.executable_contract"
EVENT_N6_EXECUTABLE_CONTRACT_COMPILED = "rc72.n6.executable_contract_compiled"
N6_SCHEMA_VERSION = "rc7.2-n6-executable-contract-v1"

_TARGET_N1 = "N1"
_TARGET_N4 = "N4"
_TARGET_N5 = "N5"

_UNRESOLVED_TOKENS = {
    "",
    "TBD",
    "TODO",
    "UNKNOWN",
    "UNRESOLVED",
    "GUESS",
    "GUESSED",
    "N/A",
}
_UNRESOLVED_PHRASES = (
    "find later",
    "find data later",
    "during execution",
    "guess during execution",
    "临时猜",
    "执行时再找",
    "执行时再猜",
)


@dataclass(frozen=True)
class ReadinessViolation:
    code: str
    target_node: str
    field: str
    reason: str

    def to_payload(self) -> Dict[str, str]:
        return {
            "code": self.code,
            "target_node": self.target_node,
            "field": self.field,
            "reason": self.reason,
        }


class ExecutableReadinessError(ValueError):
    def __init__(self, violations: Sequence[ReadinessViolation]):
        self.violations = tuple(violations)
        message = "; ".join(
            "{}:{}:{}".format(item.code, item.field, item.reason)
            for item in self.violations
        )
        super().__init__(message or "N6 executable readiness failed closed")


@dataclass(frozen=True)
class ExecutableContract:
    release_batch_id: str
    mission_id: str
    requirement_id: str
    sst_id: str
    obligation_id: str
    case_id: str
    case_ref: str
    environment: Mapping[str, Any]
    endpoint: Mapping[str, Any]
    tool_route: Mapping[str, Any]
    request: Mapping[str, Any]
    input: Mapping[str, Any]
    data_refs: Tuple[Mapping[str, Any], ...]
    preconditions: Tuple[Any, ...]
    steps: Tuple[Any, ...]
    assertions: Tuple[Mapping[str, Any], ...]
    oracles: Tuple[Any, ...]
    evidence_required: Tuple[Any, ...]
    cleanup: Mapping[str, Any]
    capabilities: Tuple[Mapping[str, Any], ...]
    resources: Tuple[Mapping[str, Any], ...]
    authoritative_sources: Tuple[str, ...]
    compiled_at: str
    contract_sha256: str

    def to_payload(self) -> Dict[str, Any]:
        return {
            "artifact_type": ARTIFACT_TYPE_N6_EXECUTABLE_CONTRACT,
            "schema_version": N6_SCHEMA_VERSION,
            "release_batch_id": self.release_batch_id,
            "mission_id": self.mission_id,
            "requirement_id": self.requirement_id,
            "sst_id": self.sst_id,
            "obligation_id": self.obligation_id,
            "case_id": self.case_id,
            "case_ref": self.case_ref,
            "environment": dict(self.environment),
            "endpoint": dict(self.endpoint),
            "tool_route": dict(self.tool_route),
            "request": dict(self.request),
            "input": dict(self.input),
            "data_refs": [dict(item) for item in self.data_refs],
            "preconditions": list(self.preconditions),
            "steps": list(self.steps),
            "assertions": [dict(item) for item in self.assertions],
            "oracles": list(self.oracles),
            "evidence_required": list(self.evidence_required),
            "cleanup": dict(self.cleanup),
            "capabilities": [dict(item) for item in self.capabilities],
            "resources": [dict(item) for item in self.resources],
            "authoritative_sources": list(self.authoritative_sources),
            "compiled_at": self.compiled_at,
            "contract_sha256": self.contract_sha256,
        }


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _is_unresolved(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        text = value.strip()
        if text.upper() in _UNRESOLVED_TOKENS:
            return True
        lowered = text.lower()
        return any(phrase in lowered for phrase in _UNRESOLVED_PHRASES)
    return False


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    body = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _iso(value: Optional[str]) -> datetime:
    text = _clean_text(value)
    if not text:
        raise ValueError("timestamp is empty")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _now_iso(now: Optional[datetime]) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or value is None:
        return ()
    return value if isinstance(value, Sequence) else ()


def _source_ref(value: Mapping[str, Any]) -> str:
    return _clean_text(value.get("source_ref") or value.get("source"))


def _validate_verified_binding(
    name: str,
    value: Any,
    violations: List[ReadinessViolation],
    *,
    target_node: str = _TARGET_N1,
    value_keys: Sequence[str] = (),
) -> Mapping[str, Any]:
    item = _mapping(value)
    if not item:
        violations.append(
            ReadinessViolation(
                "N6_BINDING_MISSING", target_node, name, "{} is missing".format(name)
            )
        )
        return {}
    if item.get("verified") is not True:
        violations.append(
            ReadinessViolation(
                "N6_BINDING_UNVERIFIED",
                target_node,
                name,
                "{} must be explicitly verified".format(name),
            )
        )
    source_ref = _source_ref(item)
    if _is_unresolved(source_ref):
        violations.append(
            ReadinessViolation(
                "N6_BINDING_SOURCE_MISSING",
                target_node,
                name,
                "{} must carry an authoritative source_ref".format(name),
            )
        )
    for key in value_keys:
        if key in item and not _is_unresolved(item.get(key)):
            break
    else:
        violations.append(
            ReadinessViolation(
                "N6_BINDING_VALUE_UNRESOLVED",
                target_node,
                name,
                "{} has no resolved value".format(name),
            )
        )
    return item


def _validate_ready_items(
    name: str,
    values: Any,
    violations: List[ReadinessViolation],
) -> Tuple[Mapping[str, Any], ...]:
    items = _sequence(values)
    if not items:
        violations.append(
            ReadinessViolation(
                "N6_RUNTIME_RESOURCE_MISSING",
                _TARGET_N1,
                name,
                "{} must contain at least one resolved item".format(name),
            )
        )
        return ()
    normalized: List[Mapping[str, Any]] = []
    for index, raw in enumerate(items):
        item = _mapping(raw)
        field = "{}[{}]".format(name, index)
        item_name = _clean_text(item.get("name"))
        status = _clean_text(item.get("status")).upper()
        source_ref = _source_ref(item)
        if _is_unresolved(item_name):
            violations.append(
                ReadinessViolation(
                    "N6_RUNTIME_RESOURCE_NAME_UNRESOLVED",
                    _TARGET_N1,
                    field,
                    "runtime item name is unresolved",
                )
            )
        if status != "READY":
            violations.append(
                ReadinessViolation(
                    "N6_RUNTIME_RESOURCE_NOT_READY",
                    _TARGET_N1,
                    field,
                    "runtime item status must be READY",
                )
            )
        if _is_unresolved(source_ref):
            violations.append(
                ReadinessViolation(
                    "N6_RUNTIME_RESOURCE_SOURCE_MISSING",
                    _TARGET_N1,
                    field,
                    "runtime item must carry source_ref",
                )
            )
        normalized.append(dict(item))
    return tuple(normalized)


class N6ExecutableReadinessCompiler:
    """Compile an immutable N7 execution contract from already-proven N1/N4/N5 truth.

    N6 is intentionally not an executor. It may only bind authoritative facts that
    already exist. It never allocates a DataLease and never guesses a route, schema,
    capability, resource, oracle, or evidence requirement.
    """

    def compile(
        self,
        case_payload: Mapping[str, Any],
        data_ref_payloads: Sequence[Mapping[str, Any]],
        runtime_binding: Mapping[str, Any],
        *,
        now: Optional[datetime] = None,
    ) -> ExecutableContract:
        violations: List[ReadinessViolation] = []
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        current = current.astimezone(timezone.utc)

        case = _mapping(case_payload)
        lineage_fields = (
            "release_batch_id",
            "mission_id",
            "requirement_id",
            "sst_id",
            "obligation_id",
            "case_id",
        )
        lineage: Dict[str, str] = {}
        for field in lineage_fields:
            value = _clean_text(case.get(field))
            lineage[field] = value
            if _is_unresolved(value):
                violations.append(
                    ReadinessViolation(
                        "N6_CASE_LINEAGE_UNRESOLVED",
                        _TARGET_N4,
                        field,
                        "{} is required from the N4 case".format(field),
                    )
                )

        state = _clean_text(case.get("status") or case.get("state")).upper()
        if case.get("stale") is True or state == "STALE":
            violations.append(
                ReadinessViolation(
                    "N6_N4_CASE_STALE",
                    _TARGET_N4,
                    "case",
                    "N4 case is stale",
                )
            )

        preconditions = tuple(_sequence(case.get("preconditions")))
        steps = tuple(_sequence(case.get("steps")))
        oracles = tuple(_sequence(case.get("oracles")))
        evidence_required = tuple(
            _sequence(case.get("evidence_requirements") or case.get("evidence_required"))
        )
        inputs = _mapping(case.get("inputs") or case.get("input"))
        expected = case.get("expected")
        case_ref = _clean_text(
            case.get("case_ref")
            or case.get("artifact_ref")
            or case.get("case_id")
        )

        for field, value in (
            ("case_ref", case_ref),
            ("preconditions", preconditions),
            ("steps", steps),
            ("inputs", inputs),
            ("expected", expected),
            ("oracles", oracles),
            ("evidence_required", evidence_required),
        ):
            if not value or _is_unresolved(value):
                violations.append(
                    ReadinessViolation(
                        "N6_CASE_EXECUTION_FIELD_UNRESOLVED",
                        _TARGET_N4,
                        field,
                        "{} must be resolved by N4 before N6".format(field),
                    )
                )

        if any(_is_unresolved(item) for item in preconditions):
            violations.append(
                ReadinessViolation(
                    "N6_CASE_PRECONDITION_UNRESOLVED",
                    _TARGET_N4,
                    "preconditions",
                    "preconditions contain unresolved placeholders",
                )
            )
        if any(_is_unresolved(item) for item in steps):
            violations.append(
                ReadinessViolation(
                    "N6_CASE_STEP_UNRESOLVED",
                    _TARGET_N4,
                    "steps",
                    "steps contain unresolved placeholders",
                )
            )
        if any(_is_unresolved(item) for item in oracles):
            violations.append(
                ReadinessViolation(
                    "N6_CASE_ORACLE_UNRESOLVED",
                    _TARGET_N4,
                    "oracles",
                    "oracles contain unresolved placeholders",
                )
            )
        if any(_is_unresolved(item) for item in evidence_required):
            violations.append(
                ReadinessViolation(
                    "N6_CASE_EVIDENCE_UNRESOLVED",
                    _TARGET_N4,
                    "evidence_required",
                    "evidence requirements contain unresolved placeholders",
                )
            )

        refs: List[Mapping[str, Any]] = []
        if not data_ref_payloads:
            violations.append(
                ReadinessViolation(
                    "N6_DATA_REF_MISSING",
                    _TARGET_N5,
                    "data_refs",
                    "at least one verified N5 DataRef is required",
                )
            )
        for index, raw in enumerate(data_ref_payloads or ()):
            ref = _mapping(raw)
            field = "data_refs[{}]".format(index)
            if ref.get("resolved_ref_status") != "VERIFIED":
                violations.append(
                    ReadinessViolation(
                        "N6_DATA_REF_UNVERIFIED",
                        _TARGET_N5,
                        field,
                        "N5 DataRef must have resolved_ref_status=VERIFIED",
                    )
                )
            for key in ("release_batch_id", "mission_id", "requirement_id", "case_id"):
                if _clean_text(ref.get(key)) != lineage.get(key, ""):
                    violations.append(
                        ReadinessViolation(
                            "N6_DATA_REF_LINEAGE_MISMATCH",
                            _TARGET_N5,
                            "{}.{}".format(field, key),
                            "DataRef lineage does not match the N4 case",
                        )
                    )
            data_ref = _clean_text(ref.get("data_ref"))
            if _is_unresolved(data_ref):
                violations.append(
                    ReadinessViolation(
                        "N6_DATA_REF_UNRESOLVED",
                        _TARGET_N5,
                        "{}.data_ref".format(field),
                        "verified DataRef must contain a concrete data_ref",
                    )
                )
            expires_at = _clean_text(ref.get("expires_at"))
            try:
                if _iso(expires_at) <= current:
                    violations.append(
                        ReadinessViolation(
                            "N6_DATA_REF_EXPIRED",
                            _TARGET_N5,
                            "{}.expires_at".format(field),
                            "DataRef expired before executable contract compilation",
                        )
                    )
            except (TypeError, ValueError):
                violations.append(
                    ReadinessViolation(
                        "N6_DATA_REF_EXPIRY_INVALID",
                        _TARGET_N5,
                        "{}.expires_at".format(field),
                        "DataRef expiry is missing or invalid",
                    )
                )
            refs.append(dict(ref))

        binding = _mapping(runtime_binding)
        if binding.get("verified") is not True:
            violations.append(
                ReadinessViolation(
                    "N6_RUNTIME_BINDING_UNVERIFIED",
                    _TARGET_N1,
                    "runtime_binding",
                    "N1/runtime binding must be explicitly verified",
                )
            )

        environment = _mapping(binding.get("environment"))
        env_name = _clean_text(environment.get("name"))
        env_status = _clean_text(environment.get("status")).upper()
        env_source = _source_ref(environment)
        if _is_unresolved(env_name) or env_status != "READY" or _is_unresolved(env_source):
            violations.append(
                ReadinessViolation(
                    "N6_ENVIRONMENT_UNRESOLVED",
                    _TARGET_N1,
                    "environment",
                    "environment requires name, READY status and source_ref",
                )
            )

        endpoint = _validate_verified_binding(
            "endpoint",
            binding.get("endpoint"),
            violations,
            value_keys=("url", "endpoint", "path"),
        )
        tool_route = _validate_verified_binding(
            "tool_route",
            binding.get("tool_route"),
            violations,
            value_keys=("tool", "name", "route"),
        )
        request = _mapping(binding.get("request"))
        request_schema = _clean_text(
            request.get("schema_ref")
            or request.get("schema")
            or request.get("contract_ref")
        )
        request_source = _source_ref(request)
        if not request or _is_unresolved(request_schema) or _is_unresolved(request_source):
            violations.append(
                ReadinessViolation(
                    "N6_REQUEST_SCHEMA_UNRESOLVED",
                    _TARGET_N4,
                    "request",
                    "request requires an explicit schema/contract ref and source_ref",
                )
            )
        if any(
            _is_unresolved(request.get(key))
            for key in ("method",)
            if key in request
        ):
            violations.append(
                ReadinessViolation(
                    "N6_REQUEST_UNRESOLVED",
                    _TARGET_N4,
                    "request",
                    "request contains unresolved execution fields",
                )
            )

        cleanup = _mapping(binding.get("cleanup"))
        cleanup_action = _clean_text(cleanup.get("action"))
        cleanup_source = _source_ref(cleanup)
        if _is_unresolved(cleanup_action) or _is_unresolved(cleanup_source):
            violations.append(
                ReadinessViolation(
                    "N6_CLEANUP_UNRESOLVED",
                    _TARGET_N4,
                    "cleanup",
                    "cleanup requires an explicit action and source_ref",
                )
            )

        capabilities = _validate_ready_items(
            "capabilities", binding.get("capabilities"), violations
        )
        resources = _validate_ready_items(
            "resources", binding.get("resources"), violations
        )

        binding_sources = tuple(
            _clean_text(item)
            for item in _sequence(binding.get("authoritative_sources"))
            if not _is_unresolved(item)
        )
        case_sources = tuple(
            _clean_text(item)
            for item in _sequence(case.get("authoritative_sources"))
            if not _is_unresolved(item)
        )
        data_sources: List[str] = []
        for ref in refs:
            for item in _sequence(ref.get("authoritative_sources")):
                if not _is_unresolved(item):
                    data_sources.append(_clean_text(item))
        collected_sources = tuple(
            sorted(
                set(
                    case_sources
                    + binding_sources
                    + tuple(data_sources)
                    + tuple(
                        item
                        for item in (
                            env_source,
                            _source_ref(endpoint),
                            _source_ref(tool_route),
                            request_source,
                            cleanup_source,
                        )
                        if item
                    )
                )
            )
        )
        if not collected_sources:
            violations.append(
                ReadinessViolation(
                    "N6_AUTHORITATIVE_SOURCE_MISSING",
                    _TARGET_N1,
                    "authoritative_sources",
                    "N6 cannot compile without authoritative source lineage",
                )
            )

        if violations:
            raise ExecutableReadinessError(violations)

        explicit_assertions = tuple(_sequence(case.get("assertions")))
        if explicit_assertions:
            assertions = tuple(
                item if isinstance(item, Mapping) else {"kind": "ASSERTION", "value": item}
                for item in explicit_assertions
            )
        else:
            assertions = (
                {
                    "kind": "EXPECTED_RESULT",
                    "expected": expected,
                    "source": "N4.expected",
                },
            )

        semantic_payload: Dict[str, Any] = {
            "schema_version": N6_SCHEMA_VERSION,
            **lineage,
            "case_ref": case_ref,
            "environment": dict(environment),
            "endpoint": dict(endpoint),
            "tool_route": dict(tool_route),
            "request": dict(request),
            "input": dict(inputs),
            "data_refs": [dict(item) for item in refs],
            "preconditions": list(preconditions),
            "steps": list(steps),
            "assertions": [dict(item) for item in assertions],
            "oracles": list(oracles),
            "evidence_required": list(evidence_required),
            "cleanup": dict(cleanup),
            "capabilities": [dict(item) for item in capabilities],
            "resources": [dict(item) for item in resources],
            "authoritative_sources": list(collected_sources),
        }
        digest = _canonical_hash(semantic_payload)

        return ExecutableContract(
            release_batch_id=lineage["release_batch_id"],
            mission_id=lineage["mission_id"],
            requirement_id=lineage["requirement_id"],
            sst_id=lineage["sst_id"],
            obligation_id=lineage["obligation_id"],
            case_id=lineage["case_id"],
            case_ref=case_ref,
            environment=dict(environment),
            endpoint=dict(endpoint),
            tool_route=dict(tool_route),
            request=dict(request),
            input=dict(inputs),
            data_refs=tuple(dict(item) for item in refs),
            preconditions=preconditions,
            steps=steps,
            assertions=tuple(dict(item) for item in assertions),
            oracles=oracles,
            evidence_required=evidence_required,
            cleanup=dict(cleanup),
            capabilities=capabilities,
            resources=resources,
            authoritative_sources=collected_sources,
            compiled_at=_now_iso(current),
            contract_sha256=digest,
        )
