"""Isolated Mission Scope preservation helpers for structured values."""

from dsh_scope_codec.mission_binding import (
    BindingStructureError, ScopeIdentity, parse_scope, serialize_scope,
)

from .models import (
    ContractError, Mission, MissionStatus, MISSION_SCOPE_HOLD, _MISSION_DICT,
    _SCOPE_ABSENT, _mission_scope_state, require_unbound_mission,
)


def _require_exact_mission(mission):
    if type(mission) is not Mission:
        raise TypeError("UNSUPPORTED_RC7_ENTITY")


def _check_identity(mission, scope):
    if (type(mission.mission_id) is not str or type(mission.release_id) is not str or
            scope.mission_id != mission.mission_id or scope.release_id != mission.release_id or
            scope.mission_id != scope.mission_id.strip() or
            scope.release_id != scope.release_id.strip()):
        raise BindingStructureError("BINDING_IDENTITY_CONFLICT")


def serialize_mission_scope(mission):
    """Return an independent Scope fragment for an isolated Mission object."""
    _require_exact_mission(mission)
    scope = _mission_scope_state(mission)
    if scope is _SCOPE_ABSENT:
        return {}
    if (type(scope) is not ScopeIdentity or type(scope.classification) is not str or
            scope.classification != "BOUND_STRUCTURAL_ONLY"):
        raise ContractError(MISSION_SCOPE_HOLD)
    fragment = serialize_scope(scope)
    _check_identity(mission, scope)
    canonical = parse_scope(dict(fragment, mission_id=mission.mission_id, release_id=mission.release_id))
    if canonical != scope:
        raise BindingStructureError("BINDING_STRUCTURE_INVALID")
    return fragment


_SCALAR_FIELDS = {
    "mission_id": str,
    "release_id": str,
    "goal": str,
    "state": MissionStatus,
    "sufficiency_state": str,
    "revision": int,
    "created_at": int,
    "updated_at": int,
}
_REFERENCE_FIELDS = ("artifact_refs", "open_gap_ids", "active_task_ids", "residual_risk_ids")
_DECLARED_FIELDS = frozenset(_SCALAR_FIELDS) | frozenset(_REFERENCE_FIELDS) | {"latest_evaluation_id"}
_COPY_FIELDS = _DECLARED_FIELDS | {"_scope_state"}


def _copy_declared_fields(mission):
    source = _MISSION_DICT.__get__(mission, Mission).copy()
    if (any(type(name) is not str or name not in _COPY_FIELDS for name in source) or
            not _DECLARED_FIELDS.issubset(source)):
        raise ContractError(MISSION_SCOPE_HOLD)

    copied = {}
    for name, expected in _SCALAR_FIELDS.items():
        value = source[name]
        if type(value) is not expected:
            raise ContractError(MISSION_SCOPE_HOLD)
        copied[name] = value
    evaluation_id = source["latest_evaluation_id"]
    if evaluation_id is not None and type(evaluation_id) is not str:
        raise ContractError(MISSION_SCOPE_HOLD)
    copied["latest_evaluation_id"] = evaluation_id

    for name in _REFERENCE_FIELDS:
        refs = source[name]
        if type(refs) is not list:
            raise ContractError(MISSION_SCOPE_HOLD)
        detached = list.copy(refs)
        if any(type(ref) is not str for ref in detached):
            raise ContractError(MISSION_SCOPE_HOLD)
        copied[name] = detached

    if "_scope_state" in source:
        scope = source["_scope_state"]
        if scope is not _SCOPE_ABSENT and type(scope) is not ScopeIdentity:
            raise ContractError(MISSION_SCOPE_HOLD)
        copied["_scope_state"] = scope
    return copied


def clone_mission(mission):
    """Copy declared Mission data while preserving the immutable Scope value."""
    _require_exact_mission(mission)
    copied = _copy_declared_fields(mission)
    result = object.__new__(Mission)
    _MISSION_DICT.__get__(result, Mission).update(copied)
    serialize_mission_scope(result)
    return result


def isolate_mission_scope(mission, envelope):
    """Decode Scope from a DTO into a detached copy of an existing Mission."""
    result = clone_mission(mission)
    require_unbound_mission(result)
    scope = parse_scope(envelope)
    _check_identity(result, scope)
    if scope.classification == "BOUND_STRUCTURAL_ONLY":
        result._scope_state = scope
    return result
