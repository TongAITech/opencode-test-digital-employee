#!/usr/bin/env python3
"""End-to-end proof of evidence-gated autonomous Stage handoff and failure.

Real chain under Uvicorn/PostgreSQL/Redis:
ProductionDate -> TestRound -> Mission bootstrap -> ID-free claim -> Stage lease/start
-> Center-owned R1 ATTEMPT_STARTED -> AVAILABLE Artifact -> ATTEMPT_COMPLETED -> WorkItem complete
-> source Stage COMPLETED -> downstream Stage READY -> downstream WorkItem materialized
-> Node claims the downstream WorkItem without receiving its ID
-> failure request is rejected before terminal Attempt evidence
-> FAILED_RUNTIME Attempt + AVAILABLE failure Artifact -> WorkItem FAILED
-> Stage FAILED_RUNTIME -> lease released -> no downstream Stage unlock.
"""
from __future__ import annotations

import hashlib
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
            if response.status_code == 200 and response.json().get("status") == "READY":
                return
        except Exception as exc:  # pragma: no cover - process startup timing
            last = str(exc)
        time.sleep(0.25)
    raise AssertionError("CENTER_NOT_READY:%s" % last)


def _post(client: httpx.Client, path: str, payload: dict, expected: int = 200):
    response = client.post(path, json=payload)
    assert response.status_code == expected, (path, response.status_code, response.text)
    return response.json()


def _next_sequence(client: httpx.Client, *, run_id: str, node_id: str) -> int:
    response = client.get("/api/v1/test-runs/%s/nodes/%s/runtime-sequence" % (run_id, node_id))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["next_sequence"] == body["latest_sequence"] + 1
    return int(body["next_sequence"])


def _runtime_payload(*, lease_id: str, event_id: str, run_id: str, work_id: str,
                     node_id: str, stage_id: str, event_type: str, sequence: int,
                     attempt_id: str, data: dict) -> dict:
    values = {
        "lease_id": lease_id,
        "event_id": event_id,
        "test_run_id": run_id,
        "work_item_id": work_id,
        "node_id": node_id,
        "producer_kind": "WORKER",
        "producer_ref": "autonomous-http-worker",
        "event_type": event_type,
        "sequence": sequence,
        "attempt_id": attempt_id,
        "refs": ["stage:%s" % stage_id],
        "data": dict(data),
        "occurred_at": 1000 + sequence,
    }
    values["data"]["stage_instance_id"] = stage_id
    return values


def _upload_bytes(
    client: httpx.Client,
    *,
    lease_id: str,
    artifact_id: str,
    run_id: str,
    work_id: str,
    node_id: str,
    stage_id: str,
    attempt_id: str,
    kind: str,
    file_name: str,
    content: bytes,
    created_at: int,
):
    digest = hashlib.sha256(content).hexdigest()
    begun = _post(client, "/api/v1/artifacts/begin", {
        "lease_id": lease_id,
        "artifact_id": artifact_id,
        "test_run_id": run_id,
        "work_item_id": work_id,
        "node_id": node_id,
        "kind": kind,
        "producer_kind": "WORKER",
        "producer_ref": "autonomous-http-worker",
        "file_name": file_name,
        "sha256": digest,
        "size_bytes": len(content),
        "attempt_id": attempt_id,
        "refs": ["stage:%s" % stage_id],
        "metadata": {"stage_id": stage_id},
        "created_at": created_at,
    }, expected=201)
    assert begun["offset"] == 0
    uploaded = client.put(
        "/api/v1/artifacts/%s/content?offset=0" % artifact_id,
        content=content,
        headers={
            "Content-Type": "application/octet-stream",
            "X-RC8-Node-Id": node_id,
            "X-RC8-Lease-Id": lease_id,
        },
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["offset"] == len(content)
    available = _post(
        client,
        "/api/v1/artifacts/%s/complete" % artifact_id,
        {"node_id": node_id, "lease_id": lease_id},
    )
    assert available["manifest"]["availability"] == "AVAILABLE"
    return available


def main() -> int:
    base_url = os.environ.get("RC8_CENTER_URL", "http://127.0.0.1:18080").rstrip("/")
    suffix = uuid.uuid4().hex[:10]
    batch_id = "PB-PROGRESS-%s" % suffix
    req_id = "REQ-PROGRESS-%s" % suffix
    delivery_id = "DEL-PROGRESS-%s" % suffix
    scope_id = "SCOPE-PROGRESS-%s" % suffix
    round_id = "ROUND-PROGRESS-%s" % suffix
    run_id = "TR-PROGRESS-%s" % suffix
    node_id = "NODE-PROGRESS-%s" % suffix

    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        _wait_ready(client)
        _post(client, "/api/v1/production-batches", {
            "production_batch_id": batch_id,
            "production_date": "2026-11-15",
            "name": "autonomous progression",
        }, expected=201)
        _post(client, "/api/v1/requirements", {
            "requirement_id": req_id,
            "title": "自动推进需求",
        }, expected=201)
        created_delivery = _post(client, "/api/v1/production-batches/%s/requirements/%s/deliveries" % (batch_id, req_id), {
            "delivery_id": delivery_id,
        }, expected=201)
        requirement_revision_id = created_delivery["requirement_revision_id"]
        scope_revision_id = created_delivery["scope_revision_id"]
        assert requirement_revision_id and scope_revision_id
        _post(client, "/api/v1/requirement-deliveries/%s/scopes" % delivery_id, {
            "scope_id": scope_id,
            "system_id": "PFC",
            "system_version": "V1",
            "application_id": "cfg-center",
            "sst_id": "SST-PROGRESS",
        }, expected=201)
        _post(client, "/api/v1/production-batches/%s/test-rounds" % batch_id, {
            "test_round_id": round_id,
            "delivery_ids": [delivery_id],
        }, expected=201)
        started = _post(
            client,
            "/api/v1/production-batches/%s/test-rounds/%s/test-run" % (batch_id, round_id),
            {"test_run_id": run_id},
            expected=201,
        )
        assert started["test_run"]["payload"]["mission_stage_count"] == 14
        assert started["test_run"]["payload"]["requirement_revision_ids"] == [requirement_revision_id]
        assert started["test_run"]["payload"]["scope_revision_ids"] == [scope_revision_id]
        initial_stage_id = started["test_run"]["payload"]["mission_initial_ready_stage_ids"][0]

        _post(client, "/api/v1/nodes/register", {
            "node_id": node_id,
            "operator_ref": "ci-autonomous",
            "os_family": "linux",
            "architecture": "x86_64",
            "shell": "bash",
            "registered_at": 1,
        })

    claimant = AutonomousClaimClient(base_url, node_id)
    first = claimant.claim_next(test_run_id=run_id)
    assert first.claimed is True
    assert first.stage == "SCOPE_INTAKE"
    assert first.stage_instance_id == initial_stage_id
    assert first.work_item_id and first.lease_id
    first_work_id = first.work_item_id
    first_lease_id = first.lease_id

    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        started_work = _post(
            client,
            "/api/v1/work-items/%s/start" % first_work_id,
            {"node_id": node_id, "lease_id": first_lease_id},
        )
        assert started_work["work_item"]["state"] == "RUNNING"

        attempt_id = first_lease_id
        terminal_sequence = _next_sequence(client, run_id=run_id, node_id=node_id)
        assert terminal_sequence >= 1

        content = ("scope intake evidence %s" % suffix).encode("utf-8")
        artifact_id = "ART-PROGRESS-%s" % suffix
        _upload_bytes(
            client,
            lease_id=first_lease_id,
            artifact_id=artifact_id,
            run_id=run_id,
            work_id=first_work_id,
            node_id=node_id,
            stage_id=initial_stage_id,
            attempt_id=attempt_id,
            kind="SCOPE_INTAKE_EVIDENCE",
            file_name="scope-intake.txt",
            content=content,
            created_at=1002,
        )

        completed_attempt = _post(client, "/api/v1/runtime-events", _runtime_payload(
            lease_id=first_lease_id,
            event_id="EVT-COMPLETE-%s" % suffix,
            run_id=run_id,
            work_id=first_work_id,
            node_id=node_id,
            stage_id=initial_stage_id,
            event_type="ATTEMPT_COMPLETED",
            sequence=terminal_sequence,
            attempt_id=attempt_id,
            data={
                "input_snapshot_ref": "scope-snapshot:%s" % scope_id,
                "evidence_refs": ["artifact:%s" % artifact_id],
                "finished_at": 1003,
            },
        ))
        assert completed_attempt["projection"]["projection"]["status"] == "PROJECTED"

        completed_work = _post(
            client,
            "/api/v1/work-items/%s/complete" % first_work_id,
            {"node_id": node_id, "lease_id": first_lease_id},
        )
        assert completed_work["work_item"]["state"] == "COMPLETED"

        governance = client.get("/api/v1/test-runs/%s/governance" % run_id)
        assert governance.status_code == 200, governance.text
        body = governance.json()
        by_id = {item["stage_instance_id"]: item for item in body["stages"]}
        assert by_id[initial_stage_id]["state"] == "COMPLETED"
        ready_after = [
            item for item in body["stages"]
            if item["state"] == "READY" and item["stage_type"] == "REQUIREMENT_ANALYSIS"
        ]
        assert len(ready_after) == 1
        next_stage_id = ready_after[0]["stage_instance_id"]

    second = claimant.claim_next(test_run_id=run_id)
    assert second.claimed is True
    assert second.stage == "REQUIREMENT_ANALYSIS"
    assert second.stage_instance_id == next_stage_id
    assert second.work_item_id and second.work_item_id != first_work_id
    assert second.lease_id
    second_work_id = second.work_item_id
    second_lease_id = second.lease_id
    second_scope_refs = set((second.work_item or {}).get("identity", {}).get("scope_refs") or [])
    assert "requirement-revision:%s" % requirement_revision_id in second_scope_refs
    assert "scope-revision:%s" % scope_revision_id in second_scope_refs

    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        started_analysis = _post(
            client,
            "/api/v1/work-items/%s/start" % second_work_id,
            {"node_id": node_id, "lease_id": second_lease_id},
        )
        assert started_analysis["work_item"]["state"] == "RUNNING"

        premature = client.post(
            "/api/v1/work-items/%s/fail" % second_work_id,
            json={"node_id": node_id, "lease_id": second_lease_id},
        )
        assert premature.status_code == 409, premature.text
        assert "MISSION_WORK_ITEM_FAILURE_REQUIRES_PROJECTED_TERMINAL_ATTEMPT" in premature.text

        failed_attempt_id = second_lease_id
        failed_sequence = _next_sequence(client, run_id=run_id, node_id=node_id)
        assert failed_sequence > terminal_sequence

        failure_content = ("simulated DSH requirement worker failure %s" % suffix).encode("utf-8")
        failure_artifact_id = "ART-REQ-FAIL-%s" % suffix
        _upload_bytes(
            client,
            lease_id=second_lease_id,
            artifact_id=failure_artifact_id,
            run_id=run_id,
            work_id=second_work_id,
            node_id=node_id,
            stage_id=next_stage_id,
            attempt_id=failed_attempt_id,
            kind="REQUIREMENT_ANALYSIS_FAILURE_EVIDENCE",
            file_name="requirement-analysis-failure.txt",
            content=failure_content,
            created_at=1005,
        )

        failed_attempt = _post(client, "/api/v1/runtime-events", _runtime_payload(
            lease_id=second_lease_id,
            event_id="EVT-REQ-FAILED-%s" % suffix,
            run_id=run_id,
            work_id=second_work_id,
            node_id=node_id,
            stage_id=next_stage_id,
            event_type="ATTEMPT_FAILED_RUNTIME",
            sequence=failed_sequence,
            attempt_id=failed_attempt_id,
            data={
                "input_snapshot_ref": "requirement-revision:%s" % requirement_revision_id,
                "evidence_refs": ["artifact:%s" % failure_artifact_id],
                "failure_ownership": "MODEL",
                "finished_at": 1006,
            },
        ))
        assert failed_attempt["projection"]["projection"]["status"] == "PROJECTED"

        failed_work = _post(
            client,
            "/api/v1/work-items/%s/fail" % second_work_id,
            {"node_id": node_id, "lease_id": second_lease_id},
        )
        assert failed_work["work_item"]["state"] == "FAILED"
        assert failed_work["work_item"]["lease_id"] is None
        assert failed_work["truth_note"] == "TERMINAL_STATE_DERIVED_FROM_R1_PROJECTED_ATTEMPT_AND_AVAILABLE_EVIDENCE"

        governance = client.get("/api/v1/test-runs/%s/governance" % run_id)
        assert governance.status_code == 200, governance.text
        body = governance.json()
        by_id = {item["stage_instance_id"]: item for item in body["stages"]}
        assert by_id[next_stage_id]["state"] == "FAILED_RUNTIME"
        assert not [item for item in body["stages"] if item["state"] == "READY"]

    no_next = claimant.claim_next(test_run_id=run_id)
    assert no_next.claimed is False

    print({
        "status": "RC8_AUTONOMOUS_HANDOFF_AND_EVIDENCED_FAILURE_PASS",
        "production_date": "2026-11-15",
        "test_round_id": round_id,
        "test_run_id": run_id,
        "requirement_revision_id": requirement_revision_id,
        "scope_revision_id": scope_revision_id,
        "source_stage": initial_stage_id,
        "source_work_item": first_work_id,
        "analysis_stage": next_stage_id,
        "analysis_work_item": second_work_id,
        "analysis_terminal_state": "FAILED_RUNTIME",
        "truth_note": "Downstream work was auto-claimed with frozen revision refs; Center-owned Attempt identity was reused by worker evidence and terminal facts; failure released the lease without unlocking successors.",
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
