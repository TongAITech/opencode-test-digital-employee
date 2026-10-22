"""Evidence-gated terminal failure route for formal RC8 WorkItems."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from rc8_center.control_plane import CenterControlError


class WorkFailureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: str = Field(min_length=1, max_length=200)
    lease_id: str = Field(min_length=1, max_length=200)


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
    if detail in {"WORK_ITEM_NOT_FOUND", "NODE_NOT_REGISTERED"}:
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def register_failure_routes(app: FastAPI) -> None:
    def control():
        value = getattr(app.state, "formal_control", None)
        if value is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="FORMAL_CONTROL_NOT_CONFIGURED",
            )
        return value

    @app.post("/api/v1/work-items/{work_item_id}/fail")
    def fail_work_item(work_item_id: str, request: WorkFailureRequest) -> Dict[str, Any]:
        try:
            value = control().fail_work_item(
                work_item_id,
                request.node_id,
                request.lease_id,
            )
            return {
                "work_item": _jsonable(value),
                "truth_note": "TERMINAL_STATE_DERIVED_FROM_R1_PROJECTED_ATTEMPT_AND_AVAILABLE_EVIDENCE",
            }
        except (CenterControlError, ValueError) as exc:
            raise _error(exc) from exc
