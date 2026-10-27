"""Production N9 defect candidate/query and result-authority routes.

Candidate source identity comes only from the Center-authoritative N8 PRODUCT
route. Fix verification and impact regression accept only a WorkItem identity;
PASS/FAIL is derived from the canonical N7 result receipt, never from a caller
boolean or caller-supplied evidence.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from rc8_center.defect_closure import DefectClosureError


class DefectCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    defect_case_id: str = Field(min_length=1, max_length=240)
    route_decision_id: str = Field(min_length=1, max_length=240)
    evidence_refs: List[str] = Field(min_length=1)


class DefectValidationWorkItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    work_item_id: str = Field(min_length=1, max_length=200)


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


def register_defect_routes(app: FastAPI) -> None:
    def service():
        value = getattr(app.state, "defect_closure_service", None)
        if value is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="DEFECT_CLOSURE_SERVICE_NOT_CONFIGURED",
            )
        return value

    def repository():
        value = getattr(app.state, "defect_closure_repository", None)
        if value is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="DEFECT_CLOSURE_REPOSITORY_NOT_CONFIGURED",
            )
        return value

    @app.post("/api/v1/defects/candidates", status_code=status.HTTP_201_CREATED)
    def create_defect_candidate(request: DefectCandidateRequest) -> Dict[str, Any]:
        try:
            value = service().create_candidate(
                defect_case_id=request.defect_case_id,
                route_decision_id=request.route_decision_id,
                evidence_refs=request.evidence_refs,
            )
            return {
                "defect": _jsonable(value),
                "truth_note": "SOURCE_IDENTITY_DERIVED_FROM_CENTER_AUTHORITATIVE_N8_PRODUCT_ROUTE",
            }
        except DefectClosureError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    @app.post("/api/v1/defects/{defect_case_id}/verify-fix")
    def verify_defect_fix(
        defect_case_id: str,
        request: DefectValidationWorkItemRequest,
    ) -> Dict[str, Any]:
        try:
            value = service().verify_fix(
                defect_case_id,
                verification_work_item_id=request.work_item_id,
            )
            return {
                "defect": _jsonable(value),
                "truth_note": "FIX_RESULT_DERIVED_FROM_CENTER_N7_R1_RECEIPT_NOT_CALLER_BOOLEAN",
            }
        except DefectClosureError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    @app.post("/api/v1/defects/{defect_case_id}/impact-regression")
    def record_impact_regression(
        defect_case_id: str,
        request: DefectValidationWorkItemRequest,
    ) -> Dict[str, Any]:
        try:
            value = service().record_impact_regression(
                defect_case_id,
                regression_work_item_id=request.work_item_id,
            )
            return {
                "defect": _jsonable(value),
                "truth_note": "REGRESSION_RESULT_DERIVED_FROM_CENTER_N7_R1_RECEIPT_NOT_CALLER_BOOLEAN",
            }
        except DefectClosureError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    @app.get("/api/v1/defects/{defect_case_id}")
    def get_defect_case(defect_case_id: str) -> Dict[str, Any]:
        value = repository().get_defect_case(defect_case_id)
        if value is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="DEFECT_CASE_NOT_FOUND")
        return {
            "defect": _jsonable(value),
            "truth_note": "POSTGRESQL_DEFECT_CLOSURE_PROJECTION",
        }
