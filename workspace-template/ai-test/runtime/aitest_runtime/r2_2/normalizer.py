"""R2.2 canonical request and Goal.definition normalization."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from aitest_runtime.durable_core import canonical_sha256
from aitest_runtime.r2_1.contracts import CONTRACT_VERSION as R2_1_CONTRACT_VERSION

from .contracts import (
    GOAL_DEFINITION_CONTRACT_VERSION,
    GoalDefinition,
    MissionIntakeError,
    MissionIntakeRequest,
    OP_CREATE,
    normalize_scope,
    validate_request_secrets,
)


def _error(message: str, code: str = "MISSION_INTAKE_SCHEMA_INVALID") -> MissionIntakeError:
    return MissionIntakeError(code, message)


def _scope_to_r2_1(scope: Mapping[str, Any]) -> dict[str, Any]:
    """Map an explicit R2.2 set to the nearest R2.1 resolution scope."""
    project_id = scope.get("project_id", "")
    environment_id = scope.get("environment_id") or scope.get("environment_ref")
    if environment_id is None and isinstance(scope.get("environment"), Mapping):
        environment = scope["environment"]
        environment_id = environment.get("environment_id") or environment.get("id") or environment.get("ref")
    if environment_id is None and isinstance(scope.get("environment"), str):
        environment_id = scope["environment"]
    repositories = list(scope.get("repository_ids") or [])
    if not repositories:
        repositories = list(scope.get("repositories") or [])
    if isinstance(scope.get("repository"), Mapping):
        repositories.append(scope["repository"])
    if not repositories and isinstance(scope.get("repository_identity"), Mapping):
        repositories.append(scope["repository_identity"])
    repositories = [
        item.get("repository_id", item.get("id")) if isinstance(item, Mapping) else item
        for item in repositories
    ]
    if environment_id is not None:
        return {"type": "ENVIRONMENT", "project_id": project_id, "environment_id": environment_id}
    if len(repositories) == 1:
        return {"type": "REPOSITORY", "project_id": project_id, "repository_id": repositories[0]}
    return {"type": "PROJECT", "project_id": project_id}


def _resolution_request(request: MissionIntakeRequest) -> dict[str, Any]:
    raw = dict(request.resolution_request)
    if "resolution" in raw and isinstance(raw["resolution"], Mapping):
        # A caller may pass a pre-resolved R2.1 record. It is consumed by the
        # orchestrator as a reference and is not rewritten here.
        return raw
    result = dict(raw)
    result.setdefault("resolution_id", f"r2.2:{request.intake_id}:resolution")
    result.setdefault("scope", _scope_to_r2_1(request.scope))
    result.setdefault("facts", raw.get("runtime_facts", []))
    result.setdefault("capabilities", raw.get("capability_declarations", []))
    result.setdefault("source_precedence", request.source["source_precedence"])
    return result


def normalize_request(value: Mapping[str, Any] | MissionIntakeRequest) -> MissionIntakeRequest:
    """Validate, normalize, and assign the stable V1 normalized digest."""
    raw = value.to_mapping(include_digest=False) if isinstance(value, MissionIntakeRequest) else value
    if not isinstance(raw, Mapping):
        raise _error("MissionIntakeRequest must be an object")
    validate_request_secrets(raw)
    request = MissionIntakeRequest.from_mapping(raw)
    canonical = request.to_mapping(include_digest=False)
    canonical["resolution_request"] = _resolution_request(request)
    digest = canonical_sha256(canonical)
    return request.with_normalized_digest(digest)


def build_resolution_request(request: MissionIntakeRequest) -> dict[str, Any]:
    return _resolution_request(request)


def _resolution_record(resolution: Mapping[str, Any], source_precedence: Any = None) -> dict[str, Any]:
    status = str(resolution.get("status") or "INVALID").upper()
    reason = str(resolution.get("reason_code") or f"R2_1_RESOLUTION_{status}")
    request_digest = resolution.get("request_digest")
    fact_set_digest = resolution.get("fact_set_digest")
    source_refs = resolution.get("source_refs") or []
    if not isinstance(source_refs, (list, tuple)):
        source_refs = [source_refs]
    source_refs = [str(item) for item in source_refs if item is not None]
    precedence = resolution.get("source_precedence")
    if precedence is None:
        precedence = source_precedence
    refs = {
        "resolution_id": resolution.get("resolution_id"),
        "snapshot_id": resolution.get("snapshot_id"),
        "request_digest": request_digest,
        "fact_set_digest": fact_set_digest,
        "status": status,
        "source_refs": source_refs,
        "valid_until": resolution.get("valid_until"),
    }
    provenance = dict(resolution.get("provenance") or {}) if isinstance(resolution.get("provenance"), Mapping) else {}
    provenance.update({
        "source": "R2.1_RUNTIME_FACTS_CAPABILITY_RESOLUTION",
        "contract_version": R2_1_CONTRACT_VERSION,
        "resolution_id": resolution.get("resolution_id"),
        "snapshot_id": resolution.get("snapshot_id"),
        "request_digest": request_digest,
        "fact_set_digest": fact_set_digest,
        "status": status,
        "source_refs": source_refs,
        "source_precedence": precedence,
        "valid_until": resolution.get("valid_until"),
    })
    return {
        "status": status,
        "reason": reason,
        "resolution_refs": refs,
        "provenance": provenance,
    }


def build_goal_definition(
    request: MissionIntakeRequest,
    resolution: Mapping[str, Any],
    *,
    source_precedence: Any = None,
) -> dict[str, Any]:
    """Build a V1 definition, retaining R2.1 identity and provenance verbatim."""
    if not isinstance(resolution, Mapping):
        raise _error("R2.1 resolution must be an object")
    normalized_scope = normalize_scope(request.scope)
    if source_precedence is None:
        source_precedence = request.resolution_request.get("source_precedence", request.source["source_precedence"])
    record = _resolution_record(resolution, source_precedence)
    definition = GoalDefinition(
        goal=dict(request.goal),
        scope=normalized_scope,
        scope_status=record["status"],
        scope_reason=record["reason"],
        provenance=record["provenance"],
        resolution_refs=record["resolution_refs"],
        execution_scope=normalized_scope,
        scope_digest=canonical_sha256(normalized_scope),
        intake={
            "intake_id": request.intake_id,
            "operation": request.operation,
            "source_manifest": dict(request.source),
        },
        intake_id=request.intake_id,
        normalized_digest=request.normalized_digest,
    )
    return definition.to_dict()


def normalize_and_build(
    value: Mapping[str, Any] | MissionIntakeRequest,
    resolution: Mapping[str, Any],
    *,
    source_precedence: Any = None,
) -> tuple[MissionIntakeRequest, dict[str, Any]]:
    request = normalize_request(value)
    return request, build_goal_definition(request, resolution, source_precedence=source_precedence)


__all__ = [
    "normalize_request",
    "build_resolution_request",
    "build_goal_definition",
    "normalize_and_build",
]
