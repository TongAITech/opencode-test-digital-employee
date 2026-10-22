from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from rc8_center.api import create_app
from rc8_center.delivery import ProductionBatch, Requirement, RequirementDelivery, RequirementDeliveryScope
from rc8_center.infrastructure import (
    Base,
    PostgresRequirementDeliveryRepository,
    PostgresRequirementRevisionRepository,
    PostgresStore,
    PostgresTestRoundRepository,
)
from rc8_center.revisions import RequirementRevision, ScopeRevision


def _store() -> PostgresStore:
    engine = create_engine(
        "sqlite+pysqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return PostgresStore(engine)


def _client() -> tuple[TestClient, PostgresStore]:
    store = _store()
    delivery = PostgresRequirementDeliveryRepository(store)
    revisions = PostgresRequirementRevisionRepository(store)
    rounds = PostgresTestRoundRepository(store)
    app = create_app(
        postgres=store,
        delivery_repository=delivery,
        revision_repository=revisions,
        test_round_repository=rounds,
    )
    return TestClient(app), store


def test_requirement_v1_v2_are_distinct_from_system_versions() -> None:
    store = _store()
    delivery = PostgresRequirementDeliveryRepository(store)
    revisions = PostgresRequirementRevisionRepository(store)

    delivery.create_requirement(Requirement(requirement_id="REQ-1", title="长期业务需求", created_at=1))
    revisions.create_requirement_revision(
        RequirementRevision(
            requirement_revision_id="REQ-1-V1",
            requirement_id="REQ-1",
            revision_label="V1",
            created_at=2,
        )
    )
    revisions.create_scope_revision(
        ScopeRevision(
            scope_revision_id="REQ-1-V1-SCOPE",
            requirement_revision_id="REQ-1-V1",
            revision_label="SR1",
            created_at=3,
        )
    )
    revisions.create_requirement_revision(
        RequirementRevision(
            requirement_revision_id="REQ-1-V2",
            requirement_id="REQ-1",
            revision_label="V2",
            parent_requirement_revision_id="REQ-1-V1",
            created_at=4,
        )
    )
    revisions.create_scope_revision(
        ScopeRevision(
            scope_revision_id="REQ-1-V2-SCOPE",
            requirement_revision_id="REQ-1-V2",
            revision_label="SR2",
            parent_scope_revision_id="REQ-1-V1-SCOPE",
            created_at=5,
        )
    )

    for batch_id, day in (("PB-1", "2026-11-15"), ("PB-2", "2026-12-20")):
        delivery.create_batch(ProductionBatch(production_batch_id=batch_id, production_date=day, name=batch_id, created_at=1))

    first = delivery.create_delivery(
        RequirementDelivery(
            delivery_id="DEL-1",
            production_batch_id="PB-1",
            requirement_id="REQ-1",
            requirement_revision_id="REQ-1-V1",
            scope_revision_id="REQ-1-V1-SCOPE",
            created_at=10,
            updated_at=10,
        )
    )
    delivery.create_scope(
        RequirementDeliveryScope(
            scope_id="SCOPE-A-V1",
            delivery_id="DEL-1",
            system_id="SYS-A",
            system_version="A-1.7.0",
            sst_id="SST-A101",
            created_at=11,
        )
    )
    second = delivery.create_delivery(
        RequirementDelivery(
            delivery_id="DEL-2",
            production_batch_id="PB-2",
            requirement_id="REQ-1",
            continuation_of_delivery_id="DEL-1",
            requirement_revision_id="REQ-1-V2",
            scope_revision_id="REQ-1-V2-SCOPE",
            created_at=20,
            updated_at=20,
        )
    )
    delivery.create_scope(
        RequirementDeliveryScope(
            scope_id="SCOPE-A-V2",
            delivery_id="DEL-2",
            system_id="SYS-A",
            system_version="A-1.8.0",
            sst_id="SST-A105",
            created_at=21,
        )
    )

    assert first.requirement_revision_id == "REQ-1-V1"
    assert second.requirement_revision_id == "REQ-1-V2"
    assert revisions.get_requirement_revision("REQ-1-V2").parent_requirement_revision_id == "REQ-1-V1"
    assert revisions.get_scope_revision("REQ-1-V2-SCOPE").parent_scope_revision_id == "REQ-1-V1-SCOPE"
    history = delivery.requirement_history("REQ-1")
    assert [item.requirement_revision_id for item in history.deliveries] == ["REQ-1-V1", "REQ-1-V2"]
    assert history.scopes_by_delivery["DEL-1"][0].system_version == "A-1.7.0"
    assert history.scopes_by_delivery["DEL-2"][0].system_version == "A-1.8.0"
    assert history.deliveries[1].requirement_revision_id != history.scopes_by_delivery["DEL-2"][0].system_version


def test_legacy_delivery_auto_materializes_revision_lineage() -> None:
    store = _store()
    delivery = PostgresRequirementDeliveryRepository(store)
    revisions = PostgresRequirementRevisionRepository(store)
    delivery.create_requirement(Requirement(requirement_id="REQ", title="兼容需求", created_at=1))
    delivery.create_batch(ProductionBatch(production_batch_id="PB1", production_date="2026-11-15", name="PB1", created_at=1))
    delivery.create_batch(ProductionBatch(production_batch_id="PB2", production_date="2026-12-20", name="PB2", created_at=1))

    first = delivery.create_delivery(
        RequirementDelivery(delivery_id="DEL1", production_batch_id="PB1", requirement_id="REQ", created_at=2, updated_at=2)
    )
    second = delivery.create_delivery(
        RequirementDelivery(
            delivery_id="DEL2",
            production_batch_id="PB2",
            requirement_id="REQ",
            continuation_of_delivery_id="DEL1",
            created_at=3,
            updated_at=3,
        )
    )
    assert first.requirement_revision_id and first.scope_revision_id
    assert second.requirement_revision_id and second.scope_revision_id
    assert revisions.get_requirement_revision(second.requirement_revision_id).parent_requirement_revision_id == first.requirement_revision_id
    assert revisions.get_scope_revision(second.scope_revision_id).parent_scope_revision_id == first.scope_revision_id


def test_invalid_explicit_revision_binding_rolls_back_delivery() -> None:
    store = _store()
    delivery = PostgresRequirementDeliveryRepository(store)
    revisions = PostgresRequirementRevisionRepository(store)
    delivery.create_requirement(Requirement(requirement_id="REQ-A", title="A", created_at=1))
    delivery.create_requirement(Requirement(requirement_id="REQ-B", title="B", created_at=1))
    delivery.create_batch(ProductionBatch(production_batch_id="PB", production_date="2026-11-15", name="PB", created_at=1))
    revisions.create_requirement_revision(
        RequirementRevision(requirement_revision_id="REQ-B-V1", requirement_id="REQ-B", revision_label="V1", created_at=1)
    )
    revisions.create_scope_revision(
        ScopeRevision(scope_revision_id="REQ-B-SR1", requirement_revision_id="REQ-B-V1", revision_label="SR1", created_at=1)
    )
    try:
        delivery.create_delivery(
            RequirementDelivery(
                delivery_id="BAD",
                production_batch_id="PB",
                requirement_id="REQ-A",
                requirement_revision_id="REQ-B-V1",
                scope_revision_id="REQ-B-SR1",
                created_at=2,
                updated_at=2,
            )
        )
        raise AssertionError("revision mismatch must fail")
    except ValueError as exc:
        assert str(exc) == "DELIVERY_REQUIREMENT_REVISION_MISMATCH"
    assert delivery.get_delivery("BAD") is None
    assert revisions.get_delivery_binding("BAD") is None


def test_api_freezes_revision_snapshot_into_test_run() -> None:
    client, _store_value = _client()
    assert client.post(
        "/api/v1/production-batches",
        json={"production_batch_id": "PB", "production_date": "2026-11-15", "name": "投产"},
    ).status_code == 201
    assert client.post("/api/v1/requirements", json={"requirement_id": "REQ", "title": "需求"}).status_code == 201
    assert client.post(
        "/api/v1/requirements/REQ/revisions",
        json={"requirement_revision_id": "REQ-V2", "revision_label": "V2"},
    ).status_code == 201
    assert client.post(
        "/api/v1/requirement-revisions/REQ-V2/scope-revisions",
        json={"scope_revision_id": "REQ-V2-SR2", "revision_label": "SR2"},
    ).status_code == 201
    created_delivery = client.post(
        "/api/v1/production-batches/PB/requirements/REQ/deliveries",
        json={
            "delivery_id": "DEL",
            "requirement_revision_id": "REQ-V2",
            "scope_revision_id": "REQ-V2-SR2",
        },
    )
    assert created_delivery.status_code == 201, created_delivery.text
    assert created_delivery.json()["requirement_revision_id"] == "REQ-V2"
    assert client.post(
        "/api/v1/requirement-deliveries/DEL/scopes",
        json={"scope_id": "SCOPE-A", "system_id": "SYS-A", "system_version": "A-1.8.0", "sst_id": "SST-A"},
    ).status_code == 201
    assert client.post(
        "/api/v1/production-batches/PB/test-rounds",
        json={"test_round_id": "ROUND", "delivery_ids": ["DEL"]},
    ).status_code == 201
    started = client.post(
        "/api/v1/production-batches/PB/test-rounds/ROUND/test-run",
        json={"test_run_id": "RUN"},
    )
    assert started.status_code == 201, started.text
    payload = started.json()["test_run"]["payload"]
    assert payload["requirement_revision_ids"] == ["REQ-V2"]
    assert payload["scope_revision_ids"] == ["REQ-V2-SR2"]
    assert payload["revision_snapshot_truth"] == "FROZEN_AT_TEST_ROUND_START"
    assert payload["delivery_revision_bindings"] == [
        {
            "delivery_id": "DEL",
            "requirement_revision_id": "REQ-V2",
            "scope_revision_id": "REQ-V2-SR2",
            "delivery_scope_ids": ["SCOPE-A"],
        }
    ]


def _run_direct() -> None:
    test_requirement_v1_v2_are_distinct_from_system_versions()
    test_legacy_delivery_auto_materializes_revision_lineage()
    test_invalid_explicit_revision_binding_rolls_back_delivery()
    test_api_freezes_revision_snapshot_into_test_run()
    print("RC8_REQUIREMENT_REVISION_MODEL_PASS")


if __name__ == "__main__":
    _run_direct()
