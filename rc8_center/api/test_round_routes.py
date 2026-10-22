"""FastAPI routes for multi-round testing inside one production date."""
from __future__ import annotations

import hashlib
import time
from dataclasses import asdict
from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field

from rc8_center.test_rounds import TestRound, TestRoundDelivery, TestRoundState


class TestRoundCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    test_round_id: Optional[str] = Field(default=None, min_length=1, max_length=200)
    name: str = Field(default="", max_length=240)
    delivery_ids: List[str] = Field(default_factory=list)
    payload: Dict[str, Any] = Field(default_factory=dict)


class TestRoundDeliveryInclude(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payload: Dict[str, Any] = Field(default_factory=dict)


class TestRoundStateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: TestRoundState


class TestRoundTestRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    test_run_id: Optional[str] = Field(default=None, min_length=1, max_length=160)
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


def _round_delivery_id(test_round_id: str, delivery_id: str) -> str:
    digest = hashlib.sha256((test_round_id + "\x1f" + delivery_id).encode("utf-8")).hexdigest()
    return "round-delivery-" + digest


def _default_test_run_id(test_round_id: str) -> str:
    readable = "%s-run" % test_round_id
    if len(readable) <= 160:
        return readable
    digest = hashlib.sha256(test_round_id.encode("utf-8")).hexdigest()[:32]
    return "test-run-%s" % digest


def _test_run_json(row: Any) -> Dict[str, Any]:
    return {
        "test_run_id": str(row.test_run_id),
        "production_batch_id": str(row.production_batch_id) if row.production_batch_id is not None else None,
        "test_round_id": str(row.test_round_id) if row.test_round_id is not None else None,
        "status_scope": str(row.status_scope),
        "current_state": str(row.current_state),
        "created_at": int(row.created_at),
        "updated_at": int(row.updated_at),
        "payload": dict(row.payload or {}),
    }


def _error(exc: Exception) -> HTTPException:
    detail = str(exc)
    if detail.endswith("_NOT_FOUND"):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    conflicts = {
        "TEST_ROUND_ALREADY_EXISTS",
        "TEST_ROUND_NO_ALREADY_EXISTS_IN_PRODUCTION_DATE",
        "TEST_ROUND_DELIVERY_ALREADY_EXISTS",
        "TEST_ROUND_DELIVERY_ROUND_MISMATCH",
        "REQUIREMENT_DELIVERY_ALREADY_IN_TEST_ROUND",
        "TEST_ROUND_DELIVERY_PRODUCTION_DATE_MISMATCH",
        "TEST_ROUND_PRODUCTION_DATE_MISMATCH",
        "TEST_ROUND_TERMINAL_STATE_IMMUTABLE",
        "TEST_ROUND_NOT_STARTABLE",
        "TEST_ROUND_HAS_NO_REQUIREMENTS",
        "TEST_ROUND_SCOPE_INCOMPLETE",
        "TEST_ROUND_SCOPE_FROZEN_AFTER_START",
        "TEST_ROUND_ALREADY_HAS_TEST_RUN",
        "TEST_RUN_ALREADY_EXISTS",
    }
    code = status.HTTP_409_CONFLICT if detail in conflicts else status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=detail)


def register_test_round_routes(app: FastAPI) -> None:
    def repository():
        value = getattr(app.state, "test_round_repository", None)
        if value is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="TEST_ROUND_REPOSITORY_NOT_CONFIGURED")
        return value

    def revisions():
        value = getattr(app.state, "revision_repository", None)
        if value is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="REQUIREMENT_REVISION_REPOSITORY_NOT_CONFIGURED")
        return value

    def deliveries():
        value = getattr(app.state, "delivery_repository", None)
        if value is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="REQUIREMENT_DELIVERY_REPOSITORY_NOT_CONFIGURED")
        return value

    def postgres():
        value = getattr(app.state, "postgres", None)
        if value is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="POSTGRES_NOT_CONFIGURED")
        return value

    def require_round_in_batch(production_batch_id: str, test_round_id: str) -> TestRound:
        value = repository().get_round(test_round_id)
        if value is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="TEST_ROUND_NOT_FOUND")
        if value.production_batch_id != production_batch_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="TEST_ROUND_PRODUCTION_DATE_MISMATCH")
        return value

    def frozen_revision_snapshot(test_round_id: str) -> List[Dict[str, Any]]:
        snapshot: List[Dict[str, Any]] = []
        for link in repository().list_round_deliveries(test_round_id):
            binding = revisions().ensure_delivery_binding(link.delivery_id)
            technical_scopes = deliveries().list_scopes(link.delivery_id)
            snapshot.append(
                {
                    "delivery_id": link.delivery_id,
                    "requirement_revision_id": binding.requirement_revision_id,
                    "scope_revision_id": binding.scope_revision_id,
                    "delivery_scope_ids": [item.scope_id for item in technical_scopes],
                }
            )
        return snapshot

    @app.get("/api/v1/production-batches/{production_batch_id}/test-rounds")
    def list_test_rounds(production_batch_id: str) -> List[Dict[str, Any]]:
        values = repository().list_rounds(production_batch_id)
        store = postgres()
        result: List[Dict[str, Any]] = []
        for value in values:
            run = store.get_test_run_for_round(value.test_round_id)
            result.append({
                "round": _jsonable(value),
                "deliveries": [_jsonable(item) for item in repository().list_round_deliveries(value.test_round_id)],
                "test_run": _test_run_json(run) if run is not None else None,
                "truth_note": "TestRound is a testing round inside this production date; it is not another production batch or requirement iteration.",
            })
        return result

    @app.post("/api/v1/production-batches/{production_batch_id}/test-rounds", status_code=status.HTTP_201_CREATED)
    def create_test_round(production_batch_id: str, request: TestRoundCreate, response: Response) -> Dict[str, Any]:
        try:
            value, included = repository().create_next_round(
                production_batch_id,
                request.delivery_ids,
                requested_test_round_id=request.test_round_id,
                name=request.name,
                payload=request.payload,
            )
        except ValueError as exc:
            raise _error(exc) from exc
        response.headers["Location"] = "/api/v1/production-batches/%s/test-rounds/%s" % (production_batch_id, value.test_round_id)
        return {
            "round": _jsonable(value),
            "deliveries": [_jsonable(item) for item in included],
            "truth_note": "Creating another TestRound does not create another production batch or requirement revision.",
        }

    @app.get("/api/v1/production-batches/{production_batch_id}/test-rounds/{test_round_id}")
    def get_test_round(production_batch_id: str, test_round_id: str) -> Dict[str, Any]:
        value = require_round_in_batch(production_batch_id, test_round_id)
        run = postgres().get_test_run_for_round(test_round_id)
        return {
            "round": _jsonable(value),
            "deliveries": [_jsonable(item) for item in repository().list_round_deliveries(test_round_id)],
            "test_run": _test_run_json(run) if run is not None else None,
        }

    @app.post(
        "/api/v1/production-batches/{production_batch_id}/test-rounds/{test_round_id}/deliveries/{delivery_id}",
        status_code=status.HTTP_201_CREATED,
    )
    def include_delivery(production_batch_id: str, test_round_id: str, delivery_id: str, request: TestRoundDeliveryInclude) -> Dict[str, Any]:
        require_round_in_batch(production_batch_id, test_round_id)
        try:
            value = repository().include_delivery(
                TestRoundDelivery(
                    round_delivery_id=_round_delivery_id(test_round_id, delivery_id),
                    test_round_id=test_round_id,
                    delivery_id=delivery_id,
                    included_at=int(time.time()),
                    payload=request.payload,
                )
            )
        except ValueError as exc:
            raise _error(exc) from exc
        return _jsonable(value)

    @app.post(
        "/api/v1/production-batches/{production_batch_id}/test-rounds/{test_round_id}/test-run",
        status_code=status.HTTP_201_CREATED,
    )
    def start_test_run_from_round(
        production_batch_id: str,
        test_round_id: str,
        request: TestRoundTestRunCreate,
        response: Response,
    ) -> Dict[str, Any]:
        require_round_in_batch(production_batch_id, test_round_id)
        test_run_id = request.test_run_id or _default_test_run_id(test_round_id)
        try:
            snapshot = frozen_revision_snapshot(test_round_id)
            run_payload = dict(request.payload)
            run_payload.update(
                {
                    "delivery_revision_bindings": snapshot,
                    "requirement_revision_ids": sorted({item["requirement_revision_id"] for item in snapshot}),
                    "scope_revision_ids": sorted({item["scope_revision_id"] for item in snapshot}),
                    "revision_snapshot_truth": "FROZEN_AT_TEST_ROUND_START",
                }
            )
            round_value, row = repository().start_runtime_mission(
                test_round_id,
                test_run_id,
                payload=run_payload,
            )
        except ValueError as exc:
            raise _error(exc) from exc

        response.headers["Location"] = "/api/v1/test-runs/%s" % row.test_run_id
        return {
            "test_run": _test_run_json(row),
            "round": _jsonable(round_value),
            "truth_note": "TestRun freezes RequirementRevision and ScopeRevision identities; later requirement changes cannot rewrite this run's analysis/evidence scope.",
        }

    @app.get("/api/v1/production-batches/{production_batch_id}/test-rounds/{test_round_id}/test-run")
    def get_test_run_for_round(production_batch_id: str, test_round_id: str) -> Dict[str, Any]:
        require_round_in_batch(production_batch_id, test_round_id)
        row = postgres().get_test_run_for_round(test_round_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="TEST_RUN_NOT_FOUND")
        return _test_run_json(row)

    @app.patch("/api/v1/production-batches/{production_batch_id}/test-rounds/{test_round_id}/state")
    def update_test_round_state(production_batch_id: str, test_round_id: str, request: TestRoundStateUpdate) -> Dict[str, Any]:
        require_round_in_batch(production_batch_id, test_round_id)
        try:
            value = repository().transition_round(test_round_id, request.state)
        except ValueError as exc:
            raise _error(exc) from exc
        return {
            "round": _jsonable(value),
            "truth_note": "TestRound state is independent from RequirementDelivery state; completing a round never completes a requirement implicitly.",
        }
