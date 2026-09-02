from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from aitest_runtime.durable_core import ActorRef, CommandResult, RuntimeService

from .contracts import (
    CAMPAIGN_INPUT_FIELDS,
    COMMAND_TYPES,
    CREATE_QUALITY_VERSION,
    CREATE_TEST_CAMPAIGN,
    EXTENSION_ID,
    QUALITY_VERSION_INPUT_FIELDS,
    RECORD_CAMPAIGN_SELECTION_REVISION,
    R41State,
    SELECTION_INPUT_FIELDS,
    CampaignSelectionRevision,
    QualityVersion,
    TestCampaign,
    input_payload,
)
from .errors import R41_COMMAND_INVALID, R41Error
from .extension import r4_1_extension


@dataclass(frozen=True)
class R41OperationResult:
    command_result: CommandResult
    entity: QualityVersion | TestCampaign | CampaignSelectionRevision | None = None

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
        value = self.command_result.to_dict()
        value["entity"] = self.entity.to_dict() if self.entity is not None else None
        return value


def compose_r4_1_runtime(
    db_path: str | Path,
    base_extensions: Iterable[Any] = (),
    *,
    clock: Any = None,
    failure_injector: Any = None,
) -> RuntimeService:
    """Explicitly compose R4.1 around a caller-owned existing RuntimeService core."""
    extensions = tuple(base_extensions)
    if any(getattr(item, "extension_id", None) == EXTENSION_ID for item in extensions):
        raise R41Error(R41_COMMAND_INVALID, "R4.1 extension is already present in the explicit composition")
    return RuntimeService(
        db_path,
        clock=clock,
        failure_injector=failure_injector,
        extensions=extensions + (r4_1_extension(),),
    )


class R41ApplicationService:
    """R4.1 application boundary delegating all durability to the injected RuntimeService."""

    def __init__(self, runtime_service: RuntimeService, *, actor: ActorRef | None = None) -> None:
        if not isinstance(runtime_service, RuntimeService):
            raise TypeError("runtime_service must be the existing RuntimeService")
        runtime_service.extension_registry.manifest(EXTENSION_ID)
        self.runtime_service = runtime_service
        self.runtime = runtime_service
        self.actor = actor or ActorRef("SYSTEM", "r4.1")

    def state(self, mission_id: str) -> R41State:
        composed = self.runtime_service.get_composed_state(mission_id)
        state = composed.extension_state(EXTENSION_ID)
        if not isinstance(state, R41State):
            raise R41Error(R41_COMMAND_INVALID, "R4.1 extension state is invalid")
        return state

    @staticmethod
    def _payload(value: Any, fields: Mapping[str, Any]) -> dict[str, Any]:
        if value is None:
            raw = dict(fields)
        elif isinstance(value, Mapping):
            raw = dict(value)
            if fields:
                raw.update(fields)
        elif isinstance(value, (QualityVersion, TestCampaign, CampaignSelectionRevision)):
            raw = input_payload(value)
            if fields:
                raw.update(fields)
        else:
            raise R41Error(R41_COMMAND_INVALID, "R4.1 service request must be a typed aggregate or mapping")
        return raw

    def _execute(
        self,
        payload: dict[str, Any],
        command_type: str,
        object_id: str,
        *,
        expected_seq: int | None,
        command_id: str | None,
        correlation_id: str | None,
        actor: ActorRef | None,
    ) -> R41OperationResult:
        if command_type not in COMMAND_TYPES:
            raise R41Error(R41_COMMAND_INVALID, f"unsupported R4.1 command: {command_type}")
        if not isinstance(object_id, str) or not object_id.strip():
            raise R41Error(R41_COMMAND_INVALID, "R4.1 aggregate identity is required")
        mission_id = payload.get("stream_owner_mission_id")
        if not isinstance(mission_id, str) or not mission_id.strip():
            raise R41Error(R41_COMMAND_INVALID, "stream_owner_mission_id is required")
        idempotency_key = {
            CREATE_QUALITY_VERSION: f"r4.1:qv:{object_id}",
            CREATE_TEST_CAMPAIGN: f"r4.1:campaign:{object_id}",
            RECORD_CAMPAIGN_SELECTION_REVISION: f"r4.1:selection:{object_id}",
        }[command_type]
        command_identifier = command_id or idempotency_key
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
        entity = None
        if result.ok:
            state = self.state(mission_id)
            if command_type == CREATE_QUALITY_VERSION:
                entity = state.quality_version(object_id)
            elif command_type == CREATE_TEST_CAMPAIGN:
                entity = state.campaign(object_id)
            else:
                entity = state.selection_revision(object_id)
        return R41OperationResult(result, entity)

    def create_quality_version(
        self,
        value: QualityVersion | Mapping[str, Any] | None = None,
        *,
        expected_seq: int | None = None,
        command_id: str | None = None,
        correlation_id: str | None = None,
        actor: ActorRef | None = None,
        **fields: Any,
    ) -> R41OperationResult:
        payload = self._payload(value, fields)
        return self._execute(
            payload, CREATE_QUALITY_VERSION, str(payload.get("quality_version_id") or ""),
            expected_seq=expected_seq, command_id=command_id, correlation_id=correlation_id, actor=actor,
        )

    def create_test_campaign(
        self,
        value: TestCampaign | Mapping[str, Any] | None = None,
        *,
        expected_seq: int | None = None,
        command_id: str | None = None,
        correlation_id: str | None = None,
        actor: ActorRef | None = None,
        **fields: Any,
    ) -> R41OperationResult:
        payload = self._payload(value, fields)
        return self._execute(
            payload, CREATE_TEST_CAMPAIGN, str(payload.get("campaign_id") or ""),
            expected_seq=expected_seq, command_id=command_id, correlation_id=correlation_id, actor=actor,
        )

    def record_campaign_selection_revision(
        self,
        value: CampaignSelectionRevision | Mapping[str, Any] | None = None,
        *,
        expected_seq: int | None = None,
        command_id: str | None = None,
        correlation_id: str | None = None,
        actor: ActorRef | None = None,
        **fields: Any,
    ) -> R41OperationResult:
        payload = self._payload(value, fields)
        return self._execute(
            payload, RECORD_CAMPAIGN_SELECTION_REVISION, str(payload.get("selection_revision_id") or ""),
            expected_seq=expected_seq, command_id=command_id, correlation_id=correlation_id, actor=actor,
        )
