"""Token-authorized N7 TOOL mutation routes.

Generic runtime/artifact routes deliberately carry no N7 tool-invocation token.
Result-authoritative TOOL writes therefore fail closed in the Center wrappers.
Only these routes transport the short-lived token issued with the admitted N7
execution bundle.  The token is authorization only; R1 remains runtime truth.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any, Dict

from fastapi import FastAPI, Header, HTTPException, Response, status

from rc8_center.formal_artifacts import FormalArtifactError
from rc8_runtime import ArtifactAvailability, RuntimeEventEnvelope, RuntimeProducerKind
from rc8_runtime.artifacts import ArtifactManifest

from .schemas import ArtifactBeginRequest, RuntimeEventRequest


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


def register_n7_tool_routes(app: FastAPI) -> None:
    def control() -> object:
        value = getattr(app.state, "formal_control", None)
        if value is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="FORMAL_CONTROL_NOT_CONFIGURED")
        return value

    def artifacts() -> object:
        value = getattr(app.state, "artifact_service", None)
        if value is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="FORMAL_ARTIFACT_SERVICE_NOT_CONFIGURED")
        return value

    @app.post("/api/v1/n7/tool-runtime-events")
    def append_n7_tool_runtime_event(
        request: RuntimeEventRequest,
        x_rc8_n7_tool_invocation_token: str = Header(alias="X-RC8-N7-Tool-Invocation-Token", min_length=1),
    ) -> Dict[str, Any]:
        try:
            producer_kind = RuntimeProducerKind(request.producer_kind)
            if producer_kind != RuntimeProducerKind.TOOL:
                raise ValueError("N7_TOOL_ROUTE_REQUIRES_TOOL_PRODUCER")
            if str(request.event_type or "").strip().upper() != "ASSERTION_OBSERVED":
                raise ValueError("N7_TOOL_ROUTE_REQUIRES_ASSERTION_OBSERVED")
            event = RuntimeEventEnvelope(
                event_id=request.event_id,
                test_run_id=request.test_run_id,
                work_item_id=request.work_item_id,
                node_id=request.node_id,
                producer_kind=producer_kind,
                producer_ref=request.producer_ref,
                event_type=request.event_type,
                sequence=request.sequence,
                case_id=request.case_id,
                attempt_id=request.attempt_id,
                step_id=request.step_id,
                refs=request.refs,
                data=request.data,
                occurred_at=request.occurred_at,
            )
            result = control().append_runtime_event(
                event,
                lease_id=request.lease_id,
                n7_tool_invocation_token=x_rc8_n7_tool_invocation_token,
            )
            return _jsonable(result)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    @app.post("/api/v1/n7/tool-artifacts/begin", status_code=status.HTTP_201_CREATED)
    def begin_n7_tool_artifact(
        request: ArtifactBeginRequest,
        response: Response,
        x_rc8_n7_tool_invocation_token: str = Header(alias="X-RC8-N7-Tool-Invocation-Token", min_length=1),
    ) -> Dict[str, Any]:
        try:
            values = request.model_dump()
            lease_id = values.pop("lease_id")
            producer_kind = RuntimeProducerKind(values.pop("producer_kind"))
            if producer_kind != RuntimeProducerKind.TOOL:
                raise ValueError("N7_TOOL_ROUTE_REQUIRES_TOOL_PRODUCER")
            manifest = ArtifactManifest(
                **values,
                producer_kind=producer_kind,
                availability=ArtifactAvailability.PENDING_UPLOAD,
            )
            result = artifacts().begin(
                manifest,
                lease_id=lease_id,
                n7_tool_invocation_token=x_rc8_n7_tool_invocation_token,
            )
            response.headers["Location"] = "/api/v1/artifacts/%s/upload-status" % manifest.artifact_id
            response.headers["Upload-Offset"] = str(result["offset"])
            return _jsonable(result)
        except (FormalArtifactError, ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
