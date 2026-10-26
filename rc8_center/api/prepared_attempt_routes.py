"""Lease-bound N5 PreparedAttempt routes for the formal RC8 Center.

The worker may submit candidate data/reality references, but it may not choose
the TestRun, case, execution Attempt, PreparedAttempt or MissionNode identity.
Those identities are derived from the current PostgreSQL + Redis lease and the
R1-projected Center-owned ATTEMPT_STARTED fact.
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

    @app.post("/api/v1/work-items/{work_item_id}/prepared-attempts/select")
    def select_prepared_attempt(work_item_id: str, request: PreparedAttemptSelectRequest) -> Dict[str, Any]:
        try:
            plane = control()
            work = control_repository().get_work_item(work_item_id)
            if work is None:
                raise CenterControlError("WORK_ITEM_NOT_FOUND")
            if work.state != WorkItemState.RUNNING:
                raise PreparedAttemptError("N5_WORK_ITEM_MUST_BE_RUNNING")
            if work.identity.stage != MissionStageType.PRECONDITION_DATA_PREP.value:
                raise PreparedAttemptError("N5_STAGE_REQUIRED")

            lease_id = request.lease_id.strip()
            node_id = str(work.lease_owner_node_id or "").strip()
            if not node_id or str(work.lease_id or "") != lease_id:
                raise CenterControlError("ACTIVE_WORK_ITEM_LEASE_REQUIRED")
            # This is the formal PG + Redis lease agreement gate. The worker
            # cannot supply node/test-run authority independently.
            work = plane.authorize_work_item_write(
                test_run_id=work.identity.test_run_id,
                work_item_id=work_item_id,
                node_id=node_id,
                lease_id=lease_id,
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

            # /start is Center-owned and must already have projected the exact
            # lease identity into governance before N5 may select data.
            attempt = governance_repository().get_attempt(lease_id)
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

            value = prepared_attempts().select(
                prepared_attempt_id="prepared:%s" % lease_id,
                test_run_id=work.identity.test_run_id,
                mission_node_id=mission_node.mission_node_id,
                case_id=case_id,
                attempt_id=lease_id,
                reality_snapshot_id=request.reality_snapshot_id,
                data_refs=request.data_refs,
            )
            return {
                "prepared_attempt": _jsonable(value),
                "truth_note": "CENTER_DERIVED_FROM_RUNNING_N5_WORK_ITEM_ACTIVE_LEASE_AND_R1_PROJECTED_ATTEMPT",
            }
        except (CenterControlError, PreparedAttemptError, ValueError) as exc:
            raise _error(exc) from exc
