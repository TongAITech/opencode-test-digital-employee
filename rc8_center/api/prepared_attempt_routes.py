"""Lease-bound N5 PreparedAttempt routes for the formal RC8 Center.

Workers submit reality/data/evidence observations, but they may not choose the
TestRun, case, execution Attempt, PreparedAttempt or MissionNode identity. Every
N5 state transition re-authorizes the active PostgreSQL + Redis lease and the
R1-projected Center-owned ATTEMPT_STARTED fact before deriving the current
PreparedAttempt identity.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from rc8_center.control_plane import CenterControlError, WorkItemState
from rc8_center.prepared_attempt import PreparedAttemptError
from rc8_runtime.governance import AttemptStatus
from rc8_runtime.mission_graph import MissionStageType
from rc8_runtime.mission_nodes import MissionNodeAdoptionGraph, MissionNodeType, binding_for_stage


class PreparedAttemptSelectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lease_id: str = Field(min_length=1, max_length=160)
    reality_snapshot_id: str = Field(min_length=1, max_length=240)
    data_refs: List[str] = Field(min_length=1, max_length=256)


class PreparedAttemptVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lease_id: str = Field(min_length=1, max_length=160)
    evidence_refs: List[str] = Field(min_length=1, max_length=256)


class PreparedAttemptReserveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lease_id: str = Field(min_length=1, max_length=160)
    reservation_ref: str = Field(min_length=1, max_length=300)
    evidence_refs: List[str] = Field(min_length=1, max_length=256)


class PreparedAttemptFreshnessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lease_id: str = Field(min_length=1, max_length=160)
    data_freshness_ref: str = Field(min_length=1, max_length=300)
    auth_session_ref: str = Field(min_length=1, max_length=300)
    auth_acquired_at: int = Field(ge=0)
    auth_expires_at: int = Field(ge=0)
    evidence_refs: List[str] = Field(min_length=1, max_length=256)


class PreparedAttemptBindRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lease_id: str = Field(min_length=1, max_length=160)
    environment_ref: str = Field(min_length=1, max_length=300)
    route_ref: str = Field(min_length=1, max_length=500)
    evidence_refs: List[str] = Field(min_length=1, max_length=256)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _error(exc: Exception) -> HTTPException:
    detail = str(exc)
    if detail in {"WORK_ITEM_NOT_FOUND", "PREPARED_ATTEMPT_NOT_FOUND"}:
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    if detail in {
        "ACTIVE_WORK_ITEM_LEASE_REQUIRED",
        "CURRENT_PREPARED_ATTEMPT_ALREADY_EXISTS",
        "CURRENT_CASE_ATTEMPT_ALREADY_EXISTS",
        "RETRY_REQUIRES_NEW_ATTEMPT_IDENTITY",
    }:
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _case_id_from_scope_refs(scope_refs: Any) -> str:
    matches = []
    for ref in tuple(scope_refs or ()):
        if not isinstance(ref, str) or not ref.startswith("case:"):
            continue
        value = ref.split(":", 1)[1].strip()
        if value and value not in matches:
            matches.append(value)
    if len(matches) != 1:
        raise PreparedAttemptError("N5_CASE_SCOPE_REQUIRED")
    return matches[0]


def register_prepared_attempt_routes(app: FastAPI) -> None:
    def prepared_attempts():
        value = getattr(app.state, "prepared_attempts", None)
        if value is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="PREPARED_ATTEMPT_SERVICE_NOT_CONFIGURED",
            )
        return value

    def control():
        value = getattr(app.state, "formal_control", None)
        if value is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="FORMAL_CONTROL_NOT_CONFIGURED",
            )
        return value

    def control_repository():
        value = getattr(app.state, "control_repository", None)
        if value is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="CONTROL_REPOSITORY_NOT_CONFIGURED",
            )
        return value

    def governance_repository():
        value = getattr(app.state, "governance_repository", None)
        if value is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="GOVERNANCE_REPOSITORY_NOT_CONFIGURED",
            )
        return value

    def n5_authority(work_item_id: str, lease_id: str) -> Dict[str, Any]:
        plane = control()
        work = control_repository().get_work_item(work_item_id)
        if work is None:
            raise CenterControlError("WORK_ITEM_NOT_FOUND")
        if work.state != WorkItemState.RUNNING:
            raise PreparedAttemptError("N5_WORK_ITEM_MUST_BE_RUNNING")
        if work.identity.stage != MissionStageType.PRECONDITION_DATA_PREP.value:
            raise PreparedAttemptError("N5_STAGE_REQUIRED")

        normalized_lease_id = str(lease_id or "").strip()
        node_id = str(work.lease_owner_node_id or "").strip()
        if not node_id or str(work.lease_id or "") != normalized_lease_id:
            raise CenterControlError("ACTIVE_WORK_ITEM_LEASE_REQUIRED")
        # Formal PG + Redis agreement gate. Worker cannot submit node or run
        # authority independently.
        work = plane.authorize_work_item_write(
            test_run_id=work.identity.test_run_id,
            work_item_id=work_item_id,
            node_id=node_id,
            lease_id=normalized_lease_id,
        )

        case_id = _case_id_from_scope_refs(work.identity.scope_refs)
        stage_instance_id = plane.stage_instance_id_for_work_item(work_item_id)
        if not stage_instance_id:
            raise PreparedAttemptError("N5_STAGE_INSTANCE_REQUIRED")
        stage = governance_repository().get_stage(stage_instance_id)
        if stage is None:
            raise PreparedAttemptError("N5_STAGE_INSTANCE_REQUIRED")
        if stage.test_run_id != work.identity.test_run_id:
            raise PreparedAttemptError("N5_STAGE_TEST_RUN_MISMATCH")
        if stage.stage_type != MissionStageType.PRECONDITION_DATA_PREP.value:
            raise PreparedAttemptError("N5_STAGE_REQUIRED")

        binding = binding_for_stage(stage.stage_type)
        if binding.mission_node_type != MissionNodeType.N5_TEST_DATA_PRECONDITIONS:
            raise PreparedAttemptError("N5_MISSION_NODE_BINDING_REQUIRED")
        mission_node = MissionNodeAdoptionGraph(
            work.identity.test_run_id,
            stage.scope_version,
        ).node(binding.mission_node_type)

        # Center /start must already have projected this exact lease identity.
        attempt = governance_repository().get_attempt(normalized_lease_id)
        if attempt is None or attempt.status != AttemptStatus.STARTED:
            raise PreparedAttemptError("CENTER_STARTED_ATTEMPT_REQUIRED")
        if attempt.test_run_id != work.identity.test_run_id:
            raise PreparedAttemptError("ATTEMPT_TEST_RUN_MISMATCH")
        if attempt.work_item_id != work_item_id:
            raise PreparedAttemptError("ATTEMPT_WORK_ITEM_MISMATCH")
        if attempt.stage_instance_id != stage_instance_id:
            raise PreparedAttemptError("ATTEMPT_STAGE_MISMATCH")
        if attempt.case_id != case_id:
            raise PreparedAttemptError("ATTEMPT_CASE_MISMATCH")
        if attempt.producer_node_id != node_id:
            raise PreparedAttemptError("ATTEMPT_NODE_MISMATCH")
        if attempt.input_snapshot_ref != stage.scope_version:
            raise PreparedAttemptError("ATTEMPT_INPUT_SNAPSHOT_MISMATCH")

        return {
            "work": work,
            "stage": stage,
            "case_id": case_id,
            "attempt": attempt,
            "mission_node": mission_node,
            "prepared_attempt_id": "prepared:%s" % normalized_lease_id,
        }

    def transition_response(value: Any, transition: str) -> Dict[str, Any]:
        return {
            "prepared_attempt": _jsonable(value),
            "transition": transition,
            "truth_note": "CENTER_REAUTHORIZED_N5_ACTIVE_LEASE_AND_R1_PROJECTED_ATTEMPT",
        }

    @app.post("/api/v1/work-items/{work_item_id}/prepared-attempts/select")
    def select_prepared_attempt(work_item_id: str, request: PreparedAttemptSelectRequest) -> Dict[str, Any]:
        try:
            authority = n5_authority(work_item_id, request.lease_id)
            value = prepared_attempts().select(
                prepared_attempt_id=authority["prepared_attempt_id"],
                test_run_id=authority["work"].identity.test_run_id,
                mission_node_id=authority["mission_node"].mission_node_id,
                case_id=authority["case_id"],
                attempt_id=authority["attempt"].attempt_id,
                reality_snapshot_id=request.reality_snapshot_id,
                data_refs=request.data_refs,
            )
            return {
                "prepared_attempt": _jsonable(value),
                "truth_note": "CENTER_DERIVED_FROM_RUNNING_N5_WORK_ITEM_ACTIVE_LEASE_AND_R1_PROJECTED_ATTEMPT",
            }
        except (CenterControlError, PreparedAttemptError, ValueError) as exc:
            raise _error(exc) from exc

    @app.post("/api/v1/work-items/{work_item_id}/prepared-attempts/verify")
    def verify_prepared_attempt(work_item_id: str, request: PreparedAttemptVerifyRequest) -> Dict[str, Any]:
        try:
            authority = n5_authority(work_item_id, request.lease_id)
            value = prepared_attempts().verify(
                authority["prepared_attempt_id"],
                evidence_refs=request.evidence_refs,
            )
            return transition_response(value, "VERIFIED")
        except (CenterControlError, PreparedAttemptError, ValueError) as exc:
            raise _error(exc) from exc

    @app.post("/api/v1/work-items/{work_item_id}/prepared-attempts/reserve")
    def reserve_prepared_attempt(work_item_id: str, request: PreparedAttemptReserveRequest) -> Dict[str, Any]:
        try:
            authority = n5_authority(work_item_id, request.lease_id)
            value = prepared_attempts().reserve(
                authority["prepared_attempt_id"],
                reservation_ref=request.reservation_ref,
                evidence_refs=request.evidence_refs,
            )
            return transition_response(value, "RESERVED")
        except (CenterControlError, PreparedAttemptError, ValueError) as exc:
            raise _error(exc) from exc

    @app.post("/api/v1/work-items/{work_item_id}/prepared-attempts/freshness-check")
    def freshness_check_prepared_attempt(work_item_id: str, request: PreparedAttemptFreshnessRequest) -> Dict[str, Any]:
        try:
            authority = n5_authority(work_item_id, request.lease_id)
            value = prepared_attempts().freshness_check(
                authority["prepared_attempt_id"],
                data_freshness_ref=request.data_freshness_ref,
                auth_session_ref=request.auth_session_ref,
                auth_acquired_at=request.auth_acquired_at,
                auth_expires_at=request.auth_expires_at,
                evidence_refs=request.evidence_refs,
            )
            return transition_response(value, "FRESH")
        except (CenterControlError, PreparedAttemptError, ValueError) as exc:
            raise _error(exc) from exc

    @app.post("/api/v1/work-items/{work_item_id}/prepared-attempts/bind")
    def bind_prepared_attempt(work_item_id: str, request: PreparedAttemptBindRequest) -> Dict[str, Any]:
        try:
            authority = n5_authority(work_item_id, request.lease_id)
            value = prepared_attempts().bind(
                authority["prepared_attempt_id"],
                environment_ref=request.environment_ref,
                route_ref=request.route_ref,
                evidence_refs=request.evidence_refs,
            )
            return transition_response(value, "PREPARED")
        except (CenterControlError, PreparedAttemptError, ValueError) as exc:
            raise _error(exc) from exc
