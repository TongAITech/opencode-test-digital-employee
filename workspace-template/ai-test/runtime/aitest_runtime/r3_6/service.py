from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from aitest_runtime.durable_core import ActorRef, CommandResult, RuntimeService

from .contracts import (
    ARCHITECTURE_BASELINE_REF,
    ASSESS_DEFECT_TRUTH,
    ASSESS_FALSE_POSITIVE,
    CREATE_DEFECT_CANDIDATE,
    EVALUATE_REPRODUCIBILITY,
    EXTENSION_ID,
    RECORD_CROSS_SOURCE_CORRELATION,
    RECORD_EVIDENCE_ASSESSMENT,
    RECORD_INVESTIGATION_CHECKPOINT,
    RECORD_RCA,
    RECORD_TEST_ANOMALY,
    REQUEST_EVIDENCE_DEEPENING,
    R36State,
    SEMANTIC_REUSE,
)
from .errors import R36Error
from .workset import TypedRetrievalProvider, retrieve_workset


@dataclass(frozen=True)
class R36OperationResult:
    command_result: CommandResult
    entity: Any | None = None

    @property
    def ok(self) -> bool:
        return self.command_result.ok

    @property
    def outcome(self) -> str:
        return self.command_result.outcome

    @property
    def error_code(self) -> str | None:
        return self.command_result.error_code

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command_result.to_dict(),
            "entity": self.entity.to_dict() if self.entity is not None else None,
        }


class R36ApplicationService:
    """Thin R3.6 application boundary over the shared R1 RuntimeService."""

    def __init__(self, runtime: RuntimeService, *, actor: ActorRef | None = None) -> None:
        if runtime is None:
            raise R36Error("R3_6_SCHEMA_INVALID", "RuntimeService is required")
        try:
            runtime.extension_registry.manifest(EXTENSION_ID)
        except Exception as exc:
            raise R36Error("R3_6_EXTENSION_REQUIRED", "R3.6 requires its registered durable extension") from exc
        self.runtime = runtime
        self.actor = actor or ActorRef("SYSTEM", "r3.6")

    def state(self, mission_id: str) -> R36State:
        state = self.runtime.replay_composed(mission_id).extension_state(EXTENSION_ID)
        if not isinstance(state, R36State):
            raise R36Error("R3_6_STATE_INVALID", "R3.6 extension state is not registered")
        return state

    get_state = state

    @staticmethod
    def _request(raw: Mapping[str, Any], *, mission_id: str | None = None) -> dict[str, Any]:
        if not isinstance(raw, Mapping):
            raise R36Error("R3_6_SCHEMA_INVALID", "request must be an object")
        request = dict(raw)
        selected_mission = mission_id or request.get("mission_id")
        if not isinstance(selected_mission, str) or not selected_mission.strip():
            raise R36Error("R3_6_SCOPE_MISMATCH", "request.mission_id is required")
        request["mission_id"] = selected_mission
        idempotency_key = request.get("idempotency_key")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise R36Error("R3_6_SCHEMA_INVALID", "request.idempotency_key is required")
        request["correlation_id"] = request.get("correlation_id") or f"corr:{idempotency_key}"
        origin = dict(request.get("origin_lineage") or {})
        origin["mission_id"] = selected_mission
        origin.setdefault("architecture_baseline_ref", ARCHITECTURE_BASELINE_REF)
        request["origin_lineage"] = origin
        for key, value in list(request.items()):
            if hasattr(value, "to_dict") and callable(value.to_dict):
                request[key] = value.to_dict()
        for key, value in list(request.items()):
            if isinstance(value, Mapping) and key not in {"origin_lineage"}:
                entity = dict(value)
                if "origin_lineage" not in entity and key in {
                    "anomaly", "candidate", "deepening", "evidence_assessment", "correlation",
                    "reproducibility", "false_positive", "defect_assessment", "rca", "checkpoint", "reuse",
                }:
                    entity["origin_lineage"] = dict(origin)
                    request[key] = entity
        return request

    def _execute(self, command_type: str, request: Mapping[str, Any], *, entity_type: str, entity_id_key: str) -> R36OperationResult:
        prepared = self._request(request)
        mission_id = prepared["mission_id"]
        command_id = f"r3.6:{command_type}:{prepared['idempotency_key']}"
        result = self.runtime.execute({
            "command_id": command_id,
            "type": command_type,
            "mission_id": mission_id,
            "session_id": prepared.get("session_id"),
            "expected_seq": self._expected_seq(command_id, mission_id),
            "actor": self.actor.to_dict(),
            "payload": {"request": prepared},
            "idempotency_key": prepared["idempotency_key"],
            "correlation_id": prepared["correlation_id"],
            "schema_version": 1,
        })
        if not result.ok:
            return R36OperationResult(result)
        state = self.state(mission_id)
        entity_id = prepared.get(entity_id_key)
        entity = self._lookup(state, entity_type, entity_id, prepared)
        return R36OperationResult(result, entity)

    def _expected_seq(self, command_id: str, mission_id: str) -> int:
        for event in self.runtime.list_events(mission_id):
            if event.command_id == command_id:
                return event.seq - 1
        return self.runtime.get_head_seq(mission_id)

    @staticmethod
    def _lookup(state: R36State, entity_type: str, entity_id: str | None, request: Mapping[str, Any]) -> Any | None:
        values: tuple[Any, ...] = {
            "anomaly": state.anomalies,
            "candidate": state.candidates,
            "deepening": state.deepenings,
            "evidence_assessment": state.evidence_assessments,
            "correlation": state.correlations,
            "reproducibility": state.reproducibility_assessments,
            "false_positive": state.false_positive_assessments,
            "defect_assessment": state.defect_assessments,
            "rca": state.rca_records,
            "checkpoint": state.checkpoints,
            "reuse": state.reuses,
        }[entity_type]
        if entity_id:
            for item in values:
                id_value = next((getattr(item, name) for name in item.__dataclass_fields__ if name.endswith("_id") and getattr(item, name) == entity_id), None)
                if id_value is not None:
                    return item
        return values[-1] if values else None

    def record_test_anomaly(self, request: Mapping[str, Any]) -> R36OperationResult:
        return self._execute(RECORD_TEST_ANOMALY, request, entity_type="anomaly", entity_id_key="anomaly_id")

    def create_defect_candidate(self, request: Mapping[str, Any]) -> R36OperationResult:
        return self._execute(CREATE_DEFECT_CANDIDATE, request, entity_type="candidate", entity_id_key="candidate_id")

    def request_evidence_deepening(self, request: Mapping[str, Any]) -> R36OperationResult:
        return self._execute(REQUEST_EVIDENCE_DEEPENING, request, entity_type="deepening", entity_id_key="deepening_id")

    def record_evidence_assessment(self, request: Mapping[str, Any]) -> R36OperationResult:
        return self._execute(RECORD_EVIDENCE_ASSESSMENT, request, entity_type="evidence_assessment", entity_id_key="assessment_id")

    def record_cross_source_correlation(self, request: Mapping[str, Any]) -> R36OperationResult:
        return self._execute(RECORD_CROSS_SOURCE_CORRELATION, request, entity_type="correlation", entity_id_key="correlation_id")

    def evaluate_reproducibility(self, request: Mapping[str, Any]) -> R36OperationResult:
        return self._execute(EVALUATE_REPRODUCIBILITY, request, entity_type="reproducibility", entity_id_key="reproducibility_id")

    def assess_false_positive(self, request: Mapping[str, Any]) -> R36OperationResult:
        return self._execute(ASSESS_FALSE_POSITIVE, request, entity_type="false_positive", entity_id_key="false_positive_id")

    def assess_defect_truth(self, request: Mapping[str, Any]) -> R36OperationResult:
        return self._execute(ASSESS_DEFECT_TRUTH, request, entity_type="defect_assessment", entity_id_key="assessment_id")

    def record_rca(self, request: Mapping[str, Any]) -> R36OperationResult:
        return self._execute(RECORD_RCA, request, entity_type="rca", entity_id_key="rca_id")

    def record_investigation_checkpoint(self, request: Mapping[str, Any]) -> R36OperationResult:
        return self._execute(RECORD_INVESTIGATION_CHECKPOINT, request, entity_type="checkpoint", entity_id_key="checkpoint_id")

    def record_semantic_reuse(self, request: Mapping[str, Any]) -> R36OperationResult:
        return self._execute(SEMANTIC_REUSE, request, entity_type="reuse", entity_id_key="reuse_id")

    @staticmethod
    def retrieve_workset(request: Any, provider: TypedRetrievalProvider) -> Any:
        return retrieve_workset(request, provider)
