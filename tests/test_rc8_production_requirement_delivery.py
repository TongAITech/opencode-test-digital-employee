from __future__ import annotations

from sqlalchemy import create_engine

from rc8_center.delivery import (
    ProductionBatch,
    Requirement,
    RequirementDelivery,
    RequirementDeliveryScope,
    RequirementDeliveryState,
)
from rc8_center.infrastructure import Base, PostgresStore
from rc8_center.infrastructure.postgres_delivery import PostgresRequirementDeliveryRepository


def _repo() -> PostgresRequirementDeliveryRepository:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return PostgresRequirementDeliveryRepository(PostgresStore(engine))


def test_requirement_can_complete_in_one_production_batch() -> None:
    repo = _repo()
    repo.create_batch(ProductionBatch("PB-20261115", "2026-11-15", "2026-11-15投产", created_at=1))
    repo.create_requirement(Requirement("REQ-001", "一次投产即可完成的需求", created_at=1))
    repo.create_delivery(
        RequirementDelivery(
            "DEL-001",
            "PB-20261115",
            "REQ-001",
            state=RequirementDeliveryState.COMPLETED,
            created_at=2,
            updated_at=2,
        )
    )
    repo.create_scope(
        RequirementDeliveryScope(
            "SCOPE-001",
            "DEL-001",
            "SYS-A",
            "A-1.8.0",
            "SST-A101",
            application_id="cfg-center",
            created_at=3,
        )
    )

    history = repo.requirement_history("REQ-001")
    assert history.completed_in_single_batch is True
    assert history.spans_multiple_batches is False
    assert history.current_delivery_state == RequirementDeliveryState.COMPLETED
    assert len(history.deliveries) == 1
    assert history.scopes_by_delivery["DEL-001"][0].system_version == "A-1.8.0"


def test_requirement_can_span_multiple_production_batches_without_forced_revision() -> None:
    repo = _repo()
    repo.create_batch(ProductionBatch("PB-1", "2026-11-15", "第一批", created_at=1))
    repo.create_batch(ProductionBatch("PB-2", "2026-12-20", "第二批", created_at=2))
    repo.create_requirement(Requirement("REQ-002", "跨批次持续交付需求", created_at=1))
    repo.create_delivery(
        RequirementDelivery(
            "DEL-1",
            "PB-1",
            "REQ-002",
            state=RequirementDeliveryState.PARTIAL,
            created_at=3,
            updated_at=3,
        )
    )
    repo.create_scope(RequirementDeliveryScope("S-1", "DEL-1", "SYS-A", "A-1.0", "SST-1", created_at=4))
    repo.create_delivery(
        RequirementDelivery(
            "DEL-2",
            "PB-2",
            "REQ-002",
            state=RequirementDeliveryState.COMPLETED,
            continuation_of_delivery_id="DEL-1",
            created_at=5,
            updated_at=5,
        )
    )
    repo.create_scope(RequirementDeliveryScope("S-2", "DEL-2", "SYS-B", "B-2.0", "SST-2", created_at=6))

    history = repo.requirement_history("REQ-002")
    assert history.spans_multiple_batches is True
    assert history.completed_in_single_batch is False
    assert [item.delivery_id for item in history.deliveries] == ["DEL-1", "DEL-2"]
    assert history.deliveries[0].state == RequirementDeliveryState.PARTIAL
    assert history.deliveries[1].state == RequirementDeliveryState.COMPLETED
    assert history.scopes_by_delivery["DEL-1"][0].system_version == "A-1.0"
    assert history.scopes_by_delivery["DEL-2"][0].system_version == "B-2.0"


def test_one_delivery_can_cover_multiple_system_versions_and_ssts() -> None:
    repo = _repo()
    repo.create_batch(ProductionBatch("PB", "2026-11-15", "投产批次", created_at=1))
    repo.create_requirement(Requirement("REQ", "多系统多SST需求", created_at=1))
    repo.create_delivery(RequirementDelivery("DEL", "PB", "REQ", created_at=2, updated_at=2))

    repo.create_scope(RequirementDeliveryScope("S1", "DEL", "SYS-A", "A-1.8.0", "SST-A1", application_id="cfg-center", created_at=3))
    repo.create_scope(RequirementDeliveryScope("S2", "DEL", "SYS-A", "A-1.8.0", "SST-A2", application_id="cfg-data", created_at=4))
    repo.create_scope(RequirementDeliveryScope("S3", "DEL", "SYS-B", "B-3.2.0", "SST-B1", application_id="cfg-admin", created_at=5))

    scopes = repo.list_scopes("DEL")
    assert len(scopes) == 3
    assert {(s.system_id, s.system_version, s.sst_id) for s in scopes} == {
        ("SYS-A", "A-1.8.0", "SST-A1"),
        ("SYS-A", "A-1.8.0", "SST-A2"),
        ("SYS-B", "B-3.2.0", "SST-B1"),
    }


def test_duplicate_scope_is_rejected_even_with_different_scope_id() -> None:
    repo = _repo()
    repo.create_batch(ProductionBatch("PB", "2026-11-15", "投产批次", created_at=1))
    repo.create_requirement(Requirement("REQ", "需求", created_at=1))
    repo.create_delivery(RequirementDelivery("DEL", "PB", "REQ", created_at=2, updated_at=2))
    first = RequirementDeliveryScope("S1", "DEL", "SYS", "1.0", "SST", application_id=None, created_at=3)
    repo.create_scope(first)
    try:
        repo.create_scope(RequirementDeliveryScope("S2", "DEL", "SYS", "1.0", "SST", application_id=None, created_at=4))
    except ValueError as exc:
        assert str(exc) == "DELIVERY_SCOPE_DUPLICATE"
    else:
        raise AssertionError("duplicate delivery scope must fail closed")


def test_scope_identity_is_compact_even_at_identifier_limits() -> None:
    scope = RequirementDeliveryScope(
        "S" * 220,
        "D" * 200,
        "系统" * 120,
        "版本" * 120,
        "SST" * 80,
        application_id="应用" * 120,
    )
    assert len(scope.scope_identity) == 64
    assert scope.scope_identity == RequirementDeliveryScope(
        "DIFFERENT-SCOPE-ID",
        "D" * 200,
        "系统" * 120,
        "版本" * 120,
        "SST" * 80,
        application_id="应用" * 120,
    ).scope_identity


def test_same_requirement_cannot_be_duplicated_inside_one_batch() -> None:
    repo = _repo()
    repo.create_batch(ProductionBatch("PB", "2026-11-15", "投产批次", created_at=1))
    repo.create_requirement(Requirement("REQ", "需求", created_at=1))
    repo.create_delivery(RequirementDelivery("DEL-1", "PB", "REQ", created_at=2, updated_at=2))
    try:
        repo.create_delivery(RequirementDelivery("DEL-2", "PB", "REQ", created_at=3, updated_at=3))
    except ValueError as exc:
        assert str(exc) == "REQUIREMENT_ALREADY_PARTICIPATES_IN_BATCH"
    else:
        raise AssertionError("same requirement must have one delivery participation per batch")


def test_completed_delivery_history_cannot_be_reopened() -> None:
    repo = _repo()
    repo.create_batch(ProductionBatch("PB", "2026-11-15", "投产批次", created_at=1))
    repo.create_requirement(Requirement("REQ", "需求", created_at=1))
    repo.create_delivery(
        RequirementDelivery(
            "DEL",
            "PB",
            "REQ",
            state=RequirementDeliveryState.COMPLETED,
            created_at=2,
            updated_at=2,
        )
    )
    try:
        repo.transition_delivery("DEL", RequirementDeliveryState.IN_PROGRESS, now=3)
    except ValueError as exc:
        assert str(exc) == "REQUIREMENT_DELIVERY_TERMINAL_STATE_IMMUTABLE"
    else:
        raise AssertionError("completed delivery must remain historical truth")


def _run_direct() -> None:
    tests = [
        test_requirement_can_complete_in_one_production_batch,
        test_requirement_can_span_multiple_production_batches_without_forced_revision,
        test_one_delivery_can_cover_multiple_system_versions_and_ssts,
        test_duplicate_scope_is_rejected_even_with_different_scope_id,
        test_scope_identity_is_compact_even_at_identifier_limits,
        test_same_requirement_cannot_be_duplicated_inside_one_batch,
        test_completed_delivery_history_cannot_be_reopened,
    ]
    for test in tests:
        test()
    print("RC8_PRODUCTION_REQUIREMENT_DELIVERY_CONTRACT_PASS")


if __name__ == "__main__":
    _run_direct()
