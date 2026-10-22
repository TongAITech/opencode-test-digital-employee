from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool

from rc8_center.api import create_app
from rc8_center.control_plane import WorkItemState
from rc8_center.infrastructure import (
    Base,
    PostgresRequirementDeliveryRepository,
    PostgresStore,
    PostgresTestRoundRepository,
    StageWorkItemLinkRow,
)
from rc8_center.infrastructure.postgres import MissionStageRow
from rc8_center.infrastructure.postgres_control import WorkItemRow
from rc8_runtime.governance import StageState
from rc8_runtime.mission_graph import MissionStageType


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
    client = TestClient(
        create_app(
            postgres=store,
            delivery_repository=delivery_repo,
            test_round_repository=round_repo,
        )
    )
    return client, store


def _seed(client: TestClient, scope_count: int = 1) -> None:
    assert client.post(
        "/api/v1/production-batches",
        json={"production_batch_id": "PB", "production_date": "2026-11-15", "name": "投产"},
    ).status_code == 201
    assert client.post(
        "/api/v1/requirements",
        json={"requirement_id": "REQ", "title": "需求"},
    ).status_code == 201
    assert client.post(
        "/api/v1/production-batches/PB/requirements/REQ/deliveries",
        json={"delivery_id": "DEL"},
    ).status_code == 201
    for number in range(1, scope_count + 1):
        assert client.post(
            "/api/v1/requirement-deliveries/DEL/scopes",
            json={
                "scope_id": "SCOPE-%s" % number,
                "system_id": "PFC",
                "system_version": "V1",
                "application_id": "cfg-%s" % number,
                "sst_id": "SST-%s" % number,
            },
        ).status_code == 201
    assert client.post(
        "/api/v1/production-batches/PB/test-rounds",
        json={"test_round_id": "ROUND-1", "delivery_ids": ["DEL"]},
    ).status_code == 201


def _start(client: TestClient):
    return client.post(
        "/api/v1/production-batches/PB/test-rounds/ROUND-1/test-run",
        json={"test_run_id": "TR-1"},
    )


def test_one_scope_bootstraps_full_graph_and_one_ready_work_item_atomically() -> None:
    client, store = _fixture()
    _seed(client, scope_count=1)

    started = _start(client)
    assert started.status_code == 201, started.text
    payload = started.json()["test_run"]["payload"]
    assert payload["mission_stage_count"] == 14
    assert len(payload["mission_initial_ready_stage_ids"]) == 1
    assert len(payload["mission_initial_work_item_ids"]) == 1

    with store._sessions() as session:
        stages = list(session.scalars(select(MissionStageRow).where(MissionStageRow.test_run_id == "TR-1")))
        work_items = list(session.scalars(select(WorkItemRow).where(WorkItemRow.test_run_id == "TR-1")))
        links = list(
            session.scalars(
                select(StageWorkItemLinkRow).where(StageWorkItemLinkRow.test_run_id == "TR-1")
            )
        )

    assert len(stages) == 14
    ready_stages = [stage for stage in stages if stage.state == StageState.READY.value]
    assert len(ready_stages) == 1
    assert ready_stages[0].stage_type == MissionStageType.SCOPE_INTAKE.value
    assert len(work_items) == 1
    assert work_items[0].state == WorkItemState.READY.value
    assert work_items[0].stage == MissionStageType.SCOPE_INTAKE.value
    assert len(links) == 1
    assert links[0].work_item_id == work_items[0].work_item_id
    assert links[0].stage_instance_id == ready_stages[0].stage_instance_id
    assert links[0].test_run_id == "TR-1"
    assert work_items[0].work_item_id in payload["mission_initial_work_item_ids"]


def test_two_scopes_bootstrap_parallel_ready_entries_and_one_mission_convergence() -> None:
    client, store = _fixture()
    _seed(client, scope_count=2)

    started = _start(client)
    assert started.status_code == 201, started.text
    payload = started.json()["test_run"]["payload"]
    assert payload["mission_stage_count"] == 26
    assert len(payload["mission_initial_ready_stage_ids"]) == 2
    assert len(payload["mission_initial_work_item_ids"]) == 2

    with store._sessions() as session:
        stages = list(session.scalars(select(MissionStageRow).where(MissionStageRow.test_run_id == "TR-1")))
        work_items = list(session.scalars(select(WorkItemRow).where(WorkItemRow.test_run_id == "TR-1")))
        links = list(
            session.scalars(
                select(StageWorkItemLinkRow).where(StageWorkItemLinkRow.test_run_id == "TR-1")
            )
        )

    assert len(stages) == 26
    assert len(work_items) == 2
    assert len(links) == 2
    assert {link.work_item_id for link in links} == {item.work_item_id for item in work_items}
    assert {link.stage_instance_id for link in links} == set(payload["mission_initial_ready_stage_ids"])

    mission = [stage for stage in stages if stage.stage_type == MissionStageType.MISSION_SUFFICIENCY.value]
    report = [stage for stage in stages if stage.stage_type == MissionStageType.REPORT_RELEASE.value]
    assert len(mission) == 1
    assert len(report) == 1
    assert len(mission[0].predecessor_ids) == 2
    assert report[0].predecessor_ids == [mission[0].stage_instance_id]


def test_failed_round_start_persists_no_test_run_stage_work_or_link() -> None:
    client, store = _fixture()
    assert client.post(
        "/api/v1/production-batches",
        json={"production_batch_id": "PB", "production_date": "2026-11-15", "name": "投产"},
    ).status_code == 201
    assert client.post(
        "/api/v1/requirements",
        json={"requirement_id": "REQ", "title": "需求"},
    ).status_code == 201
    assert client.post(
        "/api/v1/production-batches/PB/requirements/REQ/deliveries",
        json={"delivery_id": "DEL"},
    ).status_code == 201
    assert client.post(
        "/api/v1/production-batches/PB/test-rounds",
        json={"test_round_id": "ROUND-1", "delivery_ids": ["DEL"]},
    ).status_code == 201

    failed = _start(client)
    assert failed.status_code == 409
    assert failed.json()["detail"] == "TEST_ROUND_SCOPE_INCOMPLETE"
    assert store.get_test_run("TR-1") is None

    with store._sessions() as session:
        assert list(session.scalars(select(MissionStageRow).where(MissionStageRow.test_run_id == "TR-1"))) == []
        assert list(session.scalars(select(WorkItemRow).where(WorkItemRow.test_run_id == "TR-1"))) == []
        assert list(
            session.scalars(
                select(StageWorkItemLinkRow).where(StageWorkItemLinkRow.test_run_id == "TR-1")
            )
        ) == []
