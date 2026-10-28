"""Fail-closed REPORT_RELEASE handoff worker.

This worker closes the node-runtime Stage denominator without granting release or
mission-convergence authority to the node. It emits an evidence-backed handoff
observation only; Center remains the sole authority for convergence and release.
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


class ReportReleaseObservationWorkerError(RuntimeError):
    pass


class ReportReleaseObservationWorker:
    producer_ref = "RC8_REPORT_RELEASE_OBSERVATION_WORKER"
    stage = "REPORT_RELEASE"

    def __init__(self, *, agent: Any, work_dir: str, now_fn: Optional[Any] = None) -> None:
        self.agent = agent
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._now = now_fn or (lambda: int(time.time()))

    def execute(self, claimed: Any) -> Dict[str, Any]:
        work = getattr(claimed, "work_item", None)
        identity = work.get("identity") if isinstance(work, dict) else None
        if not isinstance(identity, dict):
            raise ReportReleaseObservationWorkerError("CLAIMED_WORK_ITEM_IDENTITY_REQUIRED")
        if str(identity.get("stage") or "") != self.stage:
            raise ReportReleaseObservationWorkerError("WORK_ITEM_STAGE_NOT_REPORT_RELEASE")
        work_item_id = self._required(identity.get("work_item_id"), "WORK_ITEM_ID_REQUIRED")
        test_run_id = self._required(identity.get("test_run_id"), "TEST_RUN_ID_REQUIRED")
        lease_id = self._required(getattr(claimed, "lease_id", None), "WORK_ITEM_LEASE_ID_REQUIRED")
        stage_instance_id = self._required(getattr(claimed, "stage_instance_id", None), "STAGE_INSTANCE_ID_REQUIRED")
        refs = tuple(str(v).strip() for v in identity.get("scope_refs") or [] if str(v).strip())
        if not refs:
            raise ReportReleaseObservationWorkerError("REPORT_RELEASE_FROZEN_SCOPE_REFS_REQUIRED")

        self.agent.start(work_item_id, lease_id=lease_id)
        payload = {
            "schema_version": "rc8.report-release-handoff-observation.v1",
            "authority": "NODE_OBSERVATION_ONLY",
            "convergence_authority": "CENTER_ONLY",
            "release_authority": "CENTER_ONLY",
            "release_status": "HOLD",
            "may_declare_mission_converged": False,
            "may_recommend_release": False,
            "may_release": False,
            "test_run_id": test_run_id,
            "work_item_id": work_item_id,
            "stage_instance_id": stage_instance_id,
            "scope_refs": list(refs),
            "generated_at": self._now(),
        }
        artifact_id = "artifact-report-release-handoff-%s" % uuid.uuid4().hex
        artifact_ref = self._upload(artifact_id, payload, test_run_id, work_item_id, stage_instance_id, lease_id, refs)
        self.agent.append_runtime_event(runtime_event(
            event_id="evt-report-release-handoff-%s" % uuid.uuid4().hex,
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
                "authority": "NODE_OBSERVATION_ONLY",
                "convergence_authority": "CENTER_ONLY",
                "release_authority": "CENTER_ONLY",
                "release_status": "HOLD",
                "may_declare_mission_converged": False,
                "may_recommend_release": False,
                "may_release": False,
                "finished_at": self._now(),
            },
        ), lease_id=lease_id)
        terminal = self.agent.complete(work_item_id, lease_id=lease_id)
        return {
            "status": "COMPLETED",
            "attempt_id": lease_id,
            "artifact_ref": artifact_ref,
            "release_authority": "CENTER_ONLY",
            "release_status": "HOLD",
            "terminal": terminal,
        }

    def _upload(self, artifact_id: str, content: Dict[str, Any], test_run_id: str, work_item_id: str, stage_instance_id: str, lease_id: str, refs: Sequence[str]) -> str:
        target = self.work_dir / (artifact_id + ".json")
        raw = json.dumps(content, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        target.write_bytes(raw)
        manifest = ArtifactManifest(
            artifact_id=artifact_id,
            test_run_id=test_run_id,
            work_item_id=work_item_id,
            node_id=self.agent.identity.node_id,
            kind="REPORT_RELEASE_HANDOFF_OBSERVATION",
            producer_kind=RuntimeProducerKind.WORKER,
            producer_ref=self.producer_ref,
            file_name="report-release-handoff-observation.json",
            sha256=hashlib.sha256(raw).hexdigest(),
            size_bytes=len(raw),
            attempt_id=lease_id,
            refs=list(refs) + ["stage:%s" % stage_instance_id],
            metadata={"stage": self.stage, "authority": "NODE_OBSERVATION_ONLY", "release_authority": "CENTER_ONLY", "release_status": "HOLD"},
            created_at=self._now(),
        )
        self.agent.upload_artifact_file(manifest, str(target), lease_id=lease_id)
        return "artifact:%s" % artifact_id

    def _next_sequence(self, test_run_id: str) -> int:
        value = self.agent.center.get("/api/v1/test-runs/%s/nodes/%s/runtime-sequence" % (quote(test_run_id, safe=""), quote(self.agent.identity.node_id, safe="")))
        sequence = value.get("next_sequence")
        if not isinstance(sequence, int) or sequence < 0:
            raise ReportReleaseObservationWorkerError("R1_NEXT_SEQUENCE_INVALID")
        return sequence

    @staticmethod
    def _required(value: Any, error: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ReportReleaseObservationWorkerError(error)
        return normalized
