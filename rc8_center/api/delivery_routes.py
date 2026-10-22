"""FastAPI routes for production-batch-first requirement task organization."""
from __future__ import annotations

import time
from dataclasses import asdict
from enum import Enum
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field

from rc8_center.delivery import (
    ProductionBatch,
    ProductionBatchState,
    Requirement,
    RequirementDelivery,
    RequirementDeliveryScope,
    RequirementDeliveryState,
)


class ProductionBatchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    production_batch_id: str = Field(min_length=1, max_length=160)
    production_date: str = Field(min_length=10, max_length=10)
    name: str = Field(min_length=1, max_length=240)
    payload: Dict[str, Any] = Field(default_factory=dict)


class RequirementCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirement_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1)
    payload: Dict[str, Any] = Field(default_factory=dict)


class RequirementDeliveryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    delivery_id: str = Field(min_length=1, max_length=200)
    state: RequirementDeliveryState = RequirementDeliveryState.PLANNED
    continuation_of_delivery_id: Optional[str] = Field(default=None, max_length=200)
    payload: Dict[str, Any] = Field(default_factory=dict)


class RequirementDeliveryStateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: RequirementDeliveryState


class RequirementDeliveryScopeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_id: str = Field(min_length=1, max_length=220)
    system_id: str = Field(min_length=1, max_length=240)
    system_version: str = Field(min_length=1, max_length=240)
    application_id: Optional[str] = Field(default=None, max_length=240)
    sst_id: str = Field(min_length=1, max_length=240)
    payload: Dict[str, Any] = Field(default_factory=dict)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _error(exc: Exception) -> HTTPException:
    detail = str(exc)
    if detail.endswith("_NOT_FOUND"):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    conflicts = {
        "PRODUCTION_BATCH_ALREADY_EXISTS",
        "REQUIREMENT_ALREADY_EXISTS",
        "REQUIREMENT_DELIVERY_ALREADY_EXISTS",
        "REQUIREMENT_ALREADY_PARTICIPATES_IN_BATCH",
        "DELIVERY_SCOPE_ALREADY_EXISTS",
        "DELIVERY_SCOPE_DUPLICATE",
        "REQUIREMENT_DELIVERY_TERMINAL_STATE_IMMUTABLE",
    }
    code = status.HTTP_409_CONFLICT if detail in conflicts else status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=detail)


def register_delivery_routes(app: FastAPI) -> None:
    def repository():
        value = getattr(app.state, "delivery_repository", None)
        if value is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="REQUIREMENT_DELIVERY_REPOSITORY_NOT_CONFIGURED")
        return value

    @app.post("/api/v1/production-batches", status_code=status.HTTP_201_CREATED)
    def create_production_batch(request: ProductionBatchCreate, response: Response) -> Dict[str, Any]:
        now = int(time.time())
        value = ProductionBatch(
            production_batch_id=request.production_batch_id,
            production_date=request.production_date,
            name=request.name,
            state=ProductionBatchState.PLANNED,
            created_at=now,
            payload=request.payload,
        )
        try:
            repository().create_batch(value)
        except ValueError as exc:
            raise _error(exc) from exc
        response.headers["Location"] = "/api/v1/production-batches/%s/plan" % value.production_batch_id
        return _jsonable(value)

    @app.get("/api/v1/production-batches")
    def list_production_batches() -> list[Dict[str, Any]]:
        return [_jsonable(value) for value in repository().list_batches()]

    @app.get("/api/v1/production-batches/{production_batch_id}/plan")
    def get_production_batch_plan(production_batch_id: str) -> Dict[str, Any]:
        try:
            return _jsonable(repository().batch_plan(production_batch_id))
        except ValueError as exc:
            raise _error(exc) from exc

    @app.post("/api/v1/requirements", status_code=status.HTTP_201_CREATED)
    def create_requirement(request: RequirementCreate, response: Response) -> Dict[str, Any]:
        value = Requirement(
            requirement_id=request.requirement_id,
            title=request.title,
            created_at=int(time.time()),
            payload=request.payload,
        )
        try:
            repository().create_requirement(value)
        except ValueError as exc:
            raise _error(exc) from exc
        response.headers["Location"] = "/api/v1/requirements/%s/deliveries" % value.requirement_id
        return _jsonable(value)

    @app.post(
        "/api/v1/production-batches/{production_batch_id}/requirements/{requirement_id}/deliveries",
        status_code=status.HTTP_201_CREATED,
    )
    def add_requirement_to_batch(
        production_batch_id: str,
        requirement_id: str,
        request: RequirementDeliveryCreate,
        response: Response,
    ) -> Dict[str, Any]:
        now = int(time.time())
        value = RequirementDelivery(
            delivery_id=request.delivery_id,
            production_batch_id=production_batch_id,
            requirement_id=requirement_id,
            state=request.state,
            continuation_of_delivery_id=request.continuation_of_delivery_id,
            created_at=now,
            updated_at=now,
            payload=request.payload,
        )
        try:
            repository().create_delivery(value)
        except ValueError as exc:
            raise _error(exc) from exc
        response.headers["Location"] = "/api/v1/requirement-deliveries/%s" % value.delivery_id
        return _jsonable(value)

    @app.patch("/api/v1/requirement-deliveries/{delivery_id}/state")
    def update_requirement_delivery_state(delivery_id: str, request: RequirementDeliveryStateUpdate) -> Dict[str, Any]:
        try:
            return _jsonable(repository().transition_delivery(delivery_id, request.state))
        except ValueError as exc:
            raise _error(exc) from exc

    @app.post("/api/v1/requirement-deliveries/{delivery_id}/scopes", status_code=status.HTTP_201_CREATED)
    def add_requirement_delivery_scope(
        delivery_id: str,
        request: RequirementDeliveryScopeCreate,
        response: Response,
    ) -> Dict[str, Any]:
        value = RequirementDeliveryScope(
            scope_id=request.scope_id,
            delivery_id=delivery_id,
            system_id=request.system_id,
            system_version=request.system_version,
            application_id=request.application_id,
            sst_id=request.sst_id,
            created_at=int(time.time()),
            payload=request.payload,
        )
        try:
            repository().create_scope(value)
        except ValueError as exc:
            raise _error(exc) from exc
        response.headers["Location"] = "/api/v1/requirement-deliveries/%s/scopes" % delivery_id
        return _jsonable(value)

    @app.get("/api/v1/requirements/{requirement_id}/deliveries")
    def get_requirement_delivery_history(requirement_id: str) -> Dict[str, Any]:
        try:
            history = repository().requirement_history(requirement_id)
        except ValueError as exc:
            raise _error(exc) from exc
        return {
            "requirement": _jsonable(history.requirement),
            "deliveries": [
                {
                    "delivery": _jsonable(delivery),
                    "scopes": [_jsonable(scope) for scope in history.scopes_by_delivery.get(delivery.delivery_id, [])],
                }
                for delivery in history.deliveries
            ],
            "completed_in_single_batch": history.completed_in_single_batch,
            "spans_multiple_batches": history.spans_multiple_batches,
            "current_delivery_state": history.current_delivery_state.value if history.current_delivery_state else None,
            "truth_note": "Requirement delivery history is preserved; no mandatory requirement revision object is inferred.",
        }
