"""Fail-closed N9 defect-closure observation worker.

The node may collect PRODUCT-route defect evidence, but it never creates or closes a
canonical defect. Center remains the sole defect-lifecycle authority.
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


class DefectClosureObservationWorkerError(RuntimeError):
    pass


class DefectClosureObservationWorker:
    producer_ref = "RC8_DEFECT_CLOSURE_OBSERVATION_WORKER"
    stage = "DEFECT_CLOSURE_OBSERVATION"

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
            raise DefectClosureObservationWorkerError("CLAIMED_WORK_ITEM_IDENTITY_REQUIRED")
        if str(identity.get("stage") or "") != self.stage:
            raise DefectClosureObservationWorkerError("WORK_ITEM_STAGE_NOT_DEFECT_CLOSURE_OBSERVATION")
        work_item_id = self._required(identity.get("work_item_id"), "WORK_ITEM_ID_REQUIRED")
        test_run_id = self._required(identity.get("test_run_id"), "TEST_RUN_ID_REQUIRED")
        lease_id = self._required(getattr(claimed, "lease_id", None), "WORK_ITEM_LEASE_ID_REQUIRED")
        stage_instance_id = self._required(getattr(claimed, "stage_instance_id", None), "STAGE_INSTANCE_ID_REQUIRED")
        refs = tuple(str(v).strip() for v in identity.get("scope_refs") or [] if str(v).strip())
        if not refs:
            raise DefectClosureObservationWorkerError("N9_FROZEN_SCOPE_REFS_REQUIRED")
        self.agent.start(work_item_id, lease_id=lease_id)
        try:
            result = self.dsh_runner.run(self._prompt(refs))
            candidate = self.validate_candidate(result.output)
        except DshJsonRunnerError as exc:
            raise DefectClosureObservationWorkerError("DEFECT_CLOSURE_DSH_FAILED:%s" % exc.reason)
        payload = {
            "schema_version": "rc8.defect-closure-observation.v1",
            "authority": "NODE_OBSERVATION_ONLY",
            "defect_lifecycle_authority": "CENTER_ONLY",
            "test_run_id": test_run_id,
            "work_item_id": work_item_id,
            "stage_instance_id": stage_instance_id,
            "scope_refs": list(refs),
            "candidate": candidate,
            "dsh_session_id": result.session_id,
            "tool_calls": list(result.tool_calls),
            "generated_at": self._now(),
        }
        artifact_id = "artifact-defect-closure-%s" % uuid.uuid4().hex
        artifact_ref = self._upload(artifact_id, payload, test_run_id, work_item_id, stage_instance_id, lease_id, refs)
        self.agent.append_runtime_event(runtime_event(
            event_id="evt-defect-closure-%s" % uuid.uuid4().hex,
            test_run_id=test_run_id,
            work_item_id=work_item_id,
            node_id=self.agent.identity.node_id,
            producer_kind=RuntimeProducerKind.WORKER,
            producer_ref=self.producer_ref,
            event_type="ATTEMPT_COMPLETED",
            sequence=self._next_sequence(test_run_id),
            attempt_id=lease_id,
            refs=list(refs),
            data={
                "stage_instance_id": stage_instance_id,
                "evidence_refs": [artifact_ref],
                "route_decision_ref": candidate["route_decision_ref"],
                "source_attempt_ref": candidate["source_attempt_ref"],
                "classification": "PRODUCT",
                "defect_lifecycle_authority": "CENTER_ONLY",
                "authority": "NODE_OBSERVATION_ONLY",
                "may_file_defect": False,
                "may_close_defect": False,
                "finished_at": self._now(),
            },
        ), lease_id=lease_id)
        terminal = self.agent.complete(work_item_id, lease_id=lease_id)
        return {"status": "COMPLETED", "attempt_id": lease_id, "artifact_ref": artifact_ref, "defect_lifecycle_authority": "CENTER_ONLY", "terminal": terminal}

    @staticmethod
    def validate_candidate(value: Any) -> Dict[str, Any]:
        if not isinstance(value, dict):
            raise DefectClosureObservationWorkerError("DEFECT_CLOSURE_OUTPUT_OBJECT_REQUIRED")
        route_ref = str(value.get("route_decision_ref") or "").strip()
        source_observation_ref = str(value.get("source_observation_ref") or "").strip()
        source_attempt_ref = str(value.get("source_attempt_ref") or "").strip()
        if not route_ref:
            raise DefectClosureObservationWorkerError("N9_CANONICAL_N8_ROUTE_REF_REQUIRED")
        if not source_observation_ref or not source_attempt_ref:
            raise DefectClosureObservationWorkerError("N9_SOURCE_OBSERVATION_AND_ATTEMPT_REQUIRED")
        classification = str(value.get("classification") or "").strip().upper()
        if classification != "PRODUCT":
            raise DefectClosureObservationWorkerError("N9_REQUIRES_PRODUCT_CLASSIFICATION")
        evidence = value.get("evidence_refs")
        if not isinstance(evidence, list) or not evidence or any(not str(ref).strip() for ref in evidence):
            raise DefectClosureObservationWorkerError("N9_EVIDENCE_REFS_NONEMPTY_REQUIRED")
        normalized = [str(ref).strip() for ref in evidence]
        if len(set(normalized)) != len(normalized):
            raise DefectClosureObservationWorkerError("N9_EVIDENCE_REFS_UNIQUE_REQUIRED")
        observations = value.get("observations")
        if not isinstance(observations, list) or not observations:
            raise DefectClosureObservationWorkerError("N9_OBSERVATIONS_NONEMPTY_REQUIRED")
        allowed = {"REPRODUCTION", "RCA", "IMPACT", "FIX_VERIFICATION", "REGRESSION"}
        seen = set()
        for item in observations:
            if not isinstance(item, dict):
                raise DefectClosureObservationWorkerError("N9_OBSERVATION_OBJECT_REQUIRED")
            observation_id = str(item.get("observation_id") or "").strip()
            kind = str(item.get("kind") or "").strip().upper()
            item_evidence = item.get("evidence_refs")
            if not observation_id or observation_id in seen:
                raise DefectClosureObservationWorkerError("N9_OBSERVATION_ID_UNIQUE_REQUIRED")
            if kind not in allowed:
                raise DefectClosureObservationWorkerError("N9_OBSERVATION_KIND_INVALID")
            if not isinstance(item_evidence, list) or not item_evidence or any(not str(ref).strip() for ref in item_evidence):
                raise DefectClosureObservationWorkerError("N9_OBSERVATION_EVIDENCE_REQUIRED")
            seen.add(observation_id)
        result = dict(value)
        result["classification"] = "PRODUCT"
        result["authority"] = "NODE_OBSERVATION_ONLY"
        result["defect_lifecycle_authority"] = "CENTER_ONLY"
        result["may_file_defect"] = False
        result["may_close_defect"] = False
        return result

    def _upload(self, artifact_id: str, content: Dict[str, Any], test_run_id: str, work_item_id: str, stage_instance_id: str, lease_id: str, refs: Sequence[str]) -> str:
        target = self.work_dir / (artifact_id + ".json")
        raw = json.dumps(content, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        target.write_bytes(raw)
        manifest = ArtifactManifest(artifact_id=artifact_id, test_run_id=test_run_id, work_item_id=work_item_id, node_id=self.agent.identity.node_id, kind="DEFECT_CLOSURE_OBSERVATION", producer_kind=RuntimeProducerKind.WORKER, producer_ref=self.producer_ref, file_name="defect-closure-observation.json", sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw), attempt_id=lease_id, refs=list(refs) + ["stage:%s" % stage_instance_id], metadata={"stage": self.stage, "authority": "NODE_OBSERVATION_ONLY", "defect_lifecycle_authority": "CENTER_ONLY"}, created_at=self._now())
        self.agent.upload_artifact_file(manifest, str(target), lease_id=lease_id)
        return "artifact:%s" % artifact_id

    def _next_sequence(self, test_run_id: str) -> int:
        value = self.agent.center.get("/api/v1/test-runs/%s/nodes/%s/runtime-sequence" % (quote(test_run_id, safe=""), quote(self.agent.identity.node_id, safe="")))
        sequence = value.get("next_sequence")
        if not isinstance(sequence, int) or sequence < 0:
            raise DefectClosureObservationWorkerError("R1_NEXT_SEQUENCE_INVALID")
        return sequence

    @staticmethod
    def _prompt(refs: Sequence[str]) -> str:
        return ("You are RC8 N9 defect-evidence observation. Use only frozen refs %s and canonical N8 PRODUCT-route Evidence. Return strict JSON with route_decision_ref, source_observation_ref, source_attempt_ref, classification PRODUCT, non-empty unique evidence_refs, and evidence-backed observations using REPRODUCTION/RCA/IMPACT/FIX_VERIFICATION/REGRESSION only. Do not file or close a defect and do not claim MissionNode PASS, quality, sufficiency or release; Center owns the canonical defect lifecycle." % json.dumps(list(refs), ensure_ascii=False))

    @staticmethod
    def _required(value: Any, error: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise DefectClosureObservationWorkerError(error)
        return normalized
