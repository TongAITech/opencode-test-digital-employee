from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from rc8_center.api import create_app
from rc8_center.infrastructure import (
    Base,
    PostgresRequirementDeliveryRepository,
    PostgresStore,
    PostgresTestRoundRepository,
)


def _client() -> TestClient:
    engine = create_engine(
        "sqlite+pysqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    store = PostgresStore(engine)
    repository = PostgresRequirementDeliveryRepository(store)
    round_repository = PostgresTestRoundRepository(store)
    return TestClient(
        create_app(
            postgres=store,
            delivery_repository=repository,
            test_round_repository=round_repository,
        )
    )


def test_user_flow_starts_from_batch_then_requirement_scope_then_test_round() -> None:
    client = _client()
    assert client.post(
        "/api/v1/production-batches",
        json={"production_batch_id": "PB-20261115", "production_date": "2026-11-15", "name": "11月投产"},
    ).status_code == 201
    assert client.post(
        "/api/v1/requirements",
        json={"requirement_id": "REQ-001", "title": "业务需求一"},
    ).status_code == 201
    assert client.post(
        "/api/v1/production-batches/PB-20261115/requirements/REQ-001/deliveries",
        json={"delivery_id": "DEL-001", "state": "COMPLETED"},
    ).status_code == 201
    assert client.post(
        "/api/v1/requirement-deliveries/DEL-001/scopes",
        json={
            "scope_id": "SCOPE-1",
            "system_id": "SYS-A",
            "system_version": "A-1.8.0",
            "application_id": "cfg-center",
            "sst_id": "SST-A101",
        },
    ).status_code == 201

    history = client.get("/api/v1/requirements/REQ-001/deliveries")
    assert history.status_code == 200
    body = history.json()
    assert body["completed_in_single_batch"] is True
    assert body["spans_multiple_batches"] is False
    assert body["deliveries"][0]["scopes"][0]["system_version"] == "A-1.8.0"

    plan = client.get("/api/v1/production-batches/PB-20261115/plan")
    assert plan.status_code == 200
    assert plan.json()["requirements"][0]["requirement"]["requirement_id"] == "REQ-001"

    bypass = client.post(
        "/api/v1/production-batches/PB-20261115/test-runs",
        json={},
    )
    assert bypass.status_code == 409
    assert bypass.json()["detail"] == "TEST_ROUND_REQUIRED_FOR_PRODUCTION_TEST_RUN"

    created_round = client.post(
        "/api/v1/production-batches/PB-20261115/test-rounds",
        json={"delivery_ids": ["DEL-001"]},
    )
    assert created_round.status_code == 201
    round_body = created_round.json()["round"]
    assert round_body["test_round_id"] == "PB-20261115-round-1"
    assert round_body["round_no"] == 1

    started = client.post(
        "/api/v1/production-batches/PB-20261115/test-rounds/PB-20261115-round-1/test-run",
        json={},
    )
    assert started.status_code == 201
    run = started.json()["test_run"]
    assert run["production_batch_id"] == "PB-20261115"
    assert run["test_round_id"] == "PB-20261115-round-1"
    assert run["payload"]["task_scope_source"] == "TEST_ROUND_REQUIREMENT_DELIVERY"
    assert run["payload"]["requirement_delivery_ids"] == ["DEL-001"]
    assert run["payload"]["delivery_scope_ids"] == ["SCOPE-1"]


def test_same_requirement_can_continue_in_later_batch_and_history_is_preserved() -> None:
    client = _client()
    for batch_id, production_date in (("PB-1", "2026-11-15"), ("PB-2", "2026-12-20")):
        assert client.post(
            "/api/v1/production-batches",
            json={"production_batch_id": batch_id, "production_date": production_date, "name": batch_id},
        ).status_code == 201
    assert client.post("/api/v1/requirements", json={"requirement_id": "REQ", "title": "跨批次需求"}).status_code == 201
    assert client.post(
        "/api/v1/production-batches/PB-1/requirements/REQ/deliveries",
        json={"delivery_id": "DEL-1", "state": "PARTIAL"},
    ).status_code == 201
    assert client.post(
        "/api/v1/requirement-deliveries/DEL-1/scopes",
        json={"scope_id": "S1", "system_id": "SYS-A", "system_version": "1.0", "sst_id": "SST-1"},
    ).status_code == 201
    assert client.post(
        "/api/v1/production-batches/PB-2/requirements/REQ/deliveries",
        json={"delivery_id": "DEL-2", "state": "COMPLETED", "continuation_of_delivery_id": "DEL-1"},
    ).status_code == 201
    assert client.post(
        "/api/v1/requirement-deliveries/DEL-2/scopes",
        json={"scope_id": "S2", "system_id": "SYS-B", "system_version": "2.0", "sst_id": "SST-2"},
    ).status_code == 201

    body = client.get("/api/v1/requirements/REQ/deliveries").json()
    assert body["spans_multiple_batches"] is True
    assert [entry["delivery"]["delivery_id"] for entry in body["deliveries"]] == ["DEL-1", "DEL-2"]
    assert body["deliveries"][0]["delivery"]["state"] == "PARTIAL"
    assert body["deliveries"][0]["scopes"][0]["system_version"] == "1.0"
    assert body["deliveries"][1]["scopes"][0]["system_version"] == "2.0"


def test_same_requirement_is_not_duplicated_inside_one_batch() -> None:
    client = _client()
    client.post(
        "/api/v1/production-batches",
        json={"production_batch_id": "PB", "production_date": "2026-11-15", "name": "PB"},
    )
    client.post("/api/v1/requirements", json={"requirement_id": "REQ", "title": "需求"})
    first = client.post(
        "/api/v1/production-batches/PB/requirements/REQ/deliveries",
        json={"delivery_id": "DEL-1"},
    )
    second = client.post(
        "/api/v1/production-batches/PB/requirements/REQ/deliveries",
        json={"delivery_id": "DEL-2"},
    )
    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["detail"] == "REQUIREMENT_ALREADY_PARTICIPATES_IN_BATCH"


def test_round_cannot_start_without_requirement_or_scope() -> None:
    client = _client()
    assert client.post(
        "/api/v1/production-batches",
        json={"production_batch_id": "PB", "production_date": "2026-11-15", "name": "PB"},
    ).status_code == 201

    empty_round = client.post(
        "/api/v1/production-batches/PB/test-rounds",
        json={},
    )
    assert empty_round.status_code == 201
    empty = client.post(
        "/api/v1/production-batches/PB/test-rounds/PB-round-1/test-run",
        json={},
    )
    assert empty.status_code == 409
    assert empty.json()["detail"] == "TEST_ROUND_HAS_NO_REQUIREMENTS"

    assert client.post("/api/v1/requirements", json={"requirement_id": "REQ", "title": "需求"}).status_code == 201
    assert client.post(
        "/api/v1/production-batches/PB/requirements/REQ/deliveries",
        json={"delivery_id": "DEL"},
    ).status_code == 201
    incomplete_round = client.post(
        "/api/v1/production-batches/PB/test-rounds",
        json={"delivery_ids": ["DEL"]},
    )
    assert incomplete_round.status_code == 201
    incomplete = client.post(
        "/api/v1/production-batches/PB/test-rounds/PB-round-2/test-run",
        json={},
    )
    assert incomplete.status_code == 409
    assert incomplete.json()["detail"] == "TEST_ROUND_SCOPE_INCOMPLETE"


def test_invalid_production_date_is_rejected() -> None:
    client = _client()
    response = client.post(
        "/api/v1/production-batches",
        json={"production_batch_id": "PB-BAD", "production_date": "2026-02-30", "name": "错误日期"},
    )
    assert response.status_code == 422


def _run_direct() -> None:
    test_user_flow_starts_from_batch_then_requirement_scope_then_test_round()
    test_same_requirement_can_continue_in_later_batch_and_history_is_preserved()
    test_same_requirement_is_not_duplicated_inside_one_batch()
    test_round_cannot_start_without_requirement_or_scope()
    test_invalid_production_date_is_rejected()
    print("RC8_PRODUCTION_REQUIREMENT_API_PASS")


if __name__ == "__main__":
    _run_direct()
