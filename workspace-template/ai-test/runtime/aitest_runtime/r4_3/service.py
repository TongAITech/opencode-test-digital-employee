from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from aitest_runtime.durable_core import ActorRef, CommandResult, RuntimeService
from aitest_runtime.durable_core.contracts import RuntimeError as DurableRuntimeError

from .contracts import (
    COMMAND_TYPES,
    EXTENSION_ID,
    R4_3_OPEN_CONFIRMED_DEFECT_LIFECYCLE,
    R4_3_RECORD_FIX_DETECTION_ASSESSMENT,
    R4_3_RECORD_FIX_LINK,
    R4_3_REQUEST_FIX_DETECTION,
    ConfirmedDefectLifecycle,
    FixDetectionAssessment,
    FixDetectionRequest,
    FixLink,
    R43State,
    make_detection,
    make_fix_link,
    make_lifecycle,
)
from .errors import (
    CONFLICT,
    DUPLICATE,
    IDEMPOTENT_REPLAY,
    NOT_FOUND,
    R3_ASSESSMENT_DIGEST_CONFLICT,
    R43Error,
)
from .extension import r4_3_extension
from .handlers import DETECTION_FIELDS, FIX_LINK_FIELDS, LIFECYCLE_FIELDS, REQUEST_FIELDS
from .r3_6_adapter import validate_r3_6_reference


@dataclass(frozen=True)
class R43OperationResult:
    command_result: CommandResult
    entity: ConfirmedDefectLifecycle | FixLink | FixDetectionAssessment | FixDetectionRequest | None = None

    @property
    def ok(self) -> bool:
        return self.command_result.ok

    @property
    def outcome(self) -> str:
        return self.command_result.outcome

    @property
    def error_code(self) -> str | None:
        return self.command_result.error_code

    @property
    def first_seq(self) -> int | None:
        return self.command_result.first_seq

    @property
    def last_seq(self) -> int | None:
        return self.command_result.last_seq

    @property
    def duplicate_of(self) -> str | None:
        return self.command_result.duplicate_of

    @property
    def state_hash(self) -> str | None:
        return self.command_result.state_hash

    def to_dict(self) -> dict[str, Any]:
        result = self.command_result.to_dict()
        result["entity"] = self.entity.to_dict() if self.entity is not None else None
        return result


def compose_r4_3_runtime(
    db_path: str | Path,
    base_extensions: Iterable[Any] = (),
    *,
    clock: Any = None,
    failure_injector: Any = None,
) -> RuntimeService:
    """Explicitly compose R4.3 around the existing caller-selected extensions."""
    extensions = tuple(base_extensions)
    if any(getattr(item, "extension_id", None) == EXTENSION_ID for item in extensions):
        raise R43Error("R4_3_COMPOSITION_INVALID", "R4.3 extension is already present in the explicit composition")
    return RuntimeService(
        db_path,
        clock=clock,
        failure_injector=failure_injector,
        extensions=extensions + (r4_3_extension(),),
    )


class R43ApplicationService:
    """Caller-injected application boundary over the shared RuntimeService."""

    def __init__(self, runtime_service: RuntimeService, *, actor: ActorRef | None = None) -> None:
        if not isinstance(runtime_service, RuntimeService):
            raise TypeError("runtime_service must be the existing RuntimeService")
        runtime_service.extension_registry.manifest(EXTENSION_ID)
        self.runtime_service = runtime_service
        self.runtime = runtime_service
        self.actor = actor or ActorRef("SYSTEM", "r4.3")

    def state(self, mission_id: str) -> R43State:
        composed = self.runtime_service.get_composed_state(mission_id)
        value = composed.extension_state(EXTENSION_ID)
        if not isinstance(value, R43State):
            raise R43Error("R4_3_STATE_INVALID", "R4.3 extension state is invalid")
        return value

    get_state = state

    @staticmethod
    def _mapping(value: Any, fields: Mapping[str, Any]) -> dict[str, Any]:
        if isinstance(value, Mapping):
            raw = dict(value)
        elif hasattr(value, "to_dict") and callable(value.to_dict):
            raw = dict(value.to_dict())
        else:
            raw = {}
        raw.update(fields)
        raw.pop("created_seq", None)
        raw.pop("created_at", None)
        raw.pop("correlation_id", None)
        return raw

    def _error(self, command_id: str, mission_id: str, exc: Exception) -> R43OperationResult:
        if isinstance(exc, (R43Error, DurableRuntimeError)):
            error = exc
        else:
            error = R43Error("R4_3_COMMAND_INVALID", str(exc))
        return R43OperationResult(CommandResult("REJECTED", command_id, mission_id, error=error))

    def _duplicate(self, command_id: str, mission_id: str, entity: Any, existing_command_id: str | None = None) -> R43OperationResult:
        return R43OperationResult(
            CommandResult("DUPLICATE", command_id, mission_id, duplicate_of=existing_command_id, state_hash=None), entity
        )

    def _execute(
        self,
        *,
        payload: dict[str, Any],
        command_type: str,
        entity_id: str,
        mission_id: str,
        expected_seq: int | None,
        command_id: str | None,
        correlation_id: str | None,
        actor: ActorRef | None,
        existing: Any = None,
    ) -> R43OperationResult:
        if command_type not in COMMAND_TYPES:
            raise R43Error("R4_3_COMMAND_INVALID", f"unsupported R4.3 command: {command_type}")
        command_identifier = command_id or self._idempotency(command_type, entity_id)
        idempotency_key = self._idempotency(command_type, entity_id)
        if existing is not None:
            digest_name = {R4_3_OPEN_CONFIRMED_DEFECT_LIFECYCLE: "lifecycle_digest", R4_3_RECORD_FIX_LINK: "link_digest", R4_3_RECORD_FIX_DETECTION_ASSESSMENT: "detection_digest"}.get(command_type)
            if digest_name is not None and existing.to_dict().get(digest_name) == payload.get(digest_name):
                return self._duplicate(command_identifier, mission_id, existing, idempotency_key)
            raise R43Error(CONFLICT, f"immutable {command_type} identity already exists with a different digest")
        try:
            result = self.runtime_service.execute(
                {
                    "command_id": command_identifier,
                    "type": command_type,
                    "mission_id": mission_id,
                    "session_id": None,
                    "expected_seq": self.runtime_service.get_head_seq(mission_id) if expected_seq is None else expected_seq,
                    "actor": (actor or self.actor).to_dict(),
                    "payload": payload,
                    "idempotency_key": idempotency_key,
                    "correlation_id": correlation_id or command_identifier,
                    "schema_version": 1,
                }
            )
        except (R43Error, DurableRuntimeError) as exc:
            return self._error(command_identifier, mission_id, exc)
        entity = None
        if result.ok:
            value = self.state(mission_id)
            if command_type == R4_3_OPEN_CONFIRMED_DEFECT_LIFECYCLE:
                entity = value.lifecycle(entity_id)
            elif command_type == R4_3_RECORD_FIX_LINK:
                entity = value.fix_link(entity_id)
            elif command_type == R4_3_RECORD_FIX_DETECTION_ASSESSMENT:
                entity = value.detection(entity_id)
            else:
                entity = value.request(entity_id)
        return R43OperationResult(result, entity)

    @staticmethod
    def _idempotency(command_type: str, entity_id: str) -> str:
        prefix = {
            R4_3_OPEN_CONFIRMED_DEFECT_LIFECYCLE: "lifecycle",
            R4_3_RECORD_FIX_LINK: "fix-link",
            R4_3_REQUEST_FIX_DETECTION: "fix-detection-request",
            R4_3_RECORD_FIX_DETECTION_ASSESSMENT: "fix-detection",
        }[command_type]
        return f"r4.3:{prefix}:{entity_id}"

    def open_confirmed_defect_lifecycle(
        self,
        value: ConfirmedDefectLifecycle | Mapping[str, Any] | None = None,
        *,
        expected_seq: int | None = None,
        command_id: str | None = None,
        correlation_id: str | None = None,
        actor: ActorRef | None = None,
        **fields: Any,
    ) -> R43OperationResult:
        raw = self._mapping(value, fields)
        try:
            if "lifecycle_id" not in raw:
                lifecycle = make_lifecycle(
                    owner_mission_id=raw["stream_owner_mission_id"], r3_6_defect_assessment_ref=raw["r3_6_defect_assessment_ref"],
                    r3_6_assessment_digest=raw["r3_6_assessment_digest"], quality_version_ref=raw["quality_version_ref"],
                    campaign_refs=raw["campaign_refs"], correlation_id=correlation_id or "r4.3:lifecycle",
                )
                raw = lifecycle.to_dict()
                raw = self._mapping(raw, {})
            for key in ("severity_refs", "priority_refs", "rca_refs", "evidence_refs", "fix_link_refs", "fix_detection_refs"):
                raw.setdefault(key, [])
            raw.setdefault("state", "CONFIRMED")
            lifecycle = ConfirmedDefectLifecycle.from_dict({**raw, "created_seq": 1, "created_at": "validated", "correlation_id": correlation_id or "r4.3:lifecycle"})
            validate_r3_6_reference(self.runtime_service, lifecycle.stream_owner_mission_id, lifecycle.r3_6_defect_assessment_ref)
            return self._execute(
                payload={key: raw[key] for key in LIFECYCLE_FIELDS}, command_type=R4_3_OPEN_CONFIRMED_DEFECT_LIFECYCLE,
                entity_id=lifecycle.lifecycle_id, mission_id=lifecycle.stream_owner_mission_id, expected_seq=expected_seq,
                command_id=command_id, correlation_id=correlation_id, actor=actor,
                existing=self.state(lifecycle.stream_owner_mission_id).lifecycle(lifecycle.lifecycle_id),
            )
        except Exception as exc:
            return self._error(command_id or str(raw.get("lifecycle_id") or ""), str(raw.get("stream_owner_mission_id") or ""), exc)

    def record_fix_link(
        self,
        value: FixLink | Mapping[str, Any] | None = None,
        *,
        expected_seq: int | None = None,
        command_id: str | None = None,
        correlation_id: str | None = None,
        actor: ActorRef | None = None,
        **fields: Any,
    ) -> R43OperationResult:
        raw = self._mapping(value, fields)
        try:
            if "fix_link_id" not in raw:
                link = make_fix_link(**raw, correlation_id=correlation_id or "r4.3:fix-link")
                raw = self._mapping(link, {})
            for key, default in (("build_ref", None), ("deployment_ref", None), ("environment_ref", None), ("source_ref", None), ("confidence", None), ("supersedes_fix_link_ref", None)):
                raw.setdefault(key, default)
            for key, default in (("fix_candidate_refs", []), ("source_change_refs", []), ("commit_patch_pr_refs", []), ("claimed_scope_refs", []), ("rationale_refs", []), ("provenance_refs", [])):
                raw.setdefault(key, default)
            raw.setdefault("freshness", "CURRENT")
            raw.setdefault("availability", "AVAILABLE")
            link = FixLink.from_dict({**raw, "created_seq": 1, "created_at": "validated", "correlation_id": correlation_id or "r4.3:fix-link"})
            mission_id = link.stream_owner_mission_id
            return self._execute(
                payload={key: raw[key] for key in FIX_LINK_FIELDS}, command_type=R4_3_RECORD_FIX_LINK, entity_id=link.fix_link_id,
                mission_id=mission_id, expected_seq=expected_seq, command_id=command_id, correlation_id=correlation_id, actor=actor,
                existing=self.state(mission_id).fix_link(link.fix_link_id),
            )
        except Exception as exc:
            return self._error(command_id or str(raw.get("fix_link_id") or ""), str(raw.get("stream_owner_mission_id") or ""), exc)

    def request_fix_detection(
        self,
        value: FixDetectionRequest | Mapping[str, Any] | None = None,
        *,
        expected_seq: int | None = None,
        command_id: str | None = None,
        correlation_id: str | None = None,
        actor: ActorRef | None = None,
        **fields: Any,
    ) -> R43OperationResult:
        raw = self._mapping(value, fields)
        mission_id = str(raw.get("stream_owner_mission_id") or "")
        try:
            if "request_id" not in raw:
                raise R43Error("R4_3_COMMAND_INVALID", "request_id is required for a detection request")
            request = FixDetectionRequest(
                request_id=raw["request_id"], stream_owner_mission_id=mission_id,
                confirmed_defect_lifecycle_ref=raw["confirmed_defect_lifecycle_ref"], fix_link_ref=raw["fix_link_ref"],
                quality_version_ref=raw["quality_version_ref"], campaign_ref=raw["campaign_ref"], detection_scope=raw["detection_scope"],
                detection_policy_version=raw.get("detection_policy_version", "r4.3-fix-detection-policy-v1"), created_seq=1,
                created_at="validated", correlation_id=correlation_id or "r4.3:request",
            )
            return self._execute(
                payload={key: raw[key] for key in REQUEST_FIELDS}, command_type=R4_3_REQUEST_FIX_DETECTION, entity_id=request.request_id,
                mission_id=mission_id, expected_seq=expected_seq, command_id=command_id, correlation_id=correlation_id, actor=actor,
                existing=self.state(mission_id).request(request.request_id),
            )
        except Exception as exc:
            return self._error(command_id or str(raw.get("request_id") or ""), mission_id, exc)

    def record_fix_detection_assessment(
        self,
        value: FixDetectionAssessment | Mapping[str, Any] | None = None,
        *,
        expected_seq: int | None = None,
        command_id: str | None = None,
        correlation_id: str | None = None,
        actor: ActorRef | None = None,
        **fields: Any,
    ) -> R43OperationResult:
        raw = self._mapping(value, fields)
        mission_id = str(raw.get("stream_owner_mission_id") or "")
        try:
            for key, default in (("source_revision_refs", []), ("build_refs", []), ("deployment_refs", []), ("environment_refs", []), ("observation_refs", []), ("detection_basis", []), ("reason_refs", []), ("evidence_refs", [])):
                raw.setdefault(key, default)
            raw.setdefault("detection_policy_version", "r4.3-fix-detection-policy-v1")
            assessment = FixDetectionAssessment.from_dict({**raw, "created_seq": 1, "created_at": "validated", "correlation_id": correlation_id or "r4.3:detection"}) if "fix_detection_id" in raw else make_detection(**raw, correlation_id=correlation_id or "r4.3:detection")
            raw = self._mapping(assessment, {})
            return self._execute(
                payload={key: raw[key] for key in DETECTION_FIELDS}, command_type=R4_3_RECORD_FIX_DETECTION_ASSESSMENT,
                entity_id=assessment.fix_detection_id, mission_id=mission_id or assessment.stream_owner_mission_id,
                expected_seq=expected_seq, command_id=command_id, correlation_id=correlation_id, actor=actor,
                existing=self.state(mission_id or assessment.stream_owner_mission_id).detection(assessment.fix_detection_id),
            )
        except Exception as exc:
            return self._error(command_id or str(raw.get("fix_detection_id") or ""), mission_id, exc)


__all__ = ["R43OperationResult", "R43ApplicationService", "compose_r4_3_runtime"]
