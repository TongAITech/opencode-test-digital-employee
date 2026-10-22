"""Autonomous WorkItem claim routes for RC8 formal Center."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from rc8_center.control_plane import CenterControlError


class ClaimNextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ttl_seconds: int = Field(default=60, ge=5, le=3600)
    test_run_id: Optional[str] = Field(default=None, min_length=1, max_length=160)


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
    if detail in {"NODE_NOT_REGISTERED"}:
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    if detail in {"NODE_NOT_LEASE_ELIGIBLE", "LEASE_TTL_INVALID"}:
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def register_claim_routes(app: FastAPI) -> None:
    def control():
        value = getattr(app.state, "formal_control", None)
        if value is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="FORMAL_CONTROL_NOT_CONFIGURED",
            )
        return value

    @app.post("/api/v1/nodes/{node_id}/work/claim-next")
    def claim_next(node_id: str, request: ClaimNextRequest) -> Dict[str, Any]:
        try:
            plane = control()
            claimed = plane.claim_next_work_item(
                node_id,
                ttl_seconds=request.ttl_seconds,
                test_run_id=request.test_run_id,
            )
            if claimed is None:
                return {
                    "claimed": False,
                    "work_item": None,
                    "stage_instance_id": None,
                    "truth_note": "NO_COMPATIBLE_READY_WORK_ITEM",
                }
            stage_instance_id = plane.stage_instance_id_for_work_item(claimed.identity.work_item_id)
            return {
                "claimed": True,
                "work_item": _jsonable(claimed),
                "stage_instance_id": stage_instance_id,
                "truth_note": "POSTGRES_CANDIDATE_REDIS_LEASE_CAS_POSTGRES_MIRROR",
            }
        except (CenterControlError, ValueError) as exc:
            raise _error(exc) from exc
