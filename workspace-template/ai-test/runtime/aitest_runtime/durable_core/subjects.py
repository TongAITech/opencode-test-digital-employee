"""Root identity and compatibility checks over the existing R1 event stream.

These checks grant no caller/effect permission. Registered code owns root kinds;
model payloads cannot register an extension or change a stream's identity.
"""
from __future__ import annotations

from .contracts import ComposedRuntimeState, ExtensionRegistry, RuntimeError, SubjectRef
from .event_store import list_events


def validate_creation_event(event, registry: ExtensionRegistry, command_type: str | None = None):
    owner = registry.creation_owner(event_type=event.event_type)
    if owner is None:
        raise RuntimeError("ROOT_OWNER_UNSUPPORTED", f"unsupported root creation: {event.event_type}")
    manifest, root = owner
    subject = SubjectRef(root.subject_kind, event.mission_id)
    if event.seq != 1 or not event.mission_id.startswith(root.id_prefix) or event.mission_id == root.id_prefix:
        raise RuntimeError("ROOT_IDENTITY_INVALID", "root creation requires sequence one and its registered namespace")
    if event.entity_type != root.entity_type or event.entity_id != event.mission_id or event.session_id is not None:
        raise RuntimeError("ROOT_IDENTITY_INVALID", "root creation entity/session identity mismatch")
    if event.payload.get("subject") != subject.to_dict():
        raise RuntimeError("ROOT_IDENTITY_INVALID", "root payload subject differs from its owned stream")
    version = event.payload.get("root_version")
    if not isinstance(version, int) or isinstance(version, bool) or version != root.version:
        raise RuntimeError("ROOT_VERSION_UNSUPPORTED", f"unsupported version for {root.subject_kind}")
    if event.payload.get("creation_command") != root.creation_command or (command_type is not None and command_type != root.creation_command):
        raise RuntimeError("ROOT_CREATION_PAIR_INVALID", "creation command and event are not the registered pair")
    return manifest, root, subject


def root_owner_for_state(state: ComposedRuntimeState, registry: ExtensionRegistry):
    if state.subject is None or state.subject.subject_kind == "MISSION":
        return None
    if state.core_state.mission is not None or state.core_state.goals or state.core_state.sessions:
        raise RuntimeError("ROOT_IDENTITY_INVALID", "a non-Mission root cannot contain core Mission state")
    manifest, root = registry.root_owner(state.subject.subject_kind)
    if state.root_version != root.version:
        raise RuntimeError("ROOT_VERSION_UNSUPPORTED", "registered root version does not match durable identity")
    if not manifest.state_contribution.root_exists(state.extension_state(manifest.extension_id), state.subject):
        raise RuntimeError("ROOT_NOT_FOUND", "registered root owner has no matching durable root state")
    return manifest, root


def validate_root_command(command, state: ComposedRuntimeState, registry: ExtensionRegistry) -> bool:
    """True for an allowed non-Mission command; otherwise preserve Mission rules."""
    creation = registry.creation_owner(command_type=command.type)
    if creation is not None:
        manifest, root = creation
        if state.seq != 0 or state.core_state.mission is not None or state.subject is not None:
            raise RuntimeError("ROOT_ALREADY_EXISTS", "root creation cannot claim an occupied stream")
        if command.expected_seq != 0:
            raise RuntimeError("EXPECTED_SEQ_MISMATCH", "root creation expected_seq must be zero")
        if not command.mission_id.startswith(root.id_prefix) or command.mission_id == root.id_prefix:
            raise RuntimeError("ROOT_IDENTITY_INVALID", "root id is outside its registered namespace")
        expected = SubjectRef(root.subject_kind, command.mission_id).to_dict()
        if command.payload.get("subject") != expected or command.session_id is not None:
            raise RuntimeError("ROOT_IDENTITY_INVALID", "root command subject/session mismatch")
        return True
    owner = root_owner_for_state(state, registry)
    if owner is None:
        if command.type == "CREATE_MISSION" and registry.reserved_root_namespace(command.mission_id):
            raise RuntimeError("ROOT_IDENTITY_INVALID", "Mission cannot claim an extension root namespace")
        return False
    manifest, root = owner
    if registry.command_owner(command.type) != manifest or command.type not in root.command_types:
        raise RuntimeError("ROOT_COMMAND_FORBIDDEN", "command is not owned by this root kind")
    if command.payload.get("subject") != state.subject.to_dict() or command.session_id is not None:
        raise RuntimeError("ROOT_REFERENCE_MISMATCH", "root command references another subject or a core session")
    return True


def validate_root_event(event, state: ComposedRuntimeState, registry: ExtensionRegistry) -> None:
    manifest, root = root_owner_for_state(state, registry)
    if registry.event_owner(event.event_type) != manifest or event.event_type not in root.event_types:
        raise RuntimeError("ROOT_EVENT_FORBIDDEN", "event is not owned by this root kind")
    if event.event_type == root.creation_event:
        raise RuntimeError("ROOT_ALREADY_EXISTS", "root creation cannot be replayed twice")
    if event.payload.get("subject") != state.subject.to_dict() or event.entity_id != state.subject.subject_id or event.entity_type != root.entity_type or event.session_id is not None:
        raise RuntimeError("ROOT_REFERENCE_MISMATCH", "event subject/entity/session differs from its root")


def assert_runtime_compatible(conn, registry: ExtensionRegistry) -> None:
    """Fence new dispatch/rebuild if any non-Mission root owner/version is absent.

    Explicitly scoped historical Mission reads remain available. This guard does
    not claim unmodified old executables understand the new root contract.
    """
    missing = conn.execute("SELECT mission_id FROM events GROUP BY mission_id HAVING MIN(seq)!=1 LIMIT 1").fetchone()
    if missing is not None:
        raise RuntimeError("ROOT_IDENTITY_INVALID", "a stream has no sequence-one creation event")
    rows = conn.execute("SELECT mission_id FROM events WHERE seq=1 AND event_type!='mission.created' ORDER BY mission_id").fetchall()
    for row in rows:
        event = list_events(conn, row["mission_id"], through_seq=1)[0]
        command = conn.execute("SELECT command_type,mission_id,status FROM commands WHERE command_id=?", (event.command_id,)).fetchone()
        if command is None or command["status"] != "APPLIED" or command["mission_id"] != event.mission_id:
            raise RuntimeError("ROOT_CREATION_PAIR_INVALID", "root creation command record missing or inconsistent")
        _manifest, root, _subject = validate_creation_event(event, registry, command["command_type"])
        for observed in conn.execute("SELECT DISTINCT event_type,schema_version FROM events WHERE mission_id=?", (event.mission_id,)):
            if observed["event_type"] not in root.event_types or observed["schema_version"] != 1:
                raise RuntimeError("ROOT_EVENT_UNSUPPORTED", "registered runtime cannot replay every event of this root")
