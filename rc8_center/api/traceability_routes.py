"""Business-facing read routes for requirement/page/API/code/table traceability."""
from __future__ import annotations

from enum import Enum
from typing import Any

from fastapi import FastAPI, HTTPException, Query, status

from rc8_center.traceability import TraceNodeType, TraceabilityError
from rc8_center.traceability_query import TraceabilityQueryService


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _http_error(exc: Exception) -> HTTPException:
    detail = str(exc)
    not_found = {
        "TRACE_GRAPH_NOT_FOUND",
        "TRACE_QUERY_SUBJECT_NOT_FOUND",
        "TRACE_EDGE_NOT_FOUND",
    }
    code = status.HTTP_404_NOT_FOUND if detail in not_found else status.HTTP_409_CONFLICT
    return HTTPException(status_code=code, detail=detail)


def register_traceability_routes(app: FastAPI) -> None:
    def service() -> TraceabilityQueryService:
        value = getattr(app.state, "traceability_query_service", None)
        if value is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TRACEABILITY_QUERY_NOT_CONFIGURED",
            )
        return value

    @app.get("/api/v1/test-runs/{test_run_id}/traceability-graphs")
    def list_test_run_graphs(test_run_id: str):
        return {"graphs": _jsonable(service().list_for_test_run(test_run_id))}

    @app.get("/api/v1/test-rounds/{test_round_id}/traceability-graphs")
    def list_test_round_graphs(test_round_id: str):
        return {"graphs": _jsonable(service().list_for_test_round(test_round_id))}

    @app.get("/api/v1/traceability-graphs/{graph_id}/impact")
    def query_impact(
        graph_id: str,
        node_type: TraceNodeType = Query(...),
        business_key: str = Query(..., min_length=1, max_length=1000),
        direction: str = Query(default="both", pattern="^(forward|reverse|both)$"),
        max_depth: int = Query(default=8, ge=0, le=32),
    ):
        try:
            return _jsonable(
                service().impact(
                    graph_id,
                    node_type=node_type,
                    business_key=business_key,
                    direction=direction,
                    max_depth=max_depth,
                )
            )
        except (TraceabilityError, ValueError) as exc:
            raise _http_error(exc) from exc

    @app.get("/api/v1/traceability-graphs/{graph_id}/edges/{edge_id}/evidence")
    def list_edge_evidence(graph_id: str, edge_id: str):
        try:
            return {"evidence": _jsonable(service().evidence(graph_id, edge_id))}
        except (TraceabilityError, ValueError) as exc:
            raise _http_error(exc) from exc
