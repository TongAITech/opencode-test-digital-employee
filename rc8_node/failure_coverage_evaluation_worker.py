"""Fail-closed N8 FAILURE_COVERAGE_EVALUATION node worker.

Produces diagnosis/gap-routing observations only. Canonical GapRouter decisions,
MissionNode state, quality and release authority remain in Center.
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


class FailureCoverageEvaluationWorkerError(RuntimeError):
    pass


class FailureCoverageEvaluationWorker:
    producer_ref = "RC8_FAILURE_COVERAGE_EVALUATION_WORKER"

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
            raise FailureCoverageEvaluationWorkerError("CLAIMED_WORK_ITEM_IDENTITY_REQUIRED")
        if str(identity.get("stage") or "") != "FAILURE_COVERAGE_EVALUATION":
            raise FailureCoverageEvaluationWorkerError("WORK_ITEM_STAGE_NOT_FAILURE_COVERAGE_EVALUATION")
        work_item_id = self._required(identity.get("work_item_id"), "WORK_ITEM_ID_REQUIRED")
        test_run_id = self._required(identity.get("test_run_id"), "TEST_RUN_ID_REQUIRED")
        lease_id = self._required(getattr(claimed, "lease_id", None), "WORK_ITEM_LEASE_ID_REQUIRED")
        stage_instance_id = self._required(getattr(claimed, "stage_instance_id", None), "STAGE_INSTANCE_ID_REQUIRED")
        refs = tuple(str(v).strip() for v in identity.get("scope_refs") or [] if str(v).strip())
        if not refs:
            raise FailureCoverageEvaluationWorkerError("N8_FROZEN_SCOPE_REFS_REQUIRED")
        self.agent.start(work_item_id, lease_id=lease_id)
        try:
            result = self.dsh_runner.run(self._prompt(refs))
            candidate = self.validate_candidate(result.output)
        except DshJsonRunnerError as exc:
            raise FailureCoverageEvaluationWorkerError("FAILURE_COVERAGE_DSH_FAILED:%s" % exc.reason)
        payload = {
            "schema_version": "rc8.failure-coverage-evaluation-observation.v1",
            "authority": "NODE_OBSERVATION_ONLY",
            "gap_router_authority": "CENTER_ONLY",
            "test_run_id": test_run_id,
            "work_item_id": work_item_id,
            "stage_instance_id": stage_instance_id,
            "scope_refs": list(refs),
            "candidate": candidate,
            "dsh_session_id": result.session_id,
            "tool_calls": list(result.tool_calls),
            "generated_at": self._now(),
        }
        artifact_id = "artifact-failure-coverage-%s" % uuid.uuid4().hex
        artifact_ref = self._upload(artifact_id, payload, test_run_id, work_item_id, stage_instance_id, lease_id, refs)
        self.agent.append_runtime_event(runtime_event(
            event_id="evt-failure-coverage-%s" % uuid.uuid4().hex,
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
                "coverage_denominator_refs": candidate["coverage_denominator_refs"],
                "gap_router_authority": "CENTER_ONLY",
                "authority": "NODE_OBSERVATION_ONLY",
                "finished_at": self._now(),
            },
        ), lease_id=lease_id)
        terminal = self.agent.complete(work_item_id, lease_id=lease_id)
        return {
            "status": "COMPLETED",
            "attempt_id": lease_id,
            "artifact_ref": artifact_ref,
            "gap_router_authority": "CENTER_ONLY",
            "terminal": terminal,
        }

    @staticmethod
    def validate_candidate(value: Any) -> Dict[str, Any]:
        if not isinstance(value, dict):
            raise FailureCoverageEvaluationWorkerError("FAILURE_COVERAGE_OUTPUT_OBJECT_REQUIRED")
        denominator = value.get("coverage_denominator_refs")
        evidence = value.get("evidence_refs")
        gaps = value.get("gaps")
        for name, refs in (("COVERAGE_DENOMINATOR_REFS", denominator), ("EVIDENCE_REFS", evidence)):
            if not isinstance(refs, list) or not refs or any(not str(v).strip() for v in refs):
                raise FailureCoverageEvaluationWorkerError("%s_NONEMPTY_REQUIRED" % name)
            normalized = [str(v).strip() for v in refs]
            if len(set(normalized)) != len(normalized):
                raise FailureCoverageEvaluationWorkerError("%s_UNIQUE_REQUIRED" % name)
        if not isinstance(gaps, list):
            raise FailureCoverageEvaluationWorkerError("GAPS_LIST_REQUIRED")
        known = set(str(v).strip() for v in denominator)
        seen = set()
        for gap in gaps:
            if not isinstance(gap, dict):
                raise FailureCoverageEvaluationWorkerError("GAP_OBJECT_REQUIRED")
            gap_id = str(gap.get("gap_id") or "").strip()
            ref = str(gap.get("denominator_ref") or "").strip()
            reason = str(gap.get("reason") or "").strip()
            route = str(gap.get("suggested_route") or "").strip()
            if not gap_id or not ref or not reason or not route:
                raise FailureCoverageEvaluationWorkerError("GAP_FIELDS_REQUIRED")
            if gap_id in seen:
                raise FailureCoverageEvaluationWorkerError("GAP_ID_UNIQUE_REQUIRED")
            if ref not in known:
                raise FailureCoverageEvaluationWorkerError("GAP_DENOMINATOR_REF_UNKNOWN")
            seen.add(gap_id)
        result = dict(value)
        result["authority"] = "NODE_OBSERVATION_ONLY"
        result["gap_router_authority"] = "CENTER_ONLY"
        return result

    def _upload(self, artifact_id: str, content: Dict[str, Any], test_run_id: str, work_item_id: str, stage_instance_id: str, lease_id: str, refs: Sequence[str]) -> str:
        target = self.work_dir / (artifact_id + ".json")
        raw = json.dumps(content, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        target.write_bytes(raw)
        manifest = ArtifactManifest(
            artifact_id=artifact_id,
            test_run_id=test_run_id,
            work_item_id=work_item_id,
            node_id=self.agent.identity.node_id,
            kind="FAILURE_COVERAGE_EVALUATION_OBSERVATION",
            producer_kind=RuntimeProducerKind.WORKER,
            producer_ref=self.producer_ref,
            file_name="failure-coverage-evaluation-observation.json",
            sha256=hashlib.sha256(raw).hexdigest(),
            size_bytes=len(raw),
            attempt_id=lease_id,
            refs=list(refs) + ["stage:%s" % stage_instance_id],
            metadata={"stage": "FAILURE_COVERAGE_EVALUATION", "authority": "NODE_OBSERVATION_ONLY", "gap_router_authority": "CENTER_ONLY"},
            created_at=self._now(),
        )
        self.agent.upload_artifact_file(manifest, str(target), lease_id=lease_id)
        return "artifact:%s" % artifact_id

    def _next_sequence(self, test_run_id: str) -> int:
        value = self.agent.center.get("/api/v1/test-runs/%s/nodes/%s/runtime-sequence" %
            (quote(test_run_id, safe=""), quote(self.agent.identity.node_id, safe="")))
        sequence = value.get("next_sequence")
        if not isinstance(sequence, int) or sequence < 0:
            raise FailureCoverageEvaluationWorkerError("R1_NEXT_SEQUENCE_INVALID")
        return sequence

    @staticmethod
    def _prompt(refs: Sequence[str]) -> str:
        return (
            "You are RC8 N8 FAILURE_COVERAGE_EVALUATION. Use only frozen refs %s and current execution/coverage Evidence. "
            "Return strict JSON with non-empty unique coverage_denominator_refs, non-empty unique evidence_refs, and gaps. "
            "Each gap must contain unique gap_id, denominator_ref from the supplied denominator, reason, and suggested_route. "
            "Do not claim canonical routing, MissionNode PASS, product quality or release; Center owns GapRouter and final authority."
            % json.dumps(list(refs), ensure_ascii=False)
        )

    @staticmethod
    def _required(value: Any, error: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise FailureCoverageEvaluationWorkerError(error)
        return normalized
