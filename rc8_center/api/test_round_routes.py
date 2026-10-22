"""FastAPI routes for multi-round testing inside one production date."""
from __future__ import annotations

import hashlib
import time
from dataclasses import asdict
from enum import Enum
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field

from rc8_center.test_rounds import TestRound, TestRoundDelivery, TestRoundState


class TestRoundCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    test_round_id: str = Field(min_length=1, max_length=200)
    name: str = Field(default="", max_length=240)
    delivery_ids: List[str] = Field(default_factory=list)
    payload: Dict[str, Any] = Field(default_factory=dict)


class TestRoundDeliveryInclude(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload: Dict[str, Any] = Field(default_factory=dict)


class TestRoundStateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: TestRoundState


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


def _error(exc: Exception) -> HTTPException:
    detail = str(exc)
    if detail.endswith("_NOT_FOUND"):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    conflicts = {
        "TEST_ROUND_ALREADY_EXISTS",
        "TEST_ROUND_NO_ALREADY_EXISTS_IN_PRODUCTION_DATE",
        "TEST_ROUND_DELIVERY_ALREADY_EXISTS",
        "REQUIREMENT_DELIVERY_ALREADY_IN_TEST_ROUND",
        "TEST_ROUND_DELIVERY_PRODUCTION_DATE_MISMATCH",
        "TEST_ROUND_TERMINAL_STATE_IMMUTABLE",
    }
    code = status.HTTP_409_CONFLICT if detail in conflicts else status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=detail)


def register_test_round_routes(app: FastAPI) -> None:
    def repository():
        value = getattr(app.state, "test_round_repository", None)
        if value is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TEST_ROUND_REPOSITORY_NOT_CONFIGURED",
            )
        return value

    def require_round_in_batch(production_batch_id: str, test_round_id: str) -> TestRound:
        value = repository().get_round(test_round_id)
        if value is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="TEST_ROUND_NOT_FOUND")
        if value.production_batch_id != production_batch_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="TEST_ROUND_PRODUCTION_DATE_MISMATCH",
            )
        return value

    @app.get("/api/v1/production-batches/{production_batch_id}/test-rounds")
    def list_test_rounds(production_batch_id: str) -> List[Dict[str, Any]]:
        values = repository().list_rounds(production_batch_id)
        return [
            {
                "round": _jsonable(value),
                "deliveries": [
                    _jsonable(item) for item in repository().list_round_deliveries(value.test_round_id)
                ],
                "truth_note": "TestRound is a testing round inside this production date; it is not another production batch or requirement iteration.",
            }
            for value in values
        ]

    @app.post(
        "/api/v1/production-batches/{production_batch_id}/test-rounds",
        status_code=status.HTTP_201_CREATED,
    )
    def create_test_round(
        production_batch_id: str,
        request: TestRoundCreate,
        response: Response,
    ) -> Dict[str, Any]:
        repo = repository()
        now = int(time.time())
        try:
            value = TestRound(
                test_round_id=request.test_round_id,
                production_batch_id=production_batch_id,
                round_no=repo.next_round_no(production_batch_id),
                name=request.name,
                state=TestRoundState.PLANNED,
                created_at=now,
                payload=request.payload,
            )
            repo.create_round(value)
            included = []
            for delivery_id in request.delivery_ids:
                link = TestRoundDelivery(
                    round_delivery_id=_round_delivery_id(value.test_round_id, delivery_id),
                    test_round_id=value.test_round_id,
                    delivery_id=delivery_id,
                    included_at=now,
                )
                included.append(repo.include_delivery(link))
        except ValueError as exc:
            raise _error(exc) from exc
        response.headers["Location"] = (
            "/api/v1/production-batches/%s/test-rounds/%s" % (production_batch_id, value.test_round_id)
        )
        return {
            "round": _jsonable(value),
            "deliveries": [_jsonable(item) for item in included],
            "truth_note": "Creating another TestRound does not create another production batch or requirement delivery.",
        }

    @app.get("/api/v1/production-batches/{production_batch_id}/test-rounds/{test_round_id}")
    def get_test_round(production_batch_id: str, test_round_id: str) -> Dict[str, Any]:
        value = require_round_in_batch(production_batch_id, test_round_id)
        return {
            "round": _jsonable(value),
            "deliveries": [
                _jsonable(item) for item in repository().list_round_deliveries(test_round_id)
            ],
        }

    @app.post(
        "/api/v1/production-batches/{production_batch_id}/test-rounds/{test_round_id}/deliveries/{delivery_id}",
        status_code=status.HTTP_201_CREATED,
    )
    def include_delivery(
        production_batch_id: str,
        test_round_id: str,
        delivery_id: str,
        request: TestRoundDeliveryInclude,
    ) -> Dict[str, Any]:
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

    @app.patch(
        "/api/v1/production-batches/{production_batch_id}/test-rounds/{test_round_id}/state"
    )
    def update_test_round_state(
        production_batch_id: str,
        test_round_id: str,
        request: TestRoundStateUpdate,
    ) -> Dict[str, Any]:
        require_round_in_batch(production_batch_id, test_round_id)
        try:
            value = repository().transition_round(test_round_id, request.state)
        except ValueError as exc:
            raise _error(exc) from exc
        return {
            "round": _jsonable(value),
            "truth_note": "TestRound state is independent from RequirementDelivery state; completing a round never completes a requirement implicitly.",
        }
