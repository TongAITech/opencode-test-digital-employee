#!/usr/bin/env python3
"""Real HTTP proof that the formal Node can autonomously dispatch requirement work.

The node never receives WorkItem IDs from the test.  One stage-safe dispatcher
repeatedly calls claim-next and executes only its registered workers:
SCOPE_INTAKE -> REQUIREMENT_ANALYSIS#1 -> REQUIREMENT_SUFFICIENCY#1
-> REQUIREMENT_ANALYSIS#2 -> REQUIREMENT_SUFFICIENCY#2.

After the repair succeeds, CODE_ANALYSIS becomes READY but remains unclaimed
because this dispatcher does not implement that Stage.  This proves stage
whitelisting and Center capability routing are preserved at the product edge.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import httpx

from rc8_node.agent import HttpCenterClient
from rc8_node.autonomous_claim_client import AutonomousClaimClient
from rc8_node.autonomous_dispatcher import AutonomousWorkerDispatcher
from rc8_node.dsh_json_runner import DshJsonRunner
from rc8_node.formal_agent import FormalNodeAgent
from rc8_node.requirement_analysis_worker import RequirementAnalysisWorker
from rc8_node.requirement_sufficiency_worker import RequirementSufficiencyWorker
from rc8_node.scope_intake_worker import ScopeIntakeWorker
from rc8_runtime import NodeIdentity

from rc8_requirement_repair_reality_test import _governance, _post, _wait_ready
from rc8_requirement_repair_reality_v2_test import _analysis_valid_but_insufficient_dsh


def main() -> int:
    base_url = os.environ.get("RC8_CENTER_URL", "http://127.0.0.1:18080").rstrip("/")
    suffix = uuid.uuid4().hex[:10]
    batch_id = "PB-DISPATCH-%s" % suffix
    requirement_id = "REQ-DISPATCH-%s" % suffix
    requirement_revision_id = "REQREV-DISPATCH-%s" % suffix
    scope_revision_id = "SCOPEREV-DISPATCH-%s" % suffix
    delivery_id = "DEL-DISPATCH-%s" % suffix
    scope_id = "SCOPE-DISPATCH-%s" % suffix
    test_round_id = "ROUND-DISPATCH-%s" % suffix
    test_run_id = "TR-DISPATCH-%s" % suffix
    node_id = "NODE-DISPATCH-%s" % suffix

    with tempfile.TemporaryDirectory(prefix="rc8-autonomous-dispatch-") as temp:
        root = Path(temp)
        fake_dsh = root / "fake-dsh"
        dsh_state = root / "dsh-count.txt"
        _analysis_valid_but_insufficient_dsh(fake_dsh, dsh_state)

        with httpx.Client(base_url=base_url, timeout=30.0) as client:
            _wait_ready(client)
            _post(client, "/api/v1/production-batches", {
                "production_batch_id": batch_id,
                "production_date": "2026-11-15",
                "name": "autonomous requirement dispatch reality",
            }, expected=201)
            _post(client, "/api/v1/requirements", {
                "requirement_id": requirement_id,
                "title": "自主需求闭环验证",
            }, expected=201)
            _post(client, "/api/v1/requirements/%s/revisions" % requirement_id, {
                "requirement_revision_id": requirement_revision_id,
                "revision_label": "V2",
                "payload": {"source_refs": ["source:reqdoc#dispatch"]},
            }, expected=201)
            _post(client, "/api/v1/requirement-revisions/%s/scope-revisions" % requirement_revision_id, {
                "scope_revision_id": scope_revision_id,
                "revision_label": "SR2",
                "payload": {"source_refs": ["source:scope#dispatch"]},
            }, expected=201)
            _post(
                client,
                "/api/v1/production-batches/%s/requirements/%s/deliveries" % (batch_id, requirement_id),
                {
                    "delivery_id": delivery_id,
                    "requirement_revision_id": requirement_revision_id,
                    "scope_revision_id": scope_revision_id,
                },
                expected=201,
            )
            _post(client, "/api/v1/requirement-deliveries/%s/scopes" % delivery_id, {
                "scope_id": scope_id,
                "system_id": "PFC",
                "system_version": "SYS-V1",
                "application_id": "cfg-center",
                "sst_id": "SST-DISPATCH",
            }, expected=201)
            _post(client, "/api/v1/production-batches/%s/test-rounds" % batch_id, {
                "test_round_id": test_round_id,
                "delivery_ids": [delivery_id],
            }, expected=201)
            started = _post(
                client,
                "/api/v1/production-batches/%s/test-rounds/%s/test-run" % (batch_id, test_round_id),
                {"test_run_id": test_run_id},
                expected=201,
            )
            assert started["test_run"]["payload"]["requirement_revision_ids"] == [requirement_revision_id]
            assert started["test_run"]["payload"]["scope_revision_ids"] == [scope_revision_id]

        center = HttpCenterClient(base_url, timeout_seconds=30)
        identity = NodeIdentity(
            node_id=node_id,
            operator_ref="ci-autonomous-dispatch",
            os_family="linux",
            architecture="x86_64",
            shell="bash",
            registered_at=1,
        )
        agent = FormalNodeAgent(identity, center)
        agent.register()
        agent.heartbeat()
        dispatcher = AutonomousWorkerDispatcher(
            claimant=AutonomousClaimClient(base_url, node_id, timeout_seconds=30),
            workers={
                "SCOPE_INTAKE": ScopeIntakeWorker(
                    agent=agent,
                    work_dir=str(root / "scope-intake"),
                ),
                "REQUIREMENT_ANALYSIS": RequirementAnalysisWorker(
                    agent=agent,
                    dsh_runner=DshJsonRunner(
                        dsh_bin=str(fake_dsh),
                        patch_path="ci-autonomous-dispatch-patch",
                        cwd=str(root),
                        timeout_seconds=30,
                    ),
                    work_dir=str(root / "requirement-analysis"),
                ),
                "REQUIREMENT_SUFFICIENCY": RequirementSufficiencyWorker(
                    agent=agent,
                    work_dir=str(root / "requirement-sufficiency"),
                ),
            },
            ttl_seconds=60,
            idle_sleep_seconds=0,
        )
        assert dispatcher.supported_stages == (
            "REQUIREMENT_ANALYSIS",
            "REQUIREMENT_SUFFICIENCY",
            "SCOPE_INTAKE",
        )

        outcomes = [dispatcher.run_once(test_run_id=test_run_id) for _ in range(5)]
        stages = [outcome.stage for outcome in outcomes]
        assert stages == [
            "SCOPE_INTAKE",
            "REQUIREMENT_ANALYSIS",
            "REQUIREMENT_SUFFICIENCY",
            "REQUIREMENT_ANALYSIS",
            "REQUIREMENT_SUFFICIENCY",
        ], stages
        assert outcomes[2].result["result"] == "INSUFFICIENT"
        gap_id = outcomes[2].result["gap_id"]
        assert gap_id
        assert outcomes[4].result["result"] == "SUFFICIENT"
        assert gap_id in outcomes[4].result["closed_gap_ids"]
        assert dsh_state.read_text(encoding="utf-8").strip() == "2"

        # CODE_ANALYSIS is now READY, but this process does not implement it.
        idle = dispatcher.run_once(test_run_id=test_run_id)
        assert idle.status == "IDLE"
        assert idle.stage is None

        with httpx.Client(base_url=base_url, timeout=30.0) as client:
            governance = _governance(client, test_run_id)
        assert [value["result"] for value in governance["evaluations"]] == ["INSUFFICIENT", "SUFFICIENT"]
        gap = [value for value in governance["gaps"] if value["gap_id"] == gap_id][0]
        assert gap["status"] == "CLOSED"
        code = [
            value for value in governance["stages"]
            if value["stage_type"] == "CODE_ANALYSIS" and value["state"] == "READY"
        ]
        assert len(code) == 1

        print({
            "status": "RC8_AUTONOMOUS_REQUIREMENT_DISPATCH_REALITY_PASS",
            "test_run_id": test_run_id,
            "stage_sequence": stages,
            "gap_id": gap_id,
            "gap_status": "CLOSED",
            "evaluation_history": ["INSUFFICIENT", "SUFFICIENT"],
            "code_analysis_ready": True,
            "unsupported_code_analysis_claimed": False,
            "bank_reality_verified": False,
        })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
