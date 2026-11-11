"""Isolated Mission Scope preservation helpers for structured values."""

from dsh_scope_codec.mission_binding import (
    BindingStructureError, ScopeIdentity, parse_scope, serialize_scope,
)

from .models import (
    ContractError, Mission, MISSION_SCOPE_HOLD, _SCOPE_ABSENT,
    _copy_mission_fields, _mission_instance_dict, _mission_scope_state, _plain_string_dict,
    require_unbound_mission,
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


def clone_mission(mission):
    """Copy declared Mission data while preserving the immutable Scope value."""
    _require_exact_mission(mission)
    copied = _copy_mission_fields(mission)
    result = object.__new__(Mission)
    dict.update(_mission_instance_dict(result), copied)
    serialize_mission_scope(result)
    return result


def _parse_isolated_scope(envelope):
    # The shared codec accepts decoded JSON data. An in-process DTO can also
    # carry arbitrary Python keys, so prove key types before its lookups.
    if not _plain_string_dict(envelope):
        raise BindingStructureError("MISSION_ENVELOPE_INVALID")
    binding = dict.get(envelope, "scope_binding")
    if type(binding) is dict:
        if not _plain_string_dict(binding):
            raise BindingStructureError("BINDING_STRUCTURE_INVALID")
        for name in ("creation_key_scope", "mapping"):
            child = dict.get(binding, name)
            if type(child) is dict and not _plain_string_dict(child):
                raise BindingStructureError("BINDING_STRUCTURE_INVALID")
    return parse_scope(envelope)


def isolate_mission_scope(mission, envelope):
    """Decode Scope from a DTO into a detached copy of an existing Mission."""
    result = clone_mission(mission)
    require_unbound_mission(result)
    scope = _parse_isolated_scope(envelope)
    _check_identity(result, scope)
    if scope.classification == "BOUND_STRUCTURAL_ONLY":
        result._scope_state = scope
    return result
