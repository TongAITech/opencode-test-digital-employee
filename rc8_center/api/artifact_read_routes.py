"""Lease-authorized JSON evidence reads for successor WorkItems.

A successor worker may read an AVAILABLE predecessor artifact only when:
- it currently owns an active WorkItem lease in the same TestRun; and
- the artifact ref is explicitly present in that WorkItem's immutable scope refs.

This keeps analysis/sufficiency workers from browsing arbitrary run artifacts.
"""
from __future__ import annotations

import json
from typing import Any, Dict

from fastapi import FastAPI, Header, HTTPException, Query, status

from rc8_runtime import ArtifactAvailability


MAX_JSON_EVIDENCE_BYTES = 4 * 1024 * 1024


def register_artifact_read_routes(app: FastAPI) -> None:
    @app.get("/api/v1/artifacts/{artifact_id}/json")
    def read_artifact_json(
        artifact_id: str,
        work_item_id: str = Query(min_length=1),
        x_rc8_node_id: str = Header(alias="X-RC8-Node-Id", min_length=1),
        x_rc8_lease_id: str = Header(alias="X-RC8-Lease-Id", min_length=1),
    ) -> Dict[str, Any]:
        store = getattr(app.state, "artifact_store", None)
        control = getattr(app.state, "formal_control", None)
        if store is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="ARTIFACT_STORE_NOT_CONFIGURED")
        if control is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="FORMAL_CONTROL_NOT_CONFIGURED")

        manifest = store.repository.get(artifact_id)
        if manifest is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ARTIFACT_NOT_FOUND")
        if manifest.availability != ArtifactAvailability.AVAILABLE:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="ARTIFACT_NOT_AVAILABLE")
        try:
            work = control.authorize_work_item_write(
                test_run_id=manifest.test_run_id,
                work_item_id=work_item_id,
                node_id=x_rc8_node_id,
                lease_id=x_rc8_lease_id,
            )
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

        allowed_refs = {str(value).strip() for value in work.identity.scope_refs if str(value).strip()}
        if "artifact:%s" % artifact_id not in allowed_refs and artifact_id not in allowed_refs:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ARTIFACT_NOT_REFERENCED_BY_WORK_ITEM",
            )
        try:
            path = store.content_path(artifact_id)
            if path.stat().st_size > MAX_JSON_EVIDENCE_BYTES:
                raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="ARTIFACT_JSON_TOO_LARGE")
            raw = path.read_text(encoding="utf-8")
            value = json.loads(raw)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="ARTIFACT_JSON_INVALID") from exc
        if not isinstance(value, dict):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="ARTIFACT_JSON_OBJECT_REQUIRED")
        return {
            "artifact_id": artifact_id,
            "manifest": {
                "test_run_id": manifest.test_run_id,
                "work_item_id": manifest.work_item_id,
                "kind": manifest.kind,
                "sha256": manifest.sha256,
                "size_bytes": manifest.size_bytes,
                "availability": manifest.availability.value,
            },
            "content": value,
            "truth_note": "LEASE_AUTHORIZED_EXPLICIT_PREDECESSOR_EVIDENCE_READ",
        }
