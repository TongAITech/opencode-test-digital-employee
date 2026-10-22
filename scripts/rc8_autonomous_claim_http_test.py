#!/usr/bin/env python3
"""End-to-end TestRound -> Mission bootstrap -> ID-free Node claim proof."""
from __future__ import annotations

import os
import time
import uuid

import httpx

from rc8_node.autonomous_claim_client import AutonomousClaimClient


def _wait_ready(client: httpx.Client) -> None:
    deadline = time.time() + 30
    last = None
    while time.time() < deadline:
        try:
            response = client.get("/health")
            last = response.text
            if response.status_code == 200:
                return
        except Exception as exc:  # pragma: no cover - process startup timing
            last = str(exc)
        time.sleep(0.25)
    raise AssertionError("CENTER_NOT_READY:%s" % last)


def _post(client: httpx.Client, path: str, payload: dict, expected: int = 201):
    response = client.post(path, json=payload)
    assert response.status_code == expected, (path, response.status_code, response.text)
    return response.json()


def main() -> int:
    base_url = os.environ.get("RC8_CENTER_URL", "http://127.0.0.1:18080").rstrip("/")
    suffix = uuid.uuid4().hex[:10]
    batch_id = "PB-HTTP-%s" % suffix
    requirement_id = "REQ-HTTP-%s" % suffix
    delivery_id = "DEL-HTTP-%s" % suffix
    round_id = "ROUND-HTTP-%s" % suffix
    run_id = "TR-HTTP-%s" % suffix
    node_a = "NODE-HTTP-A-%s" % suffix
    node_b = "NODE-HTTP-B-%s" % suffix

    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        _wait_ready(client)
        _post(
            client,
            "/api/v1/production-batches",
            {"production_batch_id": batch_id, "production_date": "2026-11-15", "name": "HTTP autonomous mission"},
        )
        _post(
            client,
            "/api/v1/requirements",
            {"requirement_id": requirement_id, "title": "HTTP autonomous requirement"},
        )
        _post(
            client,
            "/api/v1/production-batches/%s/requirements/%s/deliveries" % (batch_id, requirement_id),
            {"delivery_id": delivery_id},
        )
        scope_ids = []
        for number in (1, 2):
            scope_id = "SCOPE-HTTP-%s-%s" % (number, suffix)
            scope_ids.append(scope_id)
            _post(
                client,
                "/api/v1/requirement-deliveries/%s/scopes" % delivery_id,
                {
                    "scope_id": scope_id,
                    "system_id": "PFC",
                    "system_version": "HTTP-V1",
                    "application_id": "cfg-%s" % number,
                    "sst_id": "SST-HTTP-%s" % number,
                },
            )

        created_round = _post(
            client,
            "/api/v1/production-batches/%s/test-rounds" % batch_id,
            {"test_round_id": round_id, "delivery_ids": [delivery_id]},
        )
        assert created_round["round"]["round_no"] == 1

        started = _post(
            client,
            "/api/v1/production-batches/%s/test-rounds/%s/test-run" % (batch_id, round_id),
            {"test_run_id": run_id},
        )
        run = started["test_run"]
        assert run["test_round_id"] == round_id
        assert run["payload"]["mission_stage_count"] == 26
        ready_stage_ids = set(run["payload"]["mission_initial_ready_stage_ids"])
        ready_work_ids = set(run["payload"]["mission_initial_work_item_ids"])
        assert len(ready_stage_ids) == 2
        assert len(ready_work_ids) == 2

        for node_id in (node_a, node_b):
            _post(
                client,
                "/api/v1/nodes/register",
                {
                    "node_id": node_id,
                    "operator_ref": "ci",
                    "os_family": "linux",
                    "architecture": "x86_64",
                    "shell": "bash",
                    "registered_at": 1,
                },
                expected=200,
            )

    # The Nodes do not receive or guess WorkItem IDs. They ask only for next
    # compatible work inside this TestRun.
    claim_a = AutonomousClaimClient(base_url, node_a).claim_next(test_run_id=run_id)
    claim_b = AutonomousClaimClient(base_url, node_b).claim_next(test_run_id=run_id)
    assert claim_a.claimed is True
    assert claim_b.claimed is True
    assert claim_a.work_item_id and claim_b.work_item_id
    assert claim_a.work_item_id != claim_b.work_item_id
    assert {claim_a.work_item_id, claim_b.work_item_id} == ready_work_ids
    assert claim_a.stage == claim_b.stage == "SCOPE_INTAKE"
    assert {claim_a.stage_instance_id, claim_b.stage_instance_id} == ready_stage_ids
    assert claim_a.lease_id and claim_b.lease_id
    assert claim_a.truth_note == claim_b.truth_note == "POSTGRES_CANDIDATE_REDIS_LEASE_CAS_POSTGRES_MIRROR"

    print({
        "status": "RC8_TEST_ROUND_TO_ID_FREE_NODE_CLAIM_PASS",
        "test_run_id": run_id,
        "test_round_id": round_id,
        "scopes": scope_ids,
        "claimed_work_items": sorted([claim_a.work_item_id, claim_b.work_item_id]),
        "stage_instances": sorted([claim_a.stage_instance_id, claim_b.stage_instance_id]),
        "truth_note": "Nodes claimed work without caller-supplied WorkItem IDs; lease truth remains PostgreSQL + Redis.",
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
