#!/usr/bin/env python3
"""Real PostgreSQL + Redis proof for RC8 claim-next scheduling."""
from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from rc8_center.control_plane import WorkItemRecord, WorkItemState
from rc8_center.formal_control import FormalCenterControlPlane
from rc8_center.infrastructure import PostgresCenterRepository, PostgresStore, RedisCoordination, build_engine
from rc8_runtime import NodeIdentity, WorkItemIdentity


def _node(control: FormalCenterControlPlane, node_id: str) -> None:
    control.register_node(
        NodeIdentity(
            node_id=node_id,
            operator_ref="ci",
            os_family="linux",
            architecture="x86_64",
            shell="bash",
            registered_at=1,
        )
    )


def main() -> int:
    store = PostgresStore(build_engine(os.environ["RC8_DATABASE_URL"]))
    repository = PostgresCenterRepository(store)
    coordination = RedisCoordination.from_url(os.environ["RC8_REDIS_URL"])
    control = FormalCenterControlPlane(repository, coordination, object(), object())

    suffix = uuid.uuid4().hex[:10]
    run_id = "TR-CLAIM-%s" % suffix
    work_id = "WORK-CLAIM-%s" % suffix
    node_a = "NODE-A-%s" % suffix
    node_b = "NODE-B-%s" % suffix
    _node(control, node_a)
    _node(control, node_b)
    repository.upsert_work_item(
        WorkItemRecord(
            identity=WorkItemIdentity(
                work_item_id=work_id,
                test_run_id=run_id,
                stage="SCOPE_INTAKE",
                scope_refs=("delivery-scope:SCOPE-1",),
                required_capabilities=(),
            ),
            state=WorkItemState.READY,
        )
    )

    barrier = threading.Barrier(2)

    def claim(node_id: str):
        barrier.wait(timeout=10)
        return control.claim_next_work_item(node_id, test_run_id=run_id, ttl_seconds=60)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, [node_a, node_b]))

    winners = [value for value in results if value is not None]
    assert len(winners) == 1, results
    winner = winners[0]
    assert winner.identity.work_item_id == work_id
    assert winner.state == WorkItemState.LEASED
    assert winner.lease_owner_node_id in {node_a, node_b}
    assert winner.lease_id

    durable = repository.get_work_item(work_id)
    assert durable is not None
    assert durable.state == WorkItemState.LEASED
    assert durable.lease_owner_node_id == winner.lease_owner_node_id
    assert durable.lease_id == winner.lease_id

    active = coordination.lease_info("work-item", work_id)
    assert active is not None
    assert active["owner_id"] == winner.lease_owner_node_id
    assert active["lease_id"] == winner.lease_id

    # No second READY claim may appear while the active Redis lease exists.
    loser_id = node_b if winner.lease_owner_node_id == node_a else node_a
    assert control.claim_next_work_item(loser_id, test_run_id=run_id, ttl_seconds=60) is None

    print({
        "status": "RC8_CLAIM_NEXT_POSTGRES_REDIS_RACE_PASS",
        "test_run_id": run_id,
        "work_item_id": work_id,
        "winner": winner.lease_owner_node_id,
        "lease_id_present": bool(winner.lease_id),
        "truth_note": "Exactly one node won the existing Redis lease CAS; PostgreSQL durable mirror agrees.",
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
