#!/usr/bin/env python3
"""Real PostgreSQL production-date -> TestRound -> Mission bootstrap proof.

This test deliberately does not reuse the historical one-Stage control-plane
fixture. A production mission must enter through ProductionBatch(date), selected
RequirementDelivery/Scope and TestRound, then bootstrap the durable multi-Stage
Mission Graph and initial schedulable WorkItem lineage.
"""
from __future__ import annotations

import os
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from rc8_center.api import create_app
from rc8_center.governance_projection import GovernanceProjectionService
from rc8_center.infrastructure import (
    PostgresCenterRepository,
    PostgresCoverageRepository,
    PostgresGovernanceRepository,
    PostgresRequirementDeliveryRepository,
    PostgresStore,
    PostgresTestRoundRepository,
    StageWorkItemLinkRow,
    build_engine,
)
from rc8_center.infrastructure.postgres import MissionStageRow
from rc8_center.infrastructure.postgres_control import WorkItemRow


def _post(client: TestClient, path: str, payload: dict, expected: int = 201):
    response = client.post(path, json=payload)
    assert response.status_code == expected, (path, response.status_code, response.text)
    return response.json()


def main() -> int:
    store = PostgresStore(build_engine(os.environ["RC8_DATABASE_URL"]))
    delivery = PostgresRequirementDeliveryRepository(store)
    rounds = PostgresTestRoundRepository(store)
    governance = PostgresGovernanceRepository(store)
    coverage = PostgresCoverageRepository(store)
    control = PostgresCenterRepository(store)
    projection = GovernanceProjectionService(governance, coverage)
    app = create_app(
        postgres=store,
        governance_projection=projection,
        delivery_repository=delivery,
        test_round_repository=rounds,
    )
    client = TestClient(app)

    suffix = uuid.uuid4().hex[:10]
    batch_id = "PB-ROUND-%s" % suffix
    requirement_id = "REQ-ROUND-%s" % suffix
    delivery_id = "DEL-ROUND-%s" % suffix
    scope_id = "SCOPE-ROUND-%s" % suffix
    run_id = "TR-ROUND-%s" % suffix

    batch = _post(
        client,
        "/api/v1/production-batches",
        {
            "production_batch_id": batch_id,
            "production_date": "2026-11-15",
            "name": "11月15日投产",
        },
    )
    assert batch["production_date"] == "2026-11-15"
    _post(client, "/api/v1/requirements", {"requirement_id": requirement_id, "title": "轮次入口需求"})
    _post(
        client,
        "/api/v1/production-batches/%s/requirements/%s/deliveries" % (batch_id, requirement_id),
        {"delivery_id": delivery_id},
    )
    _post(
        client,
        "/api/v1/requirement-deliveries/%s/scopes" % delivery_id,
        {
            "scope_id": scope_id,
            "system_id": "PFC",
            "system_version": "V1",
            "application_id": "cfg-center",
            "sst_id": "SST-ROUND",
        },
    )

    created_round = _post(
        client,
        "/api/v1/production-batches/%s/test-rounds" % batch_id,
        {"delivery_ids": [delivery_id]},
    )
    round_body = created_round["round"]
    round_id = round_body["test_round_id"]
    assert round_body["round_no"] == 1
    assert round_body["state"] == "PLANNED"

    started = _post(
        client,
        "/api/v1/production-batches/%s/test-rounds/%s/test-run" % (batch_id, round_id),
        {"test_run_id": run_id},
    )
    run = started["test_run"]
    assert started["round"]["state"] == "ACTIVE"
    assert run["production_batch_id"] == batch_id
    assert run["test_round_id"] == round_id
    assert run["payload"]["requirement_delivery_ids"] == [delivery_id]
    assert run["payload"]["delivery_scope_ids"] == [scope_id]
    # One scope gets 12 scope-local stages + mission sufficiency + report/release.
    assert run["payload"]["mission_stage_count"] == 14
    assert len(run["payload"]["mission_initial_ready_stage_ids"]) == 1
    assert len(run["payload"]["mission_initial_work_item_ids"]) == 1

    with store._sessions() as session:
        stages = list(session.scalars(select(MissionStageRow).where(MissionStageRow.test_run_id == run_id)))
        work = list(session.scalars(select(WorkItemRow).where(WorkItemRow.test_run_id == run_id)))
        lineage = list(session.scalars(select(StageWorkItemLinkRow).where(StageWorkItemLinkRow.test_run_id == run_id)))
    assert len(stages) == 14
    assert len(work) == 1
    assert len(lineage) == 1
    ready = [item for item in stages if item.state == "READY"]
    pending = [item for item in stages if item.state == "PENDING"]
    assert len(ready) == 1 and ready[0].stage_type == "SCOPE_INTAKE"
    assert len(pending) == 13
    assert lineage[0].stage_instance_id == ready[0].stage_instance_id
    assert lineage[0].work_item_id == work[0].work_item_id
    assert work[0].state == "READY"

    view = client.get("/api/v1/test-runs/%s/governance" % run_id)
    assert view.status_code == 200, view.text
    body = view.json()
    assert body["stage_count"] == 14
    assert body["attempt_count"] == 0
    assert body["latest_mission_sufficiency"] is None
    assert body["latest_release_decision"] is None

    # Production missions cannot bypass TestRound through the generic API.
    bypass = client.post(
        "/api/v1/test-runs",
        json={"test_run_id": "BYPASS-%s" % suffix, "production_batch_id": batch_id},
    )
    assert bypass.status_code == 409
    assert bypass.json()["detail"] == "USE_TEST_ROUND_START_API_FOR_PRODUCTION_MISSION"

    print({
        "status": "RC8_PRODUCTION_DATE_TEST_ROUND_MISSION_ENTRY_PASS",
        "production_date": "2026-11-15",
        "test_round_id": round_id,
        "test_run_id": run_id,
        "stage_count": len(stages),
        "ready_work_items": [item.work_item_id for item in work],
        "truth_note": "Production mission entered through TestRound and bootstrapped the full durable Mission Graph.",
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
