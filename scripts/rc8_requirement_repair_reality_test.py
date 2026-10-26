#!/usr/bin/env python3
"""Real HTTP proof of the RC8 requirement-analysis repair loop.

This is cloud protocol reality, not bank reality. It starts from an actual
ProductionDate/TestRound mission and uses the same formal Center API that the
Docker product uses. A fake headless DSH executable is used only to make the
model protocol deterministic in CI:

SCOPE_INTAKE -> REQUIREMENT_ANALYSIS#1 -> REQUIREMENT_SUFFICIENCY#1
  -> INSUFFICIENT + GAP_OPENED -> REQUIREMENT_ANALYSIS#2
  -> REQUIREMENT_SUFFICIENCY#2 -> GAP_CLOSED + SUFFICIENT -> CODE_ANALYSIS READY.

No WorkItem ID is handed from one Stage to the next; the Node always discovers
work through claim-next. Historical Attempt/Evaluation/Gap facts remain.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import time
import uuid
from pathlib import Path

import httpx

from rc8_node.agent import HttpCenterClient
from rc8_node.autonomous_claim_client import AutonomousClaimClient
from rc8_node.dsh_json_runner import DshJsonRunner
from rc8_node.formal_agent import FormalNodeAgent
from rc8_node.requirement_analysis_worker import RequirementAnalysisWorker
from rc8_node.requirement_sufficiency_worker import RequirementSufficiencyWorker
from rc8_runtime import (
    CapabilityQualification,
    CapabilityState,
    NodeIdentity,
    RuntimeProducerKind,
    runtime_event,
)
from rc8_runtime.artifacts import ArtifactManifest


def _wait_ready(client: httpx.Client) -> None:
    deadline = time.time() + 30
    last = None
    while time.time() < deadline:
        try:
            response = client.get("/health")
            last = response.text
            if response.status_code == 200 and response.json().get("status") == "READY":
                return
        except Exception as exc:  # pragma: no cover
            last = str(exc)
        time.sleep(0.25)
    raise AssertionError("CENTER_NOT_READY:%s" % last)


def _post(client: httpx.Client, path: str, payload: dict, expected: int = 200):
    response = client.post(path, json=payload)
    assert response.status_code == expected, (path, response.status_code, response.text)
    return response.json()


def _fake_dsh(path: Path, state_path: Path) -> None:
    incomplete = {
        "source_assertions": [],
        "atomic_statements": ["A1"],
        "trace_links": [{"statement_ref": "A1", "evidence_ref": "source:reqdoc#1"}],
        "evidence_refs": ["source:reqdoc#1"],
        "business_rules": [],
        "roles": ["客户"],
        "preconditions": [],
        "normal_paths": [],
        "negative_paths": [],
        "boundaries": [],
        "states": [],
        "data_constraints": [],
        "dependencies": [],
        "side_effects": [],
        "is_sufficient": True,
    }
    complete = dict(incomplete)
    complete["source_assertions"] = ["SRC-ASSERT-1"]
    complete["normal_paths"] = ["客户提交 -> 系统校验 -> 成功"]
    program = '''#!/usr/bin/env python3
import json, pathlib, sys, uuid
state = pathlib.Path(%r)
try:
    count = int(state.read_text(encoding="utf-8").strip())
except Exception:
    count = 0
count += 1
state.write_text(str(count), encoding="utf-8")
candidate = %r if count == 1 else %r
session = "session-ci-%%s" %% uuid.uuid4().hex
print(json.dumps({"type":"session","session_id":session}, ensure_ascii=False))
print(json.dumps({"type":"tool_call","tool_name":"read_requirement_source"}, ensure_ascii=False))
print(json.dumps({"type":"final","text":json.dumps(candidate, ensure_ascii=False)}, ensure_ascii=False))
''' % (str(state_path), incomplete, complete)
    path.write_text(program, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _claim(claimant: AutonomousClaimClient, run_id: str, expected_stage: str):
    claimed = claimant.claim_next(test_run_id=run_id)
    assert claimed.claimed is True, (expected_stage, claimed)
    assert claimed.stage == expected_stage, (expected_stage, claimed.stage)
    assert claimed.work_item_id and claimed.lease_id and claimed.stage_instance_id
    return claimed


def _complete_scope_intake(agent: FormalNodeAgent, claim, work_dir: Path):
    work_id = claim.work_item_id
    lease_id = claim.lease_id
    stage_id = claim.stage_instance_id
    run_id = claim.work_item["identity"]["test_run_id"]

    # Formal Center owns ATTEMPT_STARTED. The lease returned by claim-next is
    # the only Attempt identity used by artifacts and terminal truth.
    attempt_id = lease_id
    agent.start(work_id, lease_id=lease_id)

    content = json.dumps({"scope": "normalized", "stage_instance_id": stage_id}, sort_keys=True).encode("utf-8")
    target = work_dir / "scope-intake.json"
    target.write_bytes(content)
    artifact_id = "artifact-intake-%s" % uuid.uuid4().hex
    manifest = ArtifactManifest(
        artifact_id=artifact_id,
        test_run_id=run_id,
        work_item_id=work_id,
        node_id=agent.identity.node_id,
        kind="SCOPE_INTAKE_EVIDENCE",
        producer_kind=RuntimeProducerKind.WORKER,
        producer_ref="RC8_REALITY_SCOPE_INTAKE",
        file_name="scope-intake.json",
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        attempt_id=attempt_id,
        refs=["stage:%s" % stage_id],
        created_at=int(time.time()),
    )
    agent.upload_artifact_file(manifest, str(target), lease_id=lease_id)
    seq = agent.center.get(
        "/api/v1/test-runs/%s/nodes/%s/runtime-sequence" % (run_id, agent.identity.node_id)
    )["next_sequence"]
    agent.append_runtime_event(
        runtime_event(
            event_id="evt-intake-complete-%s" % uuid.uuid4().hex,
            test_run_id=run_id,
            work_item_id=work_id,
            node_id=agent.identity.node_id,
            producer_kind=RuntimeProducerKind.WORKER,
            producer_ref="RC8_REALITY_SCOPE_INTAKE",
            event_type="ATTEMPT_COMPLETED",
            sequence=seq,
            attempt_id=attempt_id,
            refs=list(claim.work_item["identity"].get("scope_refs") or []),
            data={
                "stage_instance_id": stage_id,
                "evidence_refs": ["artifact:%s" % artifact_id],
                "finished_at": int(time.time()),
            },
        ),
        lease_id=lease_id,
    )
    terminal = agent.complete(work_id, lease_id=lease_id)
    assert terminal["work_item"]["state"] == "COMPLETED"
    return artifact_id


def _governance(client: httpx.Client, run_id: str):
    response = client.get("/api/v1/test-runs/%s/governance" % run_id)
    assert response.status_code == 200, response.text
    return response.json()


def main() -> int:
    base_url = os.environ.get("RC8_CENTER_URL", "http://127.0.0.1:18080").rstrip("/")
    suffix = uuid.uuid4().hex[:10]
    batch_id = "PB-REQ-REPAIR-%s" % suffix
    req_id = "REQ-REPAIR-%s" % suffix
    req_rev_id = "REQREV-2-%s" % suffix
    scope_rev_id = "SCOPEREV-2-%s" % suffix
    delivery_id = "DEL-REPAIR-%s" % suffix
    scope_id = "SCOPE-REPAIR-%s" % suffix
    round_id = "ROUND-REPAIR-%s" % suffix
    run_id = "TR-REPAIR-%s" % suffix
    node_id = "NODE-REPAIR-%s" % suffix

    with tempfile.TemporaryDirectory(prefix="rc8-req-repair-") as temp:
        temp_dir = Path(temp)
        fake_dsh = temp_dir / "fake-dsh"
        dsh_state = temp_dir / "dsh-count.txt"
        _fake_dsh(fake_dsh, dsh_state)

        with httpx.Client(base_url=base_url, timeout=30.0) as client:
            _wait_ready(client)
            _post(client, "/api/v1/production-batches", {
                "production_batch_id": batch_id,
                "production_date": "2026-11-15",
                "name": "requirement repair reality",
            }, expected=201)
            _post(client, "/api/v1/requirements", {
                "requirement_id": req_id,
                "title": "需求分析回补测试",
            }, expected=201)
            _post(client, "/api/v1/requirements/%s/revisions" % req_id, {
                "requirement_revision_id": req_rev_id,
                "revision_label": "V2",
                "payload": {"source_refs": ["source:reqdoc#1"]},
            }, expected=201)
            _post(client, "/api/v1/requirement-revisions/%s/scope-revisions" % req_rev_id, {
                "scope_revision_id": scope_rev_id,
                "revision_label": "SR2",
                "payload": {"source_refs": ["source:scope#1"]},
            }, expected=201)
            delivery = _post(
                client,
                "/api/v1/production-batches/%s/requirements/%s/deliveries" % (batch_id, req_id),
                {
                    "delivery_id": delivery_id,
                    "requirement_revision_id": req_rev_id,
                    "scope_revision_id": scope_rev_id,
                },
                expected=201,
            )
            assert delivery["requirement_revision_id"] == req_rev_id
            assert delivery["scope_revision_id"] == scope_rev_id
            _post(client, "/api/v1/requirement-deliveries/%s/scopes" % delivery_id, {
                "scope_id": scope_id,
                "system_id": "PFC",
                "system_version": "SYS-V1",
                "application_id": "cfg-center",
                "sst_id": "SST-REPAIR",
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
            payload = started["test_run"]["payload"]
            assert payload["requirement_revision_ids"] == [req_rev_id]
            assert payload["scope_revision_ids"] == [scope_rev_id]
            _post(client, "/api/v1/nodes/register", {
                "node_id": node_id,
                "operator_ref": "ci-requirement-repair",
                "os_family": "linux",
                "architecture": "x86_64",
                "shell": "bash",
                "registered_at": 1,
            })

        identity = NodeIdentity(
            node_id=node_id,
            operator_ref="ci-requirement-repair",
            os_family="linux",
            architecture="x86_64",
            shell="bash",
            registered_at=1,
        )
        center = HttpCenterClient(base_url, timeout_seconds=30)
        agent = FormalNodeAgent(identity, center)
        agent.report_capability(
            CapabilityQualification(
                node_id=node_id,
                capability_id="codegraph",
                state=CapabilityState.VERIFIED,
                probe_ref="ci://codegraph-probe",
                evidence_refs=["ci://codegraph-evidence"],
                verified_at=1,
            )
        )
        claimant = AutonomousClaimClient(base_url, node_id, timeout_seconds=30)
        analysis_worker = RequirementAnalysisWorker(
            agent=agent,
            dsh_runner=DshJsonRunner(
                dsh_bin=str(fake_dsh),
                patch_path="ci-reality-patch",
                cwd=str(temp_dir),
                timeout_seconds=30,
            ),
            work_dir=str(temp_dir / "analysis"),
        )
        sufficiency_worker = RequirementSufficiencyWorker(
            agent=agent,
            work_dir=str(temp_dir / "sufficiency"),
        )

        intake = _claim(claimant, run_id, "SCOPE_INTAKE")
        intake_artifact_id = _complete_scope_intake(agent, intake, temp_dir)

        analysis1 = _claim(claimant, run_id, "REQUIREMENT_ANALYSIS")
        analysis1_result = analysis_worker.execute(analysis1)
        assert analysis1_result["status"] == "COMPLETED"
        assert dsh_state.read_text(encoding="utf-8").strip() == "1"

        suff1 = _claim(claimant, run_id, "REQUIREMENT_SUFFICIENCY")
        analysis1_artifact_id = analysis1_result["artifact_ref"].split(":", 1)[1]
        valid_read = center.get(
            "/api/v1/artifacts/%s/json?work_item_id=%s" % (analysis1_artifact_id, suff1.work_item_id),
            headers={"X-RC8-Node-Id": node_id, "X-RC8-Lease-Id": suff1.lease_id},
        )
        assert valid_read["truth_note"] == "LEASE_AUTHORIZED_EXPLICIT_PREDECESSOR_EVIDENCE_READ"

        with httpx.Client(base_url=base_url, timeout=30.0) as client:
            wrong_lease = client.get(
                "/api/v1/artifacts/%s/json" % analysis1_artifact_id,
                params={"work_item_id": suff1.work_item_id},
                headers={"X-RC8-Node-Id": node_id, "X-RC8-Lease-Id": "wrong-lease"},
            )
            assert wrong_lease.status_code == 409, wrong_lease.text
            unrelated = client.get(
                "/api/v1/artifacts/%s/json" % intake_artifact_id,
                params={"work_item_id": suff1.work_item_id},
                headers={"X-RC8-Node-Id": node_id, "X-RC8-Lease-Id": suff1.lease_id},
            )
            assert unrelated.status_code == 403, unrelated.text

        suff1_result = sufficiency_worker.execute(suff1)
        assert suff1_result["result"] == "INSUFFICIENT"
        gap_id = suff1_result["gap_id"]
        assert gap_id

        with httpx.Client(base_url=base_url, timeout=30.0) as client:
            after_first = _governance(client, run_id)
            stages = after_first["stages"]
            assert len([s for s in stages if s["stage_type"] == "REQUIREMENT_ANALYSIS" and s["attempt_no"] == 2 and s["state"] == "READY"]) == 1
            assert len([s for s in stages if s["stage_type"] == "REQUIREMENT_SUFFICIENCY" and s["attempt_no"] == 2 and s["state"] == "PENDING"]) == 1
            assert len([s for s in stages if s["stage_type"] == "CODE_ANALYSIS" and s["state"] == "PENDING"]) == 1
            assert [e["result"] for e in after_first["evaluations"]] == ["INSUFFICIENT"]
            gap = [g for g in after_first["gaps"] if g["gap_id"] == gap_id][0]
            assert gap["status"] == "OPEN"

        analysis2 = _claim(claimant, run_id, "REQUIREMENT_ANALYSIS")
        refs2 = set(analysis2.work_item["identity"].get("scope_refs") or [])
        assert "gap:%s" % gap_id in refs2
        assert "requirement-revision:%s" % req_rev_id in refs2
        assert "scope-revision:%s" % scope_rev_id in refs2
        analysis2_result = analysis_worker.execute(analysis2)
        assert analysis2_result["status"] == "COMPLETED"
        assert dsh_state.read_text(encoding="utf-8").strip() == "2"
        assert analysis2_result["dsh_session_id"] != analysis1_result["dsh_session_id"]

        suff2 = _claim(claimant, run_id, "REQUIREMENT_SUFFICIENCY")
        refs_suff2 = set(suff2.work_item["identity"].get("scope_refs") or [])
        assert "gap:%s" % gap_id in refs_suff2
        assert analysis2_result["artifact_ref"] in refs_suff2
        suff2_result = sufficiency_worker.execute(suff2)
        assert suff2_result["result"] == "SUFFICIENT"
        assert gap_id in suff2_result["closed_gap_ids"]

        with httpx.Client(base_url=base_url, timeout=30.0) as client:
            final = _governance(client, run_id)
            evaluations = [e["result"] for e in final["evaluations"]]
            assert evaluations == ["INSUFFICIENT", "SUFFICIENT"], evaluations
            gap = [g for g in final["gaps"] if g["gap_id"] == gap_id][0]
            assert gap["status"] == "CLOSED"
            req_attempts = [s for s in final["stages"] if s["stage_type"] == "REQUIREMENT_ANALYSIS"]
            suff_attempts = [s for s in final["stages"] if s["stage_type"] == "REQUIREMENT_SUFFICIENCY"]
            assert sorted(s["attempt_no"] for s in req_attempts) == [1, 2]
            assert sorted(s["attempt_no"] for s in suff_attempts) == [1, 2]
            code_ready = [s for s in final["stages"] if s["stage_type"] == "CODE_ANALYSIS" and s["state"] == "READY"]
            assert len(code_ready) == 1

        code = _claim(claimant, run_id, "CODE_ANALYSIS")
        required = set(code.work_item["identity"].get("required_capabilities") or [])
        assert required == {"codegraph"}
        assert code.stage_instance_id == code_ready[0]["stage_instance_id"]

        print({
            "status": "RC8_REQUIREMENT_REPAIR_REALITY_PASS",
            "test_run_id": run_id,
            "test_round_id": round_id,
            "requirement_revision_id": req_rev_id,
            "scope_revision_id": scope_rev_id,
            "dsh_sessions": [analysis1_result["dsh_session_id"], analysis2_result["dsh_session_id"]],
            "gap_id": gap_id,
            "evaluation_history": ["INSUFFICIENT", "SUFFICIENT"],
            "next_stage": "CODE_ANALYSIS",
            "bank_reality_verified": False,
        })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
