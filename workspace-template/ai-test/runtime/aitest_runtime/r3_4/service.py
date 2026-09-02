from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from aitest_runtime.durable_core import ActorRef, CommandResult, RuntimeError, RuntimeService
from aitest_runtime.durable_core.schema import connect

from .contracts import (
    APPROVE_ORACLE_SPECIFICATION,
    ASSESS_EXECUTION_READINESS,
    BUILD_REVIEW_CONTEXT,
    EVALUATE_ORACLE,
    RECORD_TEST_RESULT,
    REGISTER_CASE_EXECUTION_ATTEMPT,
    RESOLVE_PRECONDITION,
    RESOLVE_TEST_DATA,
    REVIEW_CASE,
    CaseExecutionAttempt,
    CaseReview,
    ExecutionReadinessAssessment,
    OracleEvaluation,
    OracleSpecification,
    PreconditionResolution,
    R34State,
    TestDataResolution,
    TestResult,
    request_from_mapping,
)


@dataclass(frozen=True)
class R34OperationResult:
    command_result: CommandResult
    reviewer_context: Any | None = None
    review: CaseReview | None = None
    oracle: OracleSpecification | None = None
    readiness: ExecutionReadinessAssessment | None = None
    precondition_resolution: PreconditionResolution | None = None
    test_data_resolution: TestDataResolution | None = None
    attempt: CaseExecutionAttempt | None = None
    evaluation: OracleEvaluation | None = None
    result: TestResult | None = None

    @property
    def ok(self) -> bool:
        return self.command_result.ok

    @property
    def outcome(self) -> str:
        return self.command_result.outcome

    @property
    def error_code(self) -> str | None:
        return self.command_result.error_code


class R34ApplicationService:
    """R3.4 application boundary over the shared R1 RuntimeService."""

    def __init__(self, runtime: RuntimeService, *, actor: ActorRef | None = None) -> None:
        if runtime is None:
            raise ValueError("runtime is required")
        runtime.extension_registry.manifest("r3_4_case_review_execution_readiness_oracle")
        self.runtime = runtime
        self.actor = actor or ActorRef("SYSTEM", "r3.4")

    def state(self, mission_id: str) -> R34State:
        value = self.runtime.replay_composed(mission_id).extension_state("r3_4_case_review_execution_readiness_oracle")
        if not isinstance(value, R34State):
            raise RuntimeError("R3_4_STATE_INVALID", "R3.4 extension state is not registered")
        return value

    get_state = state

    def build_review_context(self, request: Mapping[str, Any]) -> R34OperationResult:
        return self._execute(BUILD_REVIEW_CONTEXT, "build_review_context", request, reviewer_context=True)

    def review_case(self, request: Mapping[str, Any]) -> R34OperationResult:
        return self._execute(REVIEW_CASE, "review_case", request, review=True)

    def approve_oracle_specification(self, request: Mapping[str, Any]) -> R34OperationResult:
        return self._execute(APPROVE_ORACLE_SPECIFICATION, "approve_oracle_specification", request, oracle=True)

    def assess_execution_readiness(self, request: Mapping[str, Any]) -> R34OperationResult:
        return self._execute(ASSESS_EXECUTION_READINESS, "assess_execution_readiness", request, readiness=True)

    def resolve_precondition(self, request: Mapping[str, Any]) -> R34OperationResult:
        return self._execute(RESOLVE_PRECONDITION, "resolve_precondition", request, precondition_resolution=True)

    def resolve_test_data(self, request: Mapping[str, Any]) -> R34OperationResult:
        return self._execute(RESOLVE_TEST_DATA, "resolve_test_data", request, test_data_resolution=True)

    def register_case_execution_attempt(self, request: Mapping[str, Any]) -> R34OperationResult:
        return self._execute(REGISTER_CASE_EXECUTION_ATTEMPT, "register_case_execution_attempt", request, attempt=True)

    def evaluate_oracle(self, request: Mapping[str, Any]) -> R34OperationResult:
        return self._execute(EVALUATE_ORACLE, "evaluate_oracle", request, evaluation=True)

    def record_test_result(self, request: Mapping[str, Any]) -> R34OperationResult:
        return self._execute(RECORD_TEST_RESULT, "record_test_result", request, result=True)

    def _execute(self, command_type: str, operation: str, raw_request: Mapping[str, Any], **lookup: bool) -> R34OperationResult:
        request = request_from_mapping(raw_request)
        mission_id = request.get("mission_id")
        if not isinstance(mission_id, str) or not mission_id.strip():
            raise ValueError("request.mission_id is required")
        command_id = f"r3.4:{request['idempotency_key']}:{operation}"
        command_result = self.runtime.execute({
            "command_id": command_id,
            "type": command_type,
            "mission_id": mission_id,
            "session_id": request.get("session_id"),
            "expected_seq": self._expected_seq(command_id, mission_id),
            "actor": self.actor.to_dict(),
            "payload": {"request": request},
            "idempotency_key": request["idempotency_key"],
            "correlation_id": request["correlation_id"],
            "schema_version": 1,
        })
        if not command_result.ok:
            return R34OperationResult(command_result)
        state = self.state(mission_id)
        values: dict[str, Any] = {}
        if lookup.get("reviewer_context"):
            values["reviewer_context"] = self._latest_by_request(state.reviewer_contexts, request, "reviewer_context_id")
        if lookup.get("review"):
            values["review"] = self._latest_by_request(state.case_reviews, request, "case_review_id")
        if lookup.get("oracle"):
            values["oracle"] = self._latest_by_request(state.oracle_specifications, request, "oracle_specification_id")
        if lookup.get("readiness"):
            values["readiness"] = self._latest_by_request(state.execution_readiness, request, "execution_readiness_id")
        if lookup.get("precondition_resolution"):
            values["precondition_resolution"] = self._latest_by_request(state.precondition_resolutions, request, "precondition_resolution_id", requirement_id="requirement_id")
        if lookup.get("test_data_resolution"):
            values["test_data_resolution"] = self._latest_by_request(state.test_data_resolutions, request, "test_data_resolution_id", requirement_id="requirement_id")
        if lookup.get("attempt"):
            values["attempt"] = self._latest_by_request(state.case_execution_attempts, request, "case_execution_attempt_id")
        if lookup.get("evaluation"):
            values["evaluation"] = self._latest_by_request(state.oracle_evaluations, request, "oracle_evaluation_id")
        if lookup.get("result"):
            values["result"] = self._latest_by_request(state.test_results, request, "test_result_id")
        return R34OperationResult(command_result, **values)

    @staticmethod
    def _latest_by_request(values: tuple[Any, ...], request: Mapping[str, Any], identity_name: str, **fallback_names: str) -> Any | None:
        identity = request.get(identity_name)
        if identity:
            found = next((item for item in values if getattr(item, identity_name) == identity), None)
            if found is not None:
                return found
        for request_name, record_name in fallback_names.items():
            identity = request.get(request_name)
            if identity:
                found = next((item for item in values if getattr(item, record_name) == identity), None)
                if found is not None:
                    return found
        idempotency_key = request.get("idempotency_key")
        if idempotency_key:
            found = next((item for item in reversed(values) if getattr(item, "idempotency_key", None) == idempotency_key), None)
            if found is not None:
                return found
        return values[-1] if values else None

    def _expected_seq(self, command_id: str, mission_id: str) -> int:
        conn = connect(self.runtime.db_path)
        try:
            row = conn.execute("SELECT expected_seq FROM commands WHERE command_id=?", (command_id,)).fetchone()
            return int(row["expected_seq"]) if row is not None else self.runtime.get_head_seq(mission_id)
        finally:
            conn.close()
