from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from rc8_center.api.test_round_routes import register_test_round_routes
from rc8_center.delivery import ProductionBatch, Requirement, RequirementDelivery, RequirementDeliveryState
from rc8_center.infrastructure.postgres import Base, PostgresStore
from rc8_center.infrastructure.postgres_delivery import PostgresRequirementDeliveryRepository
from rc8_center.infrastructure.postgres_test_round import PostgresTestRoundRepository


def _fixture():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    store = PostgresStore(engine)
    Base.metadata.create_all(engine)
    delivery_repo = PostgresRequirementDeliveryRepository(store)
    round_repo = PostgresTestRoundRepository(store)

    delivery_repo.create_batch(
        ProductionBatch(
            production_batch_id="batch-2026-11-15",
            production_date="2026-11-15",
            name="2026-11-15",
            created_at=100,
        )
    )
    delivery_repo.create_requirement(Requirement(requirement_id="R001", title="需求1", created_at=100))
    delivery_repo.create_delivery(
        RequirementDelivery(
            delivery_id="delivery-r1-b1",
            production_batch_id="batch-2026-11-15",
            requirement_id="R001",
            created_at=100,
            updated_at=100,
        )
    )

    app = FastAPI()
    app.state.test_round_repository = round_repo
    register_test_round_routes(app)
    return TestClient(app), delivery_repo, round_repo


def test_api_creates_multiple_rounds_inside_one_production_date_without_creating_more_deliveries():
    client, delivery_repo, _round_repo = _fixture()

    first = client.post(
        "/api/v1/production-batches/batch-2026-11-15/test-rounds",
        json={
            "test_round_id": "round-1",
            "name": "第1轮测试",
            "delivery_ids": ["delivery-r1-b1"],
        },
    )
    second = client.post(
        "/api/v1/production-batches/batch-2026-11-15/test-rounds",
        json={
            "test_round_id": "round-2",
            "name": "第2轮测试",
            "delivery_ids": ["delivery-r1-b1"],
        },
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["round"]["round_no"] == 1
    assert second.json()["round"]["round_no"] == 2

    listed = client.get("/api/v1/production-batches/batch-2026-11-15/test-rounds")
    assert listed.status_code == 200
    assert [item["round"]["round_no"] for item in listed.json()] == [1, 2]

    history = delivery_repo.requirement_history("R001")
    assert len(history.deliveries) == 1
    assert history.spans_multiple_batches is False


def test_api_rejects_delivery_from_another_production_date():
    client, delivery_repo, _round_repo = _fixture()
    delivery_repo.create_batch(
        ProductionBatch(
            production_batch_id="batch-2026-12-10",
            production_date="2026-12-10",
            name="2026-12-10",
            created_at=200,
        )
    )

    created = client.post(
        "/api/v1/production-batches/batch-2026-12-10/test-rounds",
        json={"test_round_id": "round-next-date", "name": "下一投产日第1轮"},
    )
    assert created.status_code == 201

    response = client.post(
        "/api/v1/production-batches/batch-2026-12-10/test-rounds/round-next-date/deliveries/delivery-r1-b1",
        json={},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "TEST_ROUND_DELIVERY_PRODUCTION_DATE_MISMATCH"


def test_api_round_completion_does_not_complete_requirement_delivery():
    client, delivery_repo, _round_repo = _fixture()
    created = client.post(
        "/api/v1/production-batches/batch-2026-11-15/test-rounds",
        json={
            "test_round_id": "round-1",
            "name": "第1轮测试",
            "delivery_ids": ["delivery-r1-b1"],
        },
    )
    assert created.status_code == 201

    active = client.patch(
        "/api/v1/production-batches/batch-2026-11-15/test-rounds/round-1/state",
        json={"state": "ACTIVE"},
    )
    completed = client.patch(
        "/api/v1/production-batches/batch-2026-11-15/test-rounds/round-1/state",
        json={"state": "COMPLETED"},
    )

    assert active.status_code == 200
    assert completed.status_code == 200
    assert completed.json()["round"]["state"] == "COMPLETED"
    persisted = delivery_repo.get_delivery("delivery-r1-b1")
    assert persisted is not None
    assert persisted.state == RequirementDeliveryState.PLANNED


def test_api_path_production_date_must_match_round_owner():
    client, delivery_repo, _round_repo = _fixture()
    delivery_repo.create_batch(
        ProductionBatch(
            production_batch_id="batch-2026-12-10",
            production_date="2026-12-10",
            name="2026-12-10",
            created_at=200,
        )
    )
    created = client.post(
        "/api/v1/production-batches/batch-2026-11-15/test-rounds",
        json={"test_round_id": "round-1", "name": "第1轮测试"},
    )
    assert created.status_code == 201

    wrong_path = client.get(
        "/api/v1/production-batches/batch-2026-12-10/test-rounds/round-1"
    )
    assert wrong_path.status_code == 409
    assert wrong_path.json()["detail"] == "TEST_ROUND_PRODUCTION_DATE_MISMATCH"
