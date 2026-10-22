#!/usr/bin/env python3
"""Real PostgreSQL concurrency proof for production-date TestRound allocation."""
from __future__ import annotations

import os
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rc8_center.delivery import (
    ProductionBatch,
    Requirement,
    RequirementDelivery,
    RequirementDeliveryScope,
)
from rc8_center.infrastructure import (
    PostgresRequirementDeliveryRepository,
    PostgresStore,
    PostgresTestRoundRepository,
    build_engine,
)


def main() -> int:
    store = PostgresStore(build_engine(os.environ["RC8_DATABASE_URL"]))
    delivery_repo = PostgresRequirementDeliveryRepository(store)
    round_repo = PostgresTestRoundRepository(store)

    suffix = uuid.uuid4().hex[:10]
    batch_id = "PB-CONCURRENT-%s" % suffix
    requirement_id = "REQ-CONCURRENT-%s" % suffix
    delivery_id = "DEL-CONCURRENT-%s" % suffix
    scope_id = "SCOPE-CONCURRENT-%s" % suffix

    delivery_repo.create_batch(
        ProductionBatch(
            production_batch_id=batch_id,
            production_date="2026-11-15",
            name="Concurrent TestRound allocation",
            created_at=100,
        )
    )
    delivery_repo.create_requirement(
        Requirement(
            requirement_id=requirement_id,
            title="并发测试轮次分配验证",
            created_at=100,
        )
    )
    delivery_repo.create_delivery(
        RequirementDelivery(
            delivery_id=delivery_id,
            production_batch_id=batch_id,
            requirement_id=requirement_id,
            created_at=100,
            updated_at=100,
        )
    )
    delivery_repo.create_scope(
        RequirementDeliveryScope(
            scope_id=scope_id,
            delivery_id=delivery_id,
            system_id="PFC",
            system_version="concurrency-fixture",
            application_id="cfg-center",
            sst_id="SST-CONCURRENT",
            created_at=100,
        )
    )

    worker_count = 6
    barrier = threading.Barrier(worker_count)

    def create_one(worker_no: int):
        barrier.wait(timeout=10)
        value, links = round_repo.create_next_round(
            batch_id,
            [delivery_id],
            name="并发创建-%s" % worker_no,
            payload={"worker_no": worker_no},
        )
        assert len(links) == 1
        assert links[0].delivery_id == delivery_id
        return value

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        values = list(executor.map(create_one, range(1, worker_count + 1)))

    round_nos = sorted(value.round_no for value in values)
    round_ids = {value.test_round_id for value in values}
    assert round_nos == list(range(1, worker_count + 1)), round_nos
    assert len(round_ids) == worker_count, round_ids

    persisted = round_repo.list_rounds(batch_id)
    assert [value.round_no for value in persisted] == list(range(1, worker_count + 1))
    assert {value.test_round_id for value in persisted} == round_ids
    for value in persisted:
        links = round_repo.list_round_deliveries(value.test_round_id)
        assert len(links) == 1
        assert links[0].delivery_id == delivery_id

    print({
        "status": "TEST_ROUND_CONCURRENT_ALLOCATION_VERIFIED",
        "production_batch_id": batch_id,
        "workers": worker_count,
        "round_nos": round_nos,
        "unique_round_ids": len(round_ids),
        "truth_note": "ProductionBatch row lock serialized next-round allocation on real PostgreSQL.",
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
