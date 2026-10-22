"""FastAPI routes for first-class RequirementRevision and ScopeRevision."""
from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field

from rc8_center.revisions import RequirementRevision, ScopeRevision


class RequirementRevisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirement_revision_id: str = Field(min_length=1, max_length=240)
    revision_label: str = Field(min_length=1, max_length=80)
    parent_requirement_revision_id: Optional[str] = Field(default=None, max_length=240)
    payload: Dict[str, Any] = Field(default_factory=dict)


class ScopeRevisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_revision_id: str = Field(min_length=1, max_length=240)
    revision_label: str = Field(min_length=1, max_length=80)
    parent_scope_revision_id: Optional[str] = Field(default=None, max_length=240)
    payload: Dict[str, Any] = Field(default_factory=dict)


def _jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _error(exc: Exception) -> HTTPException:
    detail = str(exc)
    if detail.endswith("_NOT_FOUND"):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    conflict_tokens = (
        "ALREADY_EXISTS",
        "IMMUTABLE",
        "MISMATCH",
        "LINEAGE_MISMATCH",
    )
    code = status.HTTP_409_CONFLICT if detail.endswith(conflict_tokens) else status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=detail)


def register_revision_routes(app: FastAPI) -> None:
    def repository():
        value = getattr(app.state, "revision_repository", None)
        if value is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="REQUIREMENT_REVISION_REPOSITORY_NOT_CONFIGURED",
            )
        return value

    @app.post(
        "/api/v1/requirements/{requirement_id}/revisions",
        status_code=status.HTTP_201_CREATED,
    )
    def create_requirement_revision(
        requirement_id: str,
        request: RequirementRevisionCreate,
        response: Response,
    ) -> Dict[str, Any]:
        value = RequirementRevision(
            requirement_revision_id=request.requirement_revision_id,
            requirement_id=requirement_id,
            revision_label=request.revision_label,
            parent_requirement_revision_id=request.parent_requirement_revision_id,
            created_at=int(time.time()),
            payload=request.payload,
        )
        try:
            repository().create_requirement_revision(value)
        except ValueError as exc:
            raise _error(exc) from exc
        response.headers["Location"] = (
            "/api/v1/requirement-revisions/%s" % value.requirement_revision_id
        )
        return _jsonable(value)

    @app.get("/api/v1/requirements/{requirement_id}/revisions")
    def list_requirement_revisions(requirement_id: str) -> list[Dict[str, Any]]:
        return [_jsonable(value) for value in repository().list_requirement_revisions(requirement_id)]

    @app.get("/api/v1/requirement-revisions/{requirement_revision_id}")
    def get_requirement_revision(requirement_revision_id: str) -> Dict[str, Any]:
        value = repository().get_requirement_revision(requirement_revision_id)
        if value is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="REQUIREMENT_REVISION_NOT_FOUND")
        return _jsonable(value)

    @app.post(
        "/api/v1/requirement-revisions/{requirement_revision_id}/scope-revisions",
        status_code=status.HTTP_201_CREATED,
    )
    def create_scope_revision(
        requirement_revision_id: str,
        request: ScopeRevisionCreate,
        response: Response,
    ) -> Dict[str, Any]:
        value = ScopeRevision(
            scope_revision_id=request.scope_revision_id,
            requirement_revision_id=requirement_revision_id,
            revision_label=request.revision_label,
            parent_scope_revision_id=request.parent_scope_revision_id,
            created_at=int(time.time()),
            payload=request.payload,
        )
        try:
            repository().create_scope_revision(value)
        except ValueError as exc:
            raise _error(exc) from exc
        response.headers["Location"] = "/api/v1/scope-revisions/%s" % value.scope_revision_id
        return _jsonable(value)

    @app.get("/api/v1/requirement-revisions/{requirement_revision_id}/scope-revisions")
    def list_scope_revisions(requirement_revision_id: str) -> list[Dict[str, Any]]:
        return [_jsonable(value) for value in repository().list_scope_revisions(requirement_revision_id)]

    @app.get("/api/v1/scope-revisions/{scope_revision_id}")
    def get_scope_revision(scope_revision_id: str) -> Dict[str, Any]:
        value = repository().get_scope_revision(scope_revision_id)
        if value is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SCOPE_REVISION_NOT_FOUND")
        return _jsonable(value)
