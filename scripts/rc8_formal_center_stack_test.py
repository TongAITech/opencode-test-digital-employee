#!/usr/bin/env python3
from __future__ import annotations

import os
import uuid

from fastapi.testclient import TestClient

from rc8_center.api import create_app
from rc8_center.formal_settings import CenterSettings
from rc8_center.infrastructure import PostgresStore, RedisCoordination, build_engine


def main() -> int:
    settings = CenterSettings(
        database_url=os.environ["RC8_DATABASE_URL"],
        redis_url=os.environ["RC8_REDIS_URL"],
        environment="integration-test",
    )
    postgres = PostgresStore(build_engine(settings.database_url))
    redis = RedisCoordination.from_url(settings.redis_url, namespace="rc8-it")

    assert postgres.ping(), "POSTGRES_PING_FAILED"
    assert redis.ping(), "REDIS_PING_FAILED"

    app = create_app(settings=settings, postgres=postgres, redis_coordination=redis)
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200, health.text
    body = health.json()
    assert body["status"] == "READY", body
    assert body["database"] == "READY", body
    assert body["redis"] == "READY", body
    assert body["runtime_truth"] == "R1_EVENT_STREAM", body

    architecture = client.get("/api/v1/system/architecture")
    assert architecture.status_code == 200, architecture.text
    architecture_body = architecture.json()
    assert architecture_body["status"] == "FROZEN"
    assert architecture_body["technology"]["backend"] == "FastAPI"
    assert architecture_body["technology"]["persistence"] == "PostgreSQL"
    assert architecture_body["technology"]["coordination"] == "Redis"
    assert architecture_body["technology"]["frontend"] == "Vue3+TypeScript+Vite"
    assert architecture_body["truth_rules"]["redis_authoritative"] is False
    assert architecture_body["truth_rules"]["ui_may_infer_pass"] is False

    run_id = "formal-it-%s" % uuid.uuid4().hex[:12]
    created = client.post(
        "/api/v1/test-runs",
        json={
            "test_run_id": run_id,
            "production_batch_id": "PB-IT",
            "payload": {"scope": "formal-center-integration"},
        },
    )
    assert created.status_code == 201, created.text
    assert created.headers["location"] == "/api/v1/test-runs/%s" % run_id
    assert created.json()["current_state"] == "PLANNED"

    duplicate = client.post("/api/v1/test-runs", json={"test_run_id": run_id})
    assert duplicate.status_code == 409, duplicate.text

    invalid = client.post("/api/v1/test-runs", json={"test_run_id": "", "unexpected": True})
    assert invalid.status_code == 422, invalid.text

    fetched = client.get("/api/v1/test-runs/%s" % run_id)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["production_batch_id"] == "PB-IT"

    listed = client.get("/api/v1/test-runs")
    assert listed.status_code == 200, listed.text
    assert any(item["test_run_id"] == run_id for item in listed.json())

    projector = "governance"
    first = postgres.set_checkpoint(projector, last_event_id="evt-10", last_sequence=10, detail="first")
    assert first.last_sequence == 10
    replay = postgres.set_checkpoint(projector, last_event_id="evt-10", last_sequence=10, detail="replay")
    assert replay.last_sequence == 10
    try:
        postgres.set_checkpoint(projector, last_event_id="evt-9", last_sequence=9)
        raise AssertionError("CHECKPOINT_REGRESSION_ACCEPTED")
    except ValueError as exc:
        assert str(exc) == "PROJECTION_CHECKPOINT_CANNOT_REGRESS"

    lease_resource = "work-%s" % uuid.uuid4().hex[:8]
    assert redis.acquire_lease("work-item", lease_resource, "node-a", 30)
    assert not redis.acquire_lease("work-item", lease_resource, "node-b", 30)
    assert redis.lease_owner("work-item", lease_resource) == "node-a"
    assert redis.renew_lease("work-item", lease_resource, "node-a", 30)
    assert not redis.renew_lease("work-item", lease_resource, "node-b", 30)
    try:
        redis.release_lease("work-item", lease_resource, "node-b")
        raise AssertionError("WRONG_OWNER_RELEASE_ACCEPTED")
    except ValueError as exc:
        assert str(exc) == "LEASE_OWNER_MISMATCH"
    assert redis.release_lease("work-item", lease_resource, "node-a")
    assert redis.lease_owner("work-item", lease_resource) is None

    queue = "dispatch-%s" % uuid.uuid4().hex[:8]
    redis.enqueue(queue, {"work_item_id": lease_resource, "test_run_id": run_id})
    item = redis.dequeue(queue)
    assert item == {"test_run_id": run_id, "work_item_id": lease_resource}
    assert redis.dequeue(queue) is None

    # Redis is coordination only. Removing transient state must not remove durable PostgreSQL truth.
    redis.client.flushdb()
    persisted = postgres.get_test_run(run_id)
    assert persisted is not None
    assert persisted.test_run_id == run_id

    governance = client.get("/api/v1/test-runs/%s/governance" % run_id)
    assert governance.status_code == 503, governance.text
    assert governance.json()["detail"] == "GOVERNANCE_PROJECTION_NOT_CONFIGURED"

    print(
        {
            "status": "FORMAL_CENTER_STACK_FOUNDATION_VERIFIED",
            "scope": "FASTAPI_POSTGRES_REDIS_FOUNDATION_ONLY",
            "test_run_id": run_id,
            "mission_sufficient": False,
            "product_closed": False,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
