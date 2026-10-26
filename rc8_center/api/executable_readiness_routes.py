"""Lease-bound N6 executable-readiness routes for the formal RC8 Center.

N6 has two distinct Attempt identities by design:
- the N6 WorkItem lease is the governance Attempt authorizing each N6 write;
- the N5 PreparedAttempt attempt_id is the case execution Attempt inherited by
  the ExecutableSpec and later execution evidence.

Workers may submit build/semantic evidence, but may not choose either Attempt,
PreparedAttempt, ExecutableSpec, TestRun, case or MissionNode identity. READY is
a deterministic Center transition from a verified current ExecutableSpec; it is
not a Worker PASS declaration.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from rc8_center.control_plane import CenterControlError, WorkItemState
from rc8_center.executable_readiness import ExecutableReadinessError
from rc8_center.prepared_attempt import PreparedAttemptError, PreparedAttemptState
from rc8_runtime.governance import AttemptStatus
from rc8_runtime.mission_graph import MissionStageType
from rc8_runtime.mission_nodes import MissionNodeAdoptionGraph, MissionNodeType, binding_for_stage


class ExecutableSpecBuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lease_id: str = Field(min_length=1, max_length=160)
    frozen_case_ref: str = Field(min_length=1, max_length=300)
    driver_ref: str = Field(min_length=1, max_length=300)
    script_artifact_ref: str = Field(min_length=1, max_length=300)
    fixture_binding_refs: List[str] = Field(min_length=1, max_length=256)
    assertion_refs: List[str] = Field(min_length=1, max_length=256)
    evidence_collector_refs: List[str] = Field(min_length=1, max_length=256)
    build_evidence_refs: List[str] = Field(min_length=1, max_length=256)


class ExecutableSpecVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lease_id: str = Field(min_length=1, max_length=160)
    semantic_evidence_refs: List[str] = Field(min_length=1, max_length=256)


class ExecutableSpecReadyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lease_id: str = Field(min_length=1, max_length=160)


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
    if detail in {"WORK_ITEM_NOT_FOUND", "EXECUTABLE_SPEC_NOT_FOUND"}:
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    if detail in {"ACTIVE_WORK_ITEM_LEASE_REQUIRED", "CURRENT_EXECUTABLE_SPEC_ALREADY_EXISTS"}:
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
        raise ExecutableReadinessError("N6_CASE_SCOPE_REQUIRED")
    return matches[0]


def register_executable_readiness_routes(app: FastAPI) -> None:
    def executable_readiness():
        value = getattr(app.state, "executable_readiness", None)
        if value is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="EXECUTABLE_READINESS_SERVICE_NOT_CONFIGURED",
            )
        return value

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
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="FORMAL_CONTROL_NOT_CONFIGURED")
        return value

    def control_repository():
        value = getattr(app.state, "control_repository", None)
        if value is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="CONTROL_REPOSITORY_NOT_CONFIGURED")
        return value

    def governance_repository():
        value = getattr(app.state, "governance_repository", None)
        if value is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="GOVERNANCE_REPOSITORY_NOT_CONFIGURED")
        return value

    def n6_authority(work_item_id: str, lease_id: str) -> Dict[str, Any]:
        plane = control()
        work = control_repository().get_work_item(work_item_id)
        if work is None:
            raise CenterControlError("WORK_ITEM_NOT_FOUND")
        if work.state != WorkItemState.RUNNING:
            raise ExecutableReadinessError("N6_WORK_ITEM_MUST_BE_RUNNING")
        if work.identity.stage != MissionStageType.EXECUTABLE_SPEC.value:
            raise ExecutableReadinessError("N6_STAGE_REQUIRED")

        governance_lease_id = str(lease_id or "").strip()
        node_id = str(work.lease_owner_node_id or "").strip()
        if not node_id or str(work.lease_id or "") != governance_lease_id:
            raise CenterControlError("ACTIVE_WORK_ITEM_LEASE_REQUIRED")
        work = plane.authorize_work_item_write(
            test_run_id=work.identity.test_run_id,
            work_item_id=work_item_id,
            node_id=node_id,
            lease_id=governance_lease_id,
        )

        case_id = _case_id_from_scope_refs(work.identity.scope_refs)
        stage_instance_id = plane.stage_instance_id_for_work_item(work_item_id)
        if not stage_instance_id:
            raise ExecutableReadinessError("N6_STAGE_INSTANCE_REQUIRED")
        stage = governance_repository().get_stage(stage_instance_id)
        if stage is None:
            raise ExecutableReadinessError("N6_STAGE_INSTANCE_REQUIRED")
        if stage.test_run_id != work.identity.test_run_id:
            raise ExecutableReadinessError("N6_STAGE_TEST_RUN_MISMATCH")
        if stage.stage_type != MissionStageType.EXECUTABLE_SPEC.value:
            raise ExecutableReadinessError("N6_STAGE_REQUIRED")

        binding = binding_for_stage(stage.stage_type)
        if binding.mission_node_type != MissionNodeType.N6_SCRIPT_BUILD_READINESS:
            raise ExecutableReadinessError("N6_MISSION_NODE_BINDING_REQUIRED")
        mission_node = MissionNodeAdoptionGraph(
            work.identity.test_run_id,
            stage.scope_version,
        ).node(binding.mission_node_type)

        governance_attempt = governance_repository().get_attempt(governance_lease_id)
        if governance_attempt is None or governance_attempt.status != AttemptStatus.STARTED:
            raise ExecutableReadinessError("CENTER_STARTED_N6_ATTEMPT_REQUIRED")
        if governance_attempt.test_run_id != work.identity.test_run_id:
            raise ExecutableReadinessError("N6_ATTEMPT_TEST_RUN_MISMATCH")
        if governance_attempt.work_item_id != work_item_id:
            raise ExecutableReadinessError("N6_ATTEMPT_WORK_ITEM_MISMATCH")
        if governance_attempt.stage_instance_id != stage_instance_id:
            raise ExecutableReadinessError("N6_ATTEMPT_STAGE_MISMATCH")
        if governance_attempt.case_id != case_id:
            raise ExecutableReadinessError("N6_ATTEMPT_CASE_MISMATCH")
        if governance_attempt.producer_node_id != node_id:
            raise ExecutableReadinessError("N6_ATTEMPT_NODE_MISMATCH")
        if governance_attempt.input_snapshot_ref != stage.scope_version:
            raise ExecutableReadinessError("N6_ATTEMPT_INPUT_SNAPSHOT_MISMATCH")

        prepared = prepared_attempts().current_for_case(
            test_run_id=work.identity.test_run_id,
            case_id=case_id,
        )
        if prepared is None:
            raise ExecutableReadinessError("N6_REQUIRES_CURRENT_N5_PREPARED_ATTEMPT")
        if prepared.state != PreparedAttemptState.PREPARED:
            raise ExecutableReadinessError("N6_REQUIRES_N5_PREPARED_STATE")

        try:
            prepared_attempts().require_current_for_execution(
                prepared_attempt_id=prepared.prepared_attempt_id,
                test_run_id=prepared.test_run_id,
                case_id=prepared.case_id,
                attempt_id=prepared.attempt_id,
            )
        except PreparedAttemptError as exc:
            raise ExecutableReadinessError("N6_REQUIRES_N5_PREPARED_ATTEMPT:%s" % exc) from exc

        return {
            "work": work,
            "stage": stage,
            "case_id": case_id,
            "mission_node": mission_node,
            "governance_attempt": governance_attempt,
            "prepared": prepared,
            "executable_spec_id": "executable:%s" % prepared.prepared_attempt_id,
        }

    def transition_response(authority: Dict[str, Any], value: Any, transition: str) -> Dict[str, Any]:
        return {
            "executable_spec": _jsonable(value),
            "transition": transition,
            "n6_governance_attempt_id": authority["governance_attempt"].attempt_id,
            "case_execution_attempt_id": authority["prepared"].attempt_id,
            "truth_note": "CENTER_REAUTHORIZED_N6_LEASE_AND_CURRENT_N5_PREPARED_ATTEMPT",
        }

    @app.post("/api/v1/work-items/{work_item_id}/executable-specs/build")
    def build_executable_spec(work_item_id: str, request: ExecutableSpecBuildRequest) -> Dict[str, Any]:
        try:
            authority = n6_authority(work_item_id, request.lease_id)
            prepared = authority["prepared"]
            value = executable_readiness().build(
                executable_spec_id=authority["executable_spec_id"],
                test_run_id=authority["work"].identity.test_run_id,
                mission_node_id=authority["mission_node"].mission_node_id,
                case_id=authority["case_id"],
                # Deliberately inherited from N5; never the N6 governance lease.
                attempt_id=prepared.attempt_id,
                prepared_attempt_id=prepared.prepared_attempt_id,
                frozen_case_ref=request.frozen_case_ref,
                driver_ref=request.driver_ref,
                script_artifact_ref=request.script_artifact_ref,
                fixture_binding_refs=request.fixture_binding_refs,
                assertion_refs=request.assertion_refs,
                evidence_collector_refs=request.evidence_collector_refs,
                build_evidence_refs=request.build_evidence_refs,
            )
            return {
                "executable_spec": _jsonable(value),
                "n6_governance_attempt_id": authority["governance_attempt"].attempt_id,
                "case_execution_attempt_id": prepared.attempt_id,
                "truth_note": "N6_GOVERNANCE_LEASE_AUTHORIZES_WRITE_WHILE_N5_PREPARED_ATTEMPT_OWNS_CASE_EXECUTION_IDENTITY",
            }
        except (CenterControlError, PreparedAttemptError, ExecutableReadinessError, ValueError) as exc:
            raise _error(exc) from exc

    @app.post("/api/v1/work-items/{work_item_id}/executable-specs/verify")
    def verify_executable_spec(work_item_id: str, request: ExecutableSpecVerifyRequest) -> Dict[str, Any]:
        try:
            authority = n6_authority(work_item_id, request.lease_id)
            value = executable_readiness().verify(
                authority["executable_spec_id"],
                semantic_evidence_refs=request.semantic_evidence_refs,
            )
            return transition_response(authority, value, "VERIFIED")
        except (CenterControlError, PreparedAttemptError, ExecutableReadinessError, ValueError) as exc:
            raise _error(exc) from exc

    @app.post("/api/v1/work-items/{work_item_id}/executable-specs/ready")
    def ready_executable_spec(work_item_id: str, request: ExecutableSpecReadyRequest) -> Dict[str, Any]:
        try:
            authority = n6_authority(work_item_id, request.lease_id)
            value = executable_readiness().mark_ready(authority["executable_spec_id"])
            return transition_response(authority, value, "READY")
        except (CenterControlError, PreparedAttemptError, ExecutableReadinessError, ValueError) as exc:
            raise _error(exc) from exc
