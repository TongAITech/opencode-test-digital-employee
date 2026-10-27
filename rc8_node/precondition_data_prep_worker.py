"""Fail-closed N5 PRECONDITION_DATA_PREP node worker.

Produces node-local preparation observations only. Canonical PreparedAttempt
creation/verification remains a Center authority; this worker cannot make an
attempt executable or declare readiness/PASS/release.
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


class PreconditionDataPrepWorkerError(RuntimeError):
    pass


class PreconditionDataPrepWorker:
    producer_ref = "RC8_PRECONDITION_DATA_PREP_WORKER"

    def __init__(self, *, agent: Any, dsh_runner: DshJsonRunner, work_dir: str, now_fn: Optional[Any] = None) -> None:
        self.agent = agent
        self.dsh_runner = dsh_runner
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._now = now_fn or (lambda: int(time.time()))

    def execute(self, claimed: Any) -> Dict[str, Any]:
        work = getattr(claimed, "work_item", None)
        identity = work.get("identity") if isinstance(work, dict) else None
        if not isinstance(identity, dict):
            raise PreconditionDataPrepWorkerError("CLAIMED_WORK_ITEM_IDENTITY_REQUIRED")
        if str(identity.get("stage") or "") != "PRECONDITION_DATA_PREP":
            raise PreconditionDataPrepWorkerError("WORK_ITEM_STAGE_NOT_PRECONDITION_DATA_PREP")
        work_item_id = self._required(identity.get("work_item_id"), "WORK_ITEM_ID_REQUIRED")
        test_run_id = self._required(identity.get("test_run_id"), "TEST_RUN_ID_REQUIRED")
        lease_id = self._required(getattr(claimed, "lease_id", None), "WORK_ITEM_LEASE_ID_REQUIRED")
        stage_instance_id = self._required(getattr(claimed, "stage_instance_id", None), "STAGE_INSTANCE_ID_REQUIRED")
        refs = tuple(str(v).strip() for v in identity.get("scope_refs") or [] if str(v).strip())
        if not refs:
            raise PreconditionDataPrepWorkerError("N5_FROZEN_SCOPE_REFS_REQUIRED")

        self.agent.start(work_item_id, lease_id=lease_id)
        try:
            result = self.dsh_runner.run(self._prompt(refs))
            candidate = self.validate_candidate(result.output)
        except DshJsonRunnerError as exc:
            raise PreconditionDataPrepWorkerError("PRECONDITION_DATA_PREP_DSH_FAILED:%s" % exc.reason)

        payload = {"schema_version": "rc8.precondition-data-prep-observation.v1",
                   "authority": "NODE_OBSERVATION_ONLY", "test_run_id": test_run_id,
                   "work_item_id": work_item_id, "stage_instance_id": stage_instance_id,
                   "scope_refs": list(refs), "candidate": candidate,
                   "dsh_session_id": result.session_id, "tool_calls": list(result.tool_calls),
                   "generated_at": self._now()}
        artifact_id = "artifact-precondition-data-%s" % uuid.uuid4().hex
        artifact_ref = self._upload(artifact_id, payload, test_run_id, work_item_id, stage_instance_id, lease_id, refs)
        self.agent.append_runtime_event(runtime_event(
            event_id="evt-precondition-data-%s" % uuid.uuid4().hex, test_run_id=test_run_id,
            work_item_id=work_item_id, node_id=self.agent.identity.node_id,
            producer_kind=RuntimeProducerKind.WORKER, producer_ref=self.producer_ref,
            event_type="ATTEMPT_COMPLETED", sequence=self._next_sequence(test_run_id),
            attempt_id=lease_id, refs=list(refs), data={"stage_instance_id": stage_instance_id,
                "evidence_refs": [artifact_ref], "prepared_attempt_authority": "CENTER_ONLY",
                "authority": "NODE_OBSERVATION_ONLY", "finished_at": self._now()}), lease_id=lease_id)
        terminal = self.agent.complete(work_item_id, lease_id=lease_id)
        return {"status": "COMPLETED", "attempt_id": lease_id, "artifact_ref": artifact_ref,
                "prepared_attempt_authority": "CENTER_ONLY", "terminal": terminal}

    @staticmethod
    def validate_candidate(value: Any) -> Dict[str, Any]:
        if not isinstance(value, dict):
            raise PreconditionDataPrepWorkerError("PRECONDITION_DATA_PREP_OUTPUT_OBJECT_REQUIRED")
        obligations = value.get("precondition_obligations")
        prepared = value.get("prepared_items")
        evidence = value.get("evidence_refs")
        if not isinstance(obligations, list) or not obligations:
            raise PreconditionDataPrepWorkerError("PRECONDITION_OBLIGATIONS_NONEMPTY_REQUIRED")
        denominator = [str(v).strip() for v in obligations if str(v).strip()]
        if len(denominator) != len(obligations) or len(set(denominator)) != len(denominator):
            raise PreconditionDataPrepWorkerError("PRECONDITION_DENOMINATOR_UNIQUE_NONBLANK_REQUIRED")
        if not isinstance(prepared, list) or not prepared:
            raise PreconditionDataPrepWorkerError("PREPARED_ITEMS_NONEMPTY_REQUIRED")
        covered = set()
        for item in prepared:
            if not isinstance(item, dict) or not str(item.get("obligation_id") or "").strip():
                raise PreconditionDataPrepWorkerError("PREPARED_ITEM_OBLIGATION_ID_REQUIRED")
            obligation_id = str(item["obligation_id"]).strip()
            if obligation_id not in denominator:
                raise PreconditionDataPrepWorkerError("PREPARED_ITEM_UNKNOWN_OBLIGATION")
            if not str(item.get("state") or "").strip() or not str(item.get("locator") or "").strip():
                raise PreconditionDataPrepWorkerError("PREPARED_ITEM_STATE_AND_LOCATOR_REQUIRED")
            item_evidence = item.get("evidence_refs")
            if not isinstance(item_evidence, list) or not [v for v in item_evidence if str(v).strip()]:
                raise PreconditionDataPrepWorkerError("PREPARED_ITEM_EVIDENCE_REQUIRED")
            covered.add(obligation_id)
        if covered != set(denominator):
            raise PreconditionDataPrepWorkerError("PRECONDITION_DENOMINATOR_NOT_FULLY_PREPARED")
        if not isinstance(evidence, list) or not [v for v in evidence if str(v).strip()]:
            raise PreconditionDataPrepWorkerError("PRECONDITION_DATA_EVIDENCE_REFS_NONEMPTY_REQUIRED")
        return dict(value)

    def _upload(self, artifact_id: str, content: Dict[str, Any], test_run_id: str, work_item_id: str, stage_instance_id: str, lease_id: str, refs: Sequence[str]) -> str:
        target = self.work_dir / (artifact_id + ".json")
        raw = json.dumps(content, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        target.write_bytes(raw)
        manifest = ArtifactManifest(artifact_id=artifact_id, test_run_id=test_run_id, work_item_id=work_item_id,
            node_id=self.agent.identity.node_id, kind="PRECONDITION_DATA_PREP_OBSERVATION",
            producer_kind=RuntimeProducerKind.WORKER, producer_ref=self.producer_ref,
            file_name="precondition-data-prep-observation.json", sha256=hashlib.sha256(raw).hexdigest(),
            size_bytes=len(raw), attempt_id=lease_id, refs=list(refs) + ["stage:%s" % stage_instance_id],
            metadata={"stage": "PRECONDITION_DATA_PREP", "authority": "NODE_OBSERVATION_ONLY",
                      "prepared_attempt_authority": "CENTER_ONLY"}, created_at=self._now())
        self.agent.upload_artifact_file(manifest, str(target), lease_id=lease_id)
        return "artifact:%s" % artifact_id

    def _next_sequence(self, test_run_id: str) -> int:
        value = self.agent.center.get("/api/v1/test-runs/%s/nodes/%s/runtime-sequence" %
            (quote(test_run_id, safe=""), quote(self.agent.identity.node_id, safe="")))
        sequence = value.get("next_sequence")
        if not isinstance(sequence, int) or sequence < 0:
            raise PreconditionDataPrepWorkerError("R1_NEXT_SEQUENCE_INVALID")
        return sequence

    @staticmethod
    def _prompt(refs: Sequence[str]) -> str:
        return ("You are RC8 N5 PRECONDITION_DATA_PREP. Use only frozen scope refs %s. Return strict JSON with "
                "precondition_obligations, prepared_items, evidence_refs. Each prepared item must bind exactly one obligation_id, "
                "state, locator and non-empty evidence_refs. Cover the full denominator; do not shrink it. Do not claim PreparedAttempt, "
                "executable readiness, PASS, quality or release; those are Center authorities." % json.dumps(list(refs), ensure_ascii=False))

    @staticmethod
    def _required(value: Any, error: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise PreconditionDataPrepWorkerError(error)
        return normalized
