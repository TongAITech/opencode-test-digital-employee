#!/usr/bin/env python3
"""Run the existing formal Center integration through the TestRound-first entry.

The legacy integration body contains hundreds of assertions for PostgreSQL,
Redis lease truth, R1 ordering, governance projection, evidence gating and
recovery.  We deliberately preserve those assertions.  This adapter only
translates its one historical product mission creation call into the current
business contract:

ProductionBatch -> RequirementDelivery + Scope -> TestRound -> TestRun.

No production endpoint is relaxed and no assertion is skipped.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx
from fastapi.testclient import TestClient

from rc8_center.infrastructure import (
    PostgresRequirementDeliveryRepository,
    PostgresTestRoundRepository,
)


_ORIGINAL_INIT = TestClient.__init__
_ORIGINAL_POST = TestClient.post


def _patched_init(self: TestClient, app: Any, *args: Any, **kwargs: Any) -> None:
    _ORIGINAL_INIT(self, app, *args, **kwargs)
    store = getattr(app.state, "postgres", None)
    if store is None:
        return
    # Routes are already registered by rc8_center.api.create_app.  The legacy
    # integration factory simply predates repository injection, so supply the
    # same formal PostgreSQL repositories used by rc8_center.formal_app.
    if getattr(app.state, "delivery_repository", None) is None:
        app.state.delivery_repository = PostgresRequirementDeliveryRepository(store)
    if getattr(app.state, "test_round_repository", None) is None:
        app.state.test_round_repository = PostgresTestRoundRepository(store)


def _post_raw(client: TestClient, url: str, payload: dict) -> httpx.Response:
    return _ORIGINAL_POST(client, url, json=payload)


def _round_first_create(client: TestClient, payload: dict) -> httpx.Response:
    run_id = str(payload["test_run_id"])
    batch_id = str(payload["production_batch_id"])
    requirement_id = "REQ-%s" % run_id
    delivery_id = "DEL-%s" % run_id
    scope_id = "SCOPE-%s" % run_id

    created_batch = _post_raw(
        client,
        "/api/v1/production-batches",
        {
            "production_batch_id": batch_id,
            "production_date": "2026-11-15",
            "name": "Formal Center integration production date",
            "payload": {"source": "FORMAL_CENTER_INTEGRATION"},
        },
    )
    assert created_batch.status_code == 201, created_batch.text

    created_requirement = _post_raw(
        client,
        "/api/v1/requirements",
        {
            "requirement_id": requirement_id,
            "title": "Formal Center integration requirement",
            "payload": {"source": "FORMAL_CENTER_INTEGRATION"},
        },
    )
    assert created_requirement.status_code == 201, created_requirement.text

    created_delivery = _post_raw(
        client,
        "/api/v1/production-batches/%s/requirements/%s/deliveries" % (batch_id, requirement_id),
        {"delivery_id": delivery_id, "state": "PLANNED"},
    )
    assert created_delivery.status_code == 201, created_delivery.text

    created_scope = _post_raw(
        client,
        "/api/v1/requirement-deliveries/%s/scopes" % delivery_id,
        {
            "scope_id": scope_id,
            "system_id": "PFC-FORMAL-IT",
            "system_version": "integration-snapshot",
            "application_id": "cfg-center",
            "sst_id": "SST-IT",
        },
    )
    assert created_scope.status_code == 201, created_scope.text

    created_round = _post_raw(
        client,
        "/api/v1/production-batches/%s/test-rounds" % batch_id,
        {
            "delivery_ids": [delivery_id],
            "payload": {"source": "FORMAL_CENTER_INTEGRATION"},
        },
    )
    assert created_round.status_code == 201, created_round.text
    round_body = created_round.json()["round"]
    round_id = str(round_body["test_round_id"])
    assert int(round_body["round_no"]) == 1

    started = _post_raw(
        client,
        "/api/v1/production-batches/%s/test-rounds/%s/test-run" % (batch_id, round_id),
        {
            "test_run_id": run_id,
            "payload": dict(payload.get("payload") or {}),
        },
    )
    assert started.status_code == 201, started.text
    started_body = started.json()
    run_body = started_body["test_run"]
    assert run_body["production_batch_id"] == batch_id
    assert run_body["test_round_id"] == round_id
    assert run_body["payload"]["requirement_delivery_ids"] == [delivery_id]
    assert run_body["payload"]["delivery_scope_ids"] == [scope_id]
    assert started_body["round"]["state"] == "ACTIVE"

    # Return the same outer shape the legacy integration body expected from the
    # old direct TestRun endpoint while the real request above used the new API.
    return httpx.Response(
        status_code=started.status_code,
        headers=dict(started.headers),
        json=run_body,
        request=started.request,
    )


def _patched_post(self: TestClient, url: Any, *args: Any, **kwargs: Any) -> httpx.Response:
    payload = kwargs.get("json")
    if (
        str(url) == "/api/v1/test-runs"
        and isinstance(payload, dict)
        and payload.get("production_batch_id") == "PB-IT"
        and (payload.get("payload") or {}).get("scope") == "formal-center-integration"
    ):
        return _round_first_create(self, payload)
    return _ORIGINAL_POST(self, url, *args, **kwargs)


def main() -> int:
    TestClient.__init__ = _patched_init  # type: ignore[method-assign]
    TestClient.post = _patched_post  # type: ignore[method-assign]
    try:
        from scripts import rc8_formal_center_stack_test as legacy

        return int(legacy.main())
    finally:
        TestClient.__init__ = _ORIGINAL_INIT  # type: ignore[method-assign]
        TestClient.post = _ORIGINAL_POST  # type: ignore[method-assign]


if __name__ == "__main__":
    raise SystemExit(main())
