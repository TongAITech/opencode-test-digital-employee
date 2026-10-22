"""Formal FastAPI adapter for RC8 Center.

FastAPI is intentionally a thin edge. Domain truth remains in existing Center
services/R1 projector and the formal PostgreSQL/Redis infrastructure adapters.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field

from rc8_center.formal_settings import CenterSettings
from rc8_center.infrastructure import PostgresStore, RedisCoordination


class TestRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    test_run_id: str = Field(min_length=1, max_length=160)
    production_batch_id: Optional[str] = Field(default=None, max_length=160)
    payload: Dict[str, Any] = Field(default_factory=dict)


class TestRunView(BaseModel):
    test_run_id: str
    production_batch_id: Optional[str] = None
    status_scope: str
    current_state: str
    created_at: int
    updated_at: int
    payload: Dict[str, Any] = Field(default_factory=dict)


class HealthView(BaseModel):
    status: str
    service: str
    database: str
    redis: str
    runtime_truth: str


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


def _test_run_view(row: Any) -> TestRunView:
    return TestRunView(
        test_run_id=str(row.test_run_id),
        production_batch_id=str(row.production_batch_id) if row.production_batch_id is not None else None,
        status_scope=str(row.status_scope),
        current_state=str(row.current_state),
        created_at=int(row.created_at),
        updated_at=int(row.updated_at),
        payload=dict(row.payload or {}),
    )


def create_app(
    *,
    settings: Optional[CenterSettings] = None,
    postgres: Optional[PostgresStore] = None,
    redis_coordination: Optional[RedisCoordination] = None,
    governance_projection: Optional[object] = None,
    product_application: Optional[object] = None,
) -> FastAPI:
    """Create the formal Center FastAPI application.

    Dependencies are injectable so domain/projection behavior can be exercised in
    contract tests without hiding network/database side effects in route code.
    `product_application` is transitional compatibility for the W-A stdlib
    product adapter; the formal path is `governance_projection` backed by
    PostgreSQL.
    """

    cfg = settings or CenterSettings()
    app = FastAPI(
        title="RC8 Center API",
        version="8",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.state.settings = cfg
    app.state.postgres = postgres
    app.state.redis_coordination = redis_coordination
    app.state.governance_projection = governance_projection
    app.state.product_application = product_application

    @app.get("/health", response_model=HealthView)
    def health() -> HealthView:
        db_status = "NOT_CONFIGURED"
        redis_status = "NOT_CONFIGURED"
        if app.state.postgres is not None:
            try:
                db_status = "READY" if app.state.postgres.ping() else "NOT_READY"
            except Exception:
                db_status = "NOT_READY"
        if app.state.redis_coordination is not None:
            try:
                redis_status = "READY" if app.state.redis_coordination.ping() else "NOT_READY"
            except Exception:
                redis_status = "NOT_READY"
        overall = "READY" if db_status == "READY" and redis_status == "READY" else "DEGRADED"
        return HealthView(
            status=overall,
            service="RC8_CENTER_FASTAPI",
            database=db_status,
            redis=redis_status,
            runtime_truth="R1_EVENT_STREAM",
        )

    @app.get("/api/v1/system/architecture")
    def architecture() -> Dict[str, Any]:
        return {
            "status": "FROZEN",
            "technology": cfg.architecture(),
            "truth_rules": {
                "runtime_truth": "R1_EVENT_STREAM",
                "redis_authoritative": False,
                "ui_may_infer_pass": False,
                "stdlib_http_role": "MINIMAL_PROTOCOL_TEST_ADAPTER_ONLY",
            },
        }

    @app.get("/api/v1/test-runs", response_model=list[TestRunView])
    def list_test_runs() -> list[TestRunView]:
        store: Optional[PostgresStore] = app.state.postgres
        if store is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="POSTGRES_NOT_CONFIGURED")
        return [_test_run_view(row) for row in store.list_test_runs()]

    @app.post("/api/v1/test-runs", response_model=TestRunView, status_code=status.HTTP_201_CREATED)
    def create_test_run(request: TestRunCreate, response: Response) -> TestRunView:
        store: Optional[PostgresStore] = app.state.postgres
        if store is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="POSTGRES_NOT_CONFIGURED")
        if store.get_test_run(request.test_run_id) is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="TEST_RUN_ALREADY_EXISTS")
        row = store.create_test_run(
            request.test_run_id,
            production_batch_id=request.production_batch_id,
            payload=request.payload,
        )
        response.headers["Location"] = "/api/v1/test-runs/%s" % request.test_run_id
        return _test_run_view(row)

    @app.get("/api/v1/test-runs/{test_run_id}", response_model=TestRunView)
    def get_test_run(test_run_id: str) -> TestRunView:
        store: Optional[PostgresStore] = app.state.postgres
        if store is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="POSTGRES_NOT_CONFIGURED")
        row = store.get_test_run(test_run_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="TEST_RUN_NOT_FOUND")
        return _test_run_view(row)

    @app.get("/api/v1/test-runs/{test_run_id}/governance")
    def get_governance(test_run_id: str) -> Dict[str, Any]:
        projection = app.state.governance_projection
        if projection is not None:
            try:
                return _jsonable(projection.test_run(test_run_id))
            except Exception as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        product = app.state.product_application
        if product is not None:
            try:
                return _jsonable(product.get("/api/v1/test-runs/%s/governance" % test_run_id))
            except Exception as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GOVERNANCE_PROJECTION_NOT_CONFIGURED",
        )

    return app
