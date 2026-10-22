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


def _fixture() -> TestClient:
    engine = create_engine(
        "sqlite+pysqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    store = PostgresStore(engine)
    delivery_repo = PostgresRequirementDeliveryRepository(store)
    round_repo = PostgresTestRoundRepository(store)
    return TestClient(
        create_app(
            postgres=store,
            delivery_repository=delivery_repo,
            test_round_repository=round_repo,
        )
    )


def _add_delivery(client: TestClient, suffix: str) -> str:
    requirement_id = "REQ-%s" % suffix
    delivery_id = "DEL-%s" % suffix
    assert client.post(
        "/api/v1/requirements",
        json={"requirement_id": requirement_id, "title": "需求%s" % suffix},
    ).status_code == 201
    assert client.post(
        "/api/v1/production-batches/PB/requirements/%s/deliveries" % requirement_id,
        json={"delivery_id": delivery_id},
    ).status_code == 201
    assert client.post(
        "/api/v1/requirement-deliveries/%s/scopes" % delivery_id,
        json={
            "scope_id": "SCOPE-%s" % suffix,
            "system_id": "PFC",
            "system_version": "V-%s" % suffix,
            "application_id": "cfg-center",
            "sst_id": "SST-%s" % suffix,
        },
    ).status_code == 201
    return delivery_id


def test_round_delivery_membership_freezes_when_runtime_mission_starts() -> None:
    client = _fixture()
    assert client.post(
        "/api/v1/production-batches",
        json={"production_batch_id": "PB", "production_date": "2026-11-15", "name": "投产"},
    ).status_code == 201
    delivery_a = _add_delivery(client, "A")
    delivery_b = _add_delivery(client, "B")
    delivery_c = _add_delivery(client, "C")

    created = client.post(
        "/api/v1/production-batches/PB/test-rounds",
        json={"delivery_ids": [delivery_a]},
    )
    assert created.status_code == 201
    round_id = created.json()["round"]["test_round_id"]

    before_start = client.post(
        "/api/v1/production-batches/PB/test-rounds/%s/deliveries/%s" % (round_id, delivery_b),
        json={},
    )
    assert before_start.status_code == 201

    started = client.post(
        "/api/v1/production-batches/PB/test-rounds/%s/test-run" % round_id,
        json={},
    )
    assert started.status_code == 201
    run_body = started.json()["test_run"]
    assert run_body["payload"]["requirement_delivery_ids"] == [delivery_a, delivery_b]

    after_start = client.post(
        "/api/v1/production-batches/PB/test-rounds/%s/deliveries/%s" % (round_id, delivery_c),
        json={},
    )
    assert after_start.status_code == 409
    assert after_start.json()["detail"] == "TEST_ROUND_SCOPE_FROZEN_AFTER_START"

    view = client.get("/api/v1/production-batches/PB/test-rounds/%s" % round_id)
    assert view.status_code == 200
    persisted_delivery_ids = [item["delivery_id"] for item in view.json()["deliveries"]]
    assert persisted_delivery_ids == [delivery_a, delivery_b]
    assert delivery_c not in persisted_delivery_ids
    assert view.json()["test_run"]["payload"]["requirement_delivery_ids"] == [delivery_a, delivery_b]
