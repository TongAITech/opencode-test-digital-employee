from __future__ import annotations

import pytest
from sqlalchemy import create_engine

from rc8_center.delivery import (
    ProductionBatch,
    Requirement,
    RequirementDelivery,
    RequirementDeliveryState,
)
from rc8_center.infrastructure.postgres import Base, PostgresStore
from rc8_center.infrastructure.postgres_delivery import PostgresRequirementDeliveryRepository
from rc8_center.infrastructure.postgres_test_round import PostgresTestRoundRepository
from rc8_center.test_rounds import TestRound, TestRoundDelivery, TestRoundState


def _repos():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = PostgresStore(engine)
    Base.metadata.create_all(engine)
    return (
        PostgresRequirementDeliveryRepository(store),
        PostgresTestRoundRepository(store),
    )


def _seed_delivery(delivery_repo, *, batch_id="batch-2026-11-15", production_date="2026-11-15", delivery_id="delivery-r1-b1"):
    delivery_repo.create_batch(
        ProductionBatch(
            production_batch_id=batch_id,
            production_date=production_date,
            name=production_date,
            created_at=100,
        )
    )
    if delivery_repo.get_requirement("R001") is None:
        delivery_repo.create_requirement(Requirement(requirement_id="R001", title="需求1", created_at=100))
    value = RequirementDelivery(
        delivery_id=delivery_id,
        production_batch_id=batch_id,
        requirement_id="R001",
        created_at=100,
        updated_at=100,
    )
    delivery_repo.create_delivery(value)
    return value


def _create_completed_round(round_repo, delivery, round_no):
    round_value = TestRound(
        test_round_id=f"{delivery.production_batch_id}-round-{round_no}",
        production_batch_id=delivery.production_batch_id,
        round_no=round_no,
        name=f"第{round_no}轮测试",
        created_at=100 + round_no,
    )
    round_repo.create_round(round_value)
    round_repo.include_delivery(
        TestRoundDelivery(
            round_delivery_id=f"{round_value.test_round_id}-{delivery.delivery_id}",
            test_round_id=round_value.test_round_id,
            delivery_id=delivery.delivery_id,
            included_at=100 + round_no,
        )
    )
    round_repo.transition_round(round_value.test_round_id, TestRoundState.ACTIVE, now=200 + round_no)
    return round_repo.transition_round(round_value.test_round_id, TestRoundState.COMPLETED, now=300 + round_no)


def test_one_production_date_can_complete_after_many_test_rounds_without_becoming_continuous_delivery():
    delivery_repo, round_repo = _repos()
    delivery = _seed_delivery(delivery_repo)

    for round_no in range(1, 5):
        completed = _create_completed_round(round_repo, delivery, round_no)
        assert completed.state == TestRoundState.COMPLETED

    delivery_repo.transition_delivery(delivery.delivery_id, RequirementDeliveryState.COMPLETED, now=500)
    history = delivery_repo.requirement_history("R001")

    assert [item.round_no for item in round_repo.list_rounds(delivery.production_batch_id)] == [1, 2, 3, 4]
    assert history.completed_in_single_batch is True
    assert history.spans_multiple_batches is False
    assert len(history.deliveries) == 1


def test_requirement_is_continuous_only_when_it_enters_another_production_date_not_when_round_count_grows():
    delivery_repo, round_repo = _repos()
    first = _seed_delivery(delivery_repo)
    _create_completed_round(round_repo, first, 1)
    _create_completed_round(round_repo, first, 2)
    delivery_repo.transition_delivery(first.delivery_id, RequirementDeliveryState.PARTIAL, now=400)

    delivery_repo.create_batch(
        ProductionBatch(
            production_batch_id="batch-2026-12-10",
            production_date="2026-12-10",
            name="2026-12-10",
            created_at=500,
        )
    )
    second = RequirementDelivery(
        delivery_id="delivery-r1-b2",
        production_batch_id="batch-2026-12-10",
        requirement_id="R001",
        continuation_of_delivery_id=first.delivery_id,
        created_at=500,
        updated_at=500,
    )
    delivery_repo.create_delivery(second)
    _create_completed_round(round_repo, second, 1)

    history = delivery_repo.requirement_history("R001")
    assert history.spans_multiple_batches is True
    assert len(history.deliveries) == 2
    assert len(round_repo.list_rounds(first.production_batch_id)) == 2
    assert len(round_repo.list_rounds(second.production_batch_id)) == 1


def test_same_delivery_can_participate_in_multiple_rounds_of_same_production_date_and_history_is_preserved():
    delivery_repo, round_repo = _repos()
    delivery = _seed_delivery(delivery_repo)

    for round_no in (1, 2, 3):
        _create_completed_round(round_repo, delivery, round_no)

    rounds = round_repo.list_rounds(delivery.production_batch_id)
    assert [item.test_round_id for item in rounds] == [
        "batch-2026-11-15-round-1",
        "batch-2026-11-15-round-2",
        "batch-2026-11-15-round-3",
    ]
    assert all(len(round_repo.list_round_deliveries(item.test_round_id)) == 1 for item in rounds)


def test_cross_production_date_delivery_cannot_be_attached_to_round():
    delivery_repo, round_repo = _repos()
    first = _seed_delivery(delivery_repo)
    delivery_repo.create_batch(
        ProductionBatch(
            production_batch_id="batch-2026-12-10",
            production_date="2026-12-10",
            name="2026-12-10",
            created_at=500,
        )
    )
    round_repo.create_round(
        TestRound(
            test_round_id="batch-2026-12-10-round-1",
            production_batch_id="batch-2026-12-10",
            round_no=1,
            created_at=500,
        )
    )

    with pytest.raises(ValueError, match="TEST_ROUND_DELIVERY_PRODUCTION_DATE_MISMATCH"):
        round_repo.include_delivery(
            TestRoundDelivery(
                round_delivery_id="wrong-date-link",
                test_round_id="batch-2026-12-10-round-1",
                delivery_id=first.delivery_id,
                included_at=501,
            )
        )


def test_completing_test_round_does_not_complete_requirement_delivery():
    delivery_repo, round_repo = _repos()
    delivery = _seed_delivery(delivery_repo)
    _create_completed_round(round_repo, delivery, 1)

    persisted_delivery = delivery_repo.get_delivery(delivery.delivery_id)
    assert persisted_delivery is not None
    assert persisted_delivery.state == RequirementDeliveryState.PLANNED


def test_round_number_is_unique_per_production_date_and_can_restart_on_next_date():
    delivery_repo, round_repo = _repos()
    first = _seed_delivery(delivery_repo)
    round_repo.create_round(
        TestRound(
            test_round_id="round-a",
            production_batch_id=first.production_batch_id,
            round_no=1,
            created_at=100,
        )
    )
    with pytest.raises(ValueError, match="TEST_ROUND_NO_ALREADY_EXISTS_IN_PRODUCTION_DATE"):
        round_repo.create_round(
            TestRound(
                test_round_id="round-b",
                production_batch_id=first.production_batch_id,
                round_no=1,
                created_at=101,
            )
        )

    delivery_repo.create_batch(
        ProductionBatch(
            production_batch_id="batch-2026-12-10",
            production_date="2026-12-10",
            name="2026-12-10",
            created_at=200,
        )
    )
    round_repo.create_round(
        TestRound(
            test_round_id="round-next-date",
            production_batch_id="batch-2026-12-10",
            round_no=1,
            created_at=201,
        )
    )
    assert round_repo.get_round("round-next-date").round_no == 1


def test_round_state_is_independent_and_terminal_history_cannot_be_rewritten():
    round_value = TestRound(
        test_round_id="round-state",
        production_batch_id="batch-1",
        round_no=1,
        created_at=10,
    )
    active = round_value.transition_to(TestRoundState.ACTIVE, now=20)
    completed = active.transition_to(TestRoundState.COMPLETED, now=30)

    assert active.started_at == 20
    assert completed.completed_at == 30
    with pytest.raises(ValueError, match="TEST_ROUND_TERMINAL_STATE_IMMUTABLE"):
        completed.transition_to(TestRoundState.ACTIVE, now=40)
