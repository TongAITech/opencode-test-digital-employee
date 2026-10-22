"""Read-only R1 sequence cursor for restart-safe formal Node workers."""
from __future__ import annotations

from typing import Dict

from fastapi import FastAPI, HTTPException, status


def register_runtime_sequence_routes(app: FastAPI) -> None:
    @app.get("/api/v1/test-runs/{test_run_id}/nodes/{node_id}/runtime-sequence")
    def runtime_sequence(test_run_id: str, node_id: str) -> Dict[str, int]:
        ledger = getattr(app.state, "r1_ledger", None)
        if ledger is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="R1_RUNTIME_LEDGER_NOT_CONFIGURED",
            )
        latest = int(ledger.latest_node_sequence(test_run_id=test_run_id, node_id=node_id))
        return {
            "latest_sequence": latest,
            "next_sequence": latest + 1,
        }
