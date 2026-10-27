"""Fail-closed N4 RISK_TEST_MODEL node worker.

The worker produces candidate risk obligations only. It never declares design
sufficiency, MissionNode PASS, product quality, or release readiness. Center
remains the final verification/sufficiency authority.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Sequence
from urllib.parse import quote

from rc8_runtime import RuntimeProducerKind, runtime_event
from rc8_runtime.artifacts import ArtifactManifest

from .dsh_json_runner import DshJsonRunner, DshJsonRunnerError


class RiskTestModelWorkerError(RuntimeError):
    pass


class RiskTestModelWorker:
    producer_ref = "RC8_RISK_TEST_MODEL_WORKER"

    def __init__(self, *, agent: Any, dsh_runner: DshJsonRunner, work_dir: str, now_fn: Optional[Any] = None) -> None:
        self.agent = agent
        self.dsh_runner = dsh_runner
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._now = now_fn or (lambda: int(time.time()))

    def execute(self, claimed: Any) -> Dict[str, Any]:
        work = getattr(claimed, "work_item", None)
        if not isinstance(work, dict) or not isinstance(work.get("identity"), dict):
            raise RiskTestModelWorkerError("CLAIMED_WORK_ITEM_IDENTITY_REQUIRED")
        identity = work["identity"]
        if str(identity.get("stage") or "") != "RISK_TEST_MODEL":
            raise RiskTestModelWorkerError("WORK_ITEM_STAGE_NOT_RISK_TEST_MODEL")
        work_item_id = self._required(identity.get("work_item_id"), "WORK_ITEM_ID_REQUIRED")
        test_run_id = self._required(identity.get("test_run_id"), "TEST_RUN_ID_REQUIRED")
        lease_id = self._required(getattr(claimed, "lease_id", None), "WORK_ITEM_LEASE_ID_REQUIRED")
        stage_instance_id = self._required(getattr(claimed, "stage_instance_id", None), "STAGE_INSTANCE_ID_REQUIRED")
        scope_refs = tuple(str(v).strip() for v in identity.get("scope_refs") or [] if str(v).strip())
        if not scope_refs:
            raise RiskTestModelWorkerError("N4_FROZEN_SCOPE_REFS_REQUIRED")

        self.agent.start(work_item_id, lease_id=lease_id)
        try:
            result = self.dsh_runner.run(self._prompt(scope_refs))
            candidate = self.validate_candidate(result.output)
        except DshJsonRunnerError as exc:
            raise RiskTestModelWorkerError("RISK_MODEL_DSH_FAILED:%s" % exc.reason)

        artifact = {
            "schema_version": "rc8.risk-test-model.v1",
            "authority": "NODE_OBSERVATION_ONLY",
            "test_run_id": test_run_id,
            "work_item_id": work_item_id,
            "stage_instance_id": stage_instance_id,
            "scope_refs": list(scope_refs),
            "candidate": candidate,
            "dsh_session_id": result.session_id,
            "tool_calls": list(result.tool_calls),
            "generated_at": self._now(),
        }
        artifact_id = "artifact-risk-model-%s" % uuid.uuid4().hex
        artifact_ref = self._upload(artifact_id, artifact, test_run_id, work_item_id, stage_instance_id, lease_id, scope_refs)
        sequence = self._next_sequence(test_run_id)
        self.agent.append_runtime_event(runtime_event(
            event_id="evt-risk-model-%s" % uuid.uuid4().hex,
            test_run_id=test_run_id,
            work_item_id=work_item_id,
            node_id=self.agent.identity.node_id,
            producer_kind=RuntimeProducerKind.WORKER,
            producer_ref=self.producer_ref,
            event_type="ATTEMPT_COMPLETED",
            sequence=sequence,
            attempt_id=lease_id,
            refs=list(scope_refs),
            data={"stage_instance_id": stage_instance_id, "evidence_refs": [artifact_ref], "authority": "NODE_OBSERVATION_ONLY", "finished_at": self._now()},
        ), lease_id=lease_id)
        terminal = self.agent.complete(work_item_id, lease_id=lease_id)
        return {"status": "COMPLETED", "attempt_id": lease_id, "artifact_ref": artifact_ref, "terminal": terminal}

    @staticmethod
    def validate_candidate(value: Any) -> Dict[str, Any]:
        if not isinstance(value, dict):
            raise RiskTestModelWorkerError("RISK_MODEL_OUTPUT_OBJECT_REQUIRED")
        obligations = value.get("risk_obligations")
        evidence_refs = value.get("evidence_refs")
        denominator = value.get("denominator")
        if not isinstance(obligations, list) or not obligations:
            raise RiskTestModelWorkerError("RISK_OBLIGATIONS_NONEMPTY_REQUIRED")
        if not isinstance(evidence_refs, list) or not [x for x in evidence_refs if str(x).strip()]:
            raise RiskTestModelWorkerError("RISK_MODEL_EVIDENCE_REFS_NONEMPTY_REQUIRED")
        if not isinstance(denominator, dict) or not denominator:
            raise RiskTestModelWorkerError("RISK_MODEL_DENOMINATOR_REQUIRED")
        expected = denominator.get("expected_obligation_count")
        if not isinstance(expected, int) or expected <= 0 or expected != len(obligations):
            raise RiskTestModelWorkerError("RISK_MODEL_DENOMINATOR_MISMATCH")
        evidence = {str(x).strip() for x in evidence_refs if str(x).strip()}
        for item in obligations:
            if not isinstance(item, dict) or not str(item.get("risk_id") or "").strip():
                raise RiskTestModelWorkerError("RISK_OBLIGATION_ID_REQUIRED")
            refs = item.get("evidence_refs")
            if not isinstance(refs, list) or not refs or any(str(ref).strip() not in evidence for ref in refs):
                raise RiskTestModelWorkerError("RISK_OBLIGATION_EVIDENCE_MISMATCH")
        return dict(value)

    def _upload(self, artifact_id: str, content: Dict[str, Any], test_run_id: str, work_item_id: str, stage_instance_id: str, lease_id: str, refs: Sequence[str]) -> str:
        target = self.work_dir / (artifact_id + ".json")
        raw = json.dumps(content, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        target.write_bytes(raw)
        manifest = ArtifactManifest(
            artifact_id=artifact_id, test_run_id=test_run_id, work_item_id=work_item_id,
            node_id=self.agent.identity.node_id, kind="RISK_TEST_MODEL",
            producer_kind=RuntimeProducerKind.WORKER, producer_ref=self.producer_ref,
            file_name="risk-test-model.json", sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw),
            attempt_id=lease_id, refs=list(refs) + ["stage:%s" % stage_instance_id],
            metadata={"stage": "RISK_TEST_MODEL", "authority": "NODE_OBSERVATION_ONLY"}, created_at=self._now())
        self.agent.upload_artifact_file(manifest, str(target), lease_id=lease_id)
        return "artifact:%s" % artifact_id

    def _next_sequence(self, test_run_id: str) -> int:
        value = self.agent.center.get("/api/v1/test-runs/%s/nodes/%s/runtime-sequence" % (quote(test_run_id, safe=""), quote(self.agent.identity.node_id, safe="")))
        sequence = value.get("next_sequence")
        if not isinstance(sequence, int) or sequence < 0:
            raise RiskTestModelWorkerError("R1_NEXT_SEQUENCE_INVALID")
        return sequence

    @staticmethod
    def _prompt(scope_refs: Sequence[str]) -> str:
        return ("You are the RC8 N4 RISK_TEST_MODEL worker. Analyze only the frozen scope refs: %s. "
                "Do not decide PASS, sufficiency, product quality, or release. Use real inspected evidence; never guess missing facts. "
                "Return strict JSON with risk_obligations (non-empty list), evidence_refs (non-empty list), and denominator object containing expected_obligation_count. "
                "Every risk obligation requires risk_id and evidence_refs, and every obligation evidence ref must exist in top-level evidence_refs."
                % json.dumps(list(scope_refs), ensure_ascii=False))

    @staticmethod
    def _required(value: Any, error: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise RiskTestModelWorkerError(error)
        return normalized
