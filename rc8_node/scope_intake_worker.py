"""Deterministic SCOPE_INTAKE worker for the autonomous RC8 node.

Scope intake does not need a model. It snapshots the immutable WorkItem scope
refs into an AVAILABLE artifact, publishes Attempt truth through R1, and lets
the Center evidence gate decide whether REQUIREMENT_ANALYSIS may become READY.
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


class ScopeIntakeWorkerError(RuntimeError):
    pass


class ScopeIntakeWorker:
    producer_ref = "RC8_SCOPE_INTAKE_WORKER"

    def __init__(self, *, agent: Any, work_dir: str, now_fn: Optional[Any] = None) -> None:
        self.agent = agent
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._now = now_fn or (lambda: int(time.time()))

    def execute(self, claimed: Any) -> Dict[str, Any]:
        work = getattr(claimed, "work_item", None)
        if not isinstance(work, dict):
            raise ScopeIntakeWorkerError("CLAIMED_WORK_ITEM_REQUIRED")
        identity = work.get("identity")
        if not isinstance(identity, dict):
            raise ScopeIntakeWorkerError("WORK_ITEM_IDENTITY_REQUIRED")
        if str(identity.get("stage") or "") != "SCOPE_INTAKE":
            raise ScopeIntakeWorkerError("WORK_ITEM_STAGE_NOT_SCOPE_INTAKE")

        work_item_id = self._required(identity.get("work_item_id"), "WORK_ITEM_ID_REQUIRED")
        test_run_id = self._required(identity.get("test_run_id"), "TEST_RUN_ID_REQUIRED")
        lease_id = self._required(getattr(claimed, "lease_id", None), "WORK_ITEM_LEASE_ID_REQUIRED")
        stage_instance_id = self._required(
            getattr(claimed, "stage_instance_id", None),
            "STAGE_INSTANCE_ID_REQUIRED",
        )
        scope_refs = tuple(str(value).strip() for value in identity.get("scope_refs") or [] if str(value).strip())
        if not scope_refs:
            raise ScopeIntakeWorkerError("SCOPE_INTAKE_REFS_REQUIRED")

        attempt_id = "att-scope-intake-%s" % uuid.uuid4().hex
        input_snapshot_ref = "scope-intake:%s" % hashlib.sha256(
            "\x1f".join(scope_refs).encode("utf-8")
        ).hexdigest()
        self.agent.start(work_item_id, lease_id=lease_id)
        self._event(
            test_run_id=test_run_id,
            work_item_id=work_item_id,
            lease_id=lease_id,
            event_type="ATTEMPT_STARTED",
            attempt_id=attempt_id,
            refs=scope_refs,
            data={
                "stage_instance_id": stage_instance_id,
                "input_snapshot_ref": input_snapshot_ref,
                "started_at": self._now(),
            },
        )

        content = {
            "schema_version": "rc8.scope-intake.v1",
            "test_run_id": test_run_id,
            "work_item_id": work_item_id,
            "stage_instance_id": stage_instance_id,
            "scope_refs": list(scope_refs),
            "input_snapshot_ref": input_snapshot_ref,
            "generated_at": self._now(),
        }
        artifact_id = "artifact-scope-intake-%s" % uuid.uuid4().hex
        artifact_ref = self._upload_json_artifact(
            artifact_id=artifact_id,
            content=content,
            test_run_id=test_run_id,
            work_item_id=work_item_id,
            stage_instance_id=stage_instance_id,
            attempt_id=attempt_id,
            lease_id=lease_id,
            refs=scope_refs,
        )
        self._event(
            test_run_id=test_run_id,
            work_item_id=work_item_id,
            lease_id=lease_id,
            event_type="ATTEMPT_COMPLETED",
            attempt_id=attempt_id,
            refs=scope_refs,
            data={
                "stage_instance_id": stage_instance_id,
                "input_snapshot_ref": input_snapshot_ref,
                "evidence_refs": [artifact_ref],
                "finished_at": self._now(),
            },
        )
        terminal = self.agent.complete(work_item_id, lease_id=lease_id)
        return {
            "status": "COMPLETED",
            "attempt_id": attempt_id,
            "artifact_ref": artifact_ref,
            "terminal": terminal,
        }

    def _upload_json_artifact(
        self,
        *,
        artifact_id: str,
        content: Dict[str, Any],
        test_run_id: str,
        work_item_id: str,
        stage_instance_id: str,
        attempt_id: str,
        lease_id: str,
        refs: Sequence[str],
    ) -> str:
        target = self.work_dir / (artifact_id + ".json")
        raw = json.dumps(content, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        target.write_bytes(raw)
        manifest = ArtifactManifest(
            artifact_id=artifact_id,
            test_run_id=test_run_id,
            work_item_id=work_item_id,
            node_id=self.agent.identity.node_id,
            kind="SCOPE_INTAKE",
            producer_kind=RuntimeProducerKind.WORKER,
            producer_ref=self.producer_ref,
            file_name="scope-intake.json",
            sha256=hashlib.sha256(raw).hexdigest(),
            size_bytes=len(raw),
            attempt_id=attempt_id,
            refs=list(refs) + ["stage:%s" % stage_instance_id],
            metadata={"stage": "SCOPE_INTAKE"},
            created_at=self._now(),
        )
        self.agent.upload_artifact_file(manifest, str(target), lease_id=lease_id)
        return "artifact:%s" % artifact_id

    def _event(
        self,
        *,
        test_run_id: str,
        work_item_id: str,
        lease_id: str,
        event_type: str,
        attempt_id: str,
        refs: Sequence[str],
        data: Dict[str, Any],
    ) -> None:
        self.agent.append_runtime_event(
            runtime_event(
                event_id="evt-scope-intake-%s" % uuid.uuid4().hex,
                test_run_id=test_run_id,
                work_item_id=work_item_id,
                node_id=self.agent.identity.node_id,
                producer_kind=RuntimeProducerKind.WORKER,
                producer_ref=self.producer_ref,
                event_type=event_type,
                sequence=self._next_sequence(test_run_id),
                attempt_id=attempt_id,
                refs=list(refs),
                data=data,
            ),
            lease_id=lease_id,
        )

    def _next_sequence(self, test_run_id: str) -> int:
        value = self.agent.center.get(
            "/api/v1/test-runs/%s/nodes/%s/runtime-sequence" % (
                quote(test_run_id, safe=""),
                quote(self.agent.identity.node_id, safe=""),
            )
        )
        sequence = value.get("next_sequence")
        if not isinstance(sequence, int) or sequence < 0:
            raise ScopeIntakeWorkerError("R1_NEXT_SEQUENCE_INVALID")
        return sequence

    @staticmethod
    def _required(value: Any, error: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ScopeIntakeWorkerError(error)
        return normalized
