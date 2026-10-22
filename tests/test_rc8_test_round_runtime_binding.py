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
from rc8_center.infrastructure.postgres import AttemptRow, MissionStageRow


def _fixture():
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
    app = create_app(
        postgres=store,
        delivery_repository=delivery_repo,
        test_round_repository=round_repo,
    )
    return TestClient(app), store


def _seed_scope(client: TestClient) -> None:
    assert client.post(
        "/api/v1/production-batches",
        json={"production_batch_id": "PB-20261115", "production_date": "2026-11-15", "name": "11月15日投产"},
    ).status_code == 201
    assert client.post(
        "/api/v1/requirements",
        json={"requirement_id": "REQ-001", "title": "需求一"},
    ).status_code == 201
    assert client.post(
        "/api/v1/production-batches/PB-20261115/requirements/REQ-001/deliveries",
        json={"delivery_id": "DEL-001"},
    ).status_code == 201
    assert client.post(
        "/api/v1/requirement-deliveries/DEL-001/scopes",
        json={
            "scope_id": "SCOPE-001",
            "system_id": "PFC",
            "system_version": "BLOAN-PF1.2.0",
            "application_id": "cfg-center",
            "sst_id": "STB915-7489",
        },
    ).status_code == 201


def _create_round(client: TestClient, round_id: str, name: str):
    response = client.post(
        "/api/v1/production-batches/PB-20261115/test-rounds",
        json={"test_round_id": round_id, "name": name, "delivery_ids": ["DEL-001"]},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _start_round(client: TestClient, round_id: str, run_id: str):
    return client.post(
        f"/api/v1/production-batches/PB-20261115/test-rounds/{round_id}/test-run",
        json={"test_run_id": run_id},
    )


def test_round_scoped_test_run_becomes_runtime_parent_for_stage_and_attempt() -> None:
    client, store = _fixture()
    _seed_scope(client)
    _create_round(client, "ROUND-1", "第1轮")

    started = _start_round(client, "ROUND-1", "TR-ROUND-1")
    assert started.status_code == 201, started.text
    body = started.json()
    assert body["test_run"]["production_batch_id"] == "PB-20261115"
    assert body["test_run"]["test_round_id"] == "ROUND-1"
    assert body["test_run"]["payload"]["task_scope_source"] == "TEST_ROUND_REQUIREMENT_DELIVERY"
    assert body["test_run"]["payload"]["requirement_delivery_ids"] == ["DEL-001"]
    assert body["test_run"]["payload"]["delivery_scope_ids"] == ["SCOPE-001"]
    assert body["round"]["state"] == "ACTIVE"

    persisted = store.get_test_run_for_round("ROUND-1")
    assert persisted is not None
    assert persisted.test_run_id == "TR-ROUND-1"
    assert persisted.test_round_id == "ROUND-1"

    with store.session() as session:
        session.add(
            MissionStageRow(
                stage_instance_id="STAGE-1",
                test_run_id="TR-ROUND-1",
                stage_type="TEST_EXECUTION",
                scope_version="scope-v1",
                attempt_no=1,
                state="RUNNING",
                input_refs=[],
                output_refs=[],
                gap_refs=[],
                invalidation_refs=[],
                predecessor_ids=[],
                successor_ids=[],
                created_at=100,
                updated_at=100,
                payload={},
            )
        )
        session.add(
            AttemptRow(
                attempt_id="ATTEMPT-1",
                test_run_id="TR-ROUND-1",
                stage_instance_id="STAGE-1",
                work_item_id="WORK-1",
                producer_node_id="NODE-1",
                producer_ref="worker:L1",
                input_snapshot_ref="snapshot:1",
                status="RUNNING",
                action_refs=[],
                assertion_refs=[],
                evidence_refs=[],
                coverage_refs=[],
                gap_refs=[],
                defect_refs=[],
                started_at=101,
                payload={},
            )
        )

    with store._sessions() as session:
        stage = session.get(MissionStageRow, "STAGE-1")
        attempt = session.get(AttemptRow, "ATTEMPT-1")
        assert stage is not None and stage.test_run_id == persisted.test_run_id
        assert attempt is not None and attempt.test_run_id == persisted.test_run_id
        assert attempt.stage_instance_id == stage.stage_instance_id

    round_view = client.get("/api/v1/production-batches/PB-20261115/test-rounds/ROUND-1")
    assert round_view.status_code == 200
    assert round_view.json()["test_run"]["test_run_id"] == "TR-ROUND-1"


def test_two_rounds_of_same_delivery_create_two_isolated_runtime_missions() -> None:
    client, store = _fixture()
    _seed_scope(client)
    _create_round(client, "ROUND-1", "第1轮")
    first = _start_round(client, "ROUND-1", "TR-ROUND-1")
    assert first.status_code == 201

    _create_round(client, "ROUND-2", "第2轮")
    second = _start_round(client, "ROUND-2", "TR-ROUND-2")
    assert second.status_code == 201

    first_row = store.get_test_run_for_round("ROUND-1")
    second_row = store.get_test_run_for_round("ROUND-2")
    assert first_row is not None and second_row is not None
    assert first_row.test_run_id == "TR-ROUND-1"
    assert second_row.test_run_id == "TR-ROUND-2"
    assert first_row.test_run_id != second_row.test_run_id
    assert first_row.production_batch_id == second_row.production_batch_id == "PB-20261115"
    assert first_row.payload["requirement_delivery_ids"] == second_row.payload["requirement_delivery_ids"] == ["DEL-001"]


def test_one_round_cannot_own_two_top_level_test_runs() -> None:
    client, _store = _fixture()
    _seed_scope(client)
    _create_round(client, "ROUND-1", "第1轮")
    assert _start_round(client, "ROUND-1", "TR-1").status_code == 201

    duplicate = _start_round(client, "ROUND-1", "TR-2")
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "TEST_ROUND_ALREADY_HAS_TEST_RUN"


def test_round_start_is_fail_closed_when_round_has_no_delivery_or_scope() -> None:
    client, _store = _fixture()
    assert client.post(
        "/api/v1/production-batches",
        json={"production_batch_id": "PB-20261115", "production_date": "2026-11-15", "name": "投产"},
    ).status_code == 201
    assert client.post(
        "/api/v1/production-batches/PB-20261115/test-rounds",
        json={"test_round_id": "ROUND-EMPTY", "name": "空轮次"},
    ).status_code == 201
    empty = _start_round(client, "ROUND-EMPTY", "TR-EMPTY")
    assert empty.status_code == 409
    assert empty.json()["detail"] == "TEST_ROUND_HAS_NO_REQUIREMENTS"

    assert client.post("/api/v1/requirements", json={"requirement_id": "REQ", "title": "需求"}).status_code == 201
    assert client.post(
        "/api/v1/production-batches/PB-20261115/requirements/REQ/deliveries",
        json={"delivery_id": "DEL-NO-SCOPE"},
    ).status_code == 201
    assert client.post(
        "/api/v1/production-batches/PB-20261115/test-rounds",
        json={"test_round_id": "ROUND-NO-SCOPE", "delivery_ids": ["DEL-NO-SCOPE"]},
    ).status_code == 201
    incomplete = _start_round(client, "ROUND-NO-SCOPE", "TR-NO-SCOPE")
    assert incomplete.status_code == 409
    assert incomplete.json()["detail"] == "TEST_ROUND_SCOPE_INCOMPLETE"


def test_terminal_round_cannot_start_runtime_mission() -> None:
    client, _store = _fixture()
    _seed_scope(client)
    _create_round(client, "ROUND-1", "第1轮")
    assert client.patch(
        "/api/v1/production-batches/PB-20261115/test-rounds/ROUND-1/state",
        json={"state": "CANCELLED"},
    ).status_code == 200

    blocked = _start_round(client, "ROUND-1", "TR-BLOCKED")
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "TEST_ROUND_NOT_STARTABLE"
