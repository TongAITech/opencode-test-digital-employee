"""Fail-closed N10 mission-sufficiency observation worker.

The node assembles evidence-backed convergence inputs through the normal WorkItem/Attempt,
DSH, Evidence and R1 path. Center remains the sole authority for test sufficiency,
product quality, release recommendation and mission convergence.
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


class MissionSufficiencyObservationWorkerError(RuntimeError):
    pass


class MissionSufficiencyObservationWorker:
    producer_ref = "RC8_MISSION_SUFFICIENCY_OBSERVATION_WORKER"
    stage = "MISSION_SUFFICIENCY"

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
            raise MissionSufficiencyObservationWorkerError("CLAIMED_WORK_ITEM_IDENTITY_REQUIRED")
        if str(identity.get("stage") or "") != self.stage:
            raise MissionSufficiencyObservationWorkerError("WORK_ITEM_STAGE_NOT_MISSION_SUFFICIENCY")
        work_item_id = self._required(identity.get("work_item_id"), "WORK_ITEM_ID_REQUIRED")
        test_run_id = self._required(identity.get("test_run_id"), "TEST_RUN_ID_REQUIRED")
        lease_id = self._required(getattr(claimed, "lease_id", None), "WORK_ITEM_LEASE_ID_REQUIRED")
        stage_instance_id = self._required(getattr(claimed, "stage_instance_id", None), "STAGE_INSTANCE_ID_REQUIRED")
        refs = tuple(str(v).strip() for v in identity.get("scope_refs") or [] if str(v).strip())
        if not refs:
            raise MissionSufficiencyObservationWorkerError("N10_FROZEN_SCOPE_REFS_REQUIRED")
        self.agent.start(work_item_id, lease_id=lease_id)
        try:
            result = self.dsh_runner.run(self._prompt(refs))
            candidate = self.validate_candidate(result.output)
        except DshJsonRunnerError as exc:
            raise MissionSufficiencyObservationWorkerError("MISSION_SUFFICIENCY_DSH_FAILED:%s" % exc.reason)
        payload = {
            "schema_version": "rc8.mission-sufficiency-observation.v1",
            "authority": "NODE_OBSERVATION_ONLY",
            "convergence_authority": "CENTER_ONLY",
            "test_run_id": test_run_id,
            "work_item_id": work_item_id,
            "stage_instance_id": stage_instance_id,
            "scope_refs": list(refs),
            "candidate": candidate,
            "dsh_session_id": result.session_id,
            "tool_calls": list(result.tool_calls),
            "generated_at": self._now(),
        }
        artifact_id = "artifact-mission-sufficiency-%s" % uuid.uuid4().hex
        artifact_ref = self._upload(artifact_id, payload, test_run_id, work_item_id, stage_instance_id, lease_id, refs)
        self.agent.append_runtime_event(runtime_event(
            event_id="evt-mission-sufficiency-%s" % uuid.uuid4().hex,
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
                "convergence_authority": "CENTER_ONLY",
                "authority": "NODE_OBSERVATION_ONLY",
                "may_declare_mission_converged": False,
                "may_recommend_release": False,
                "active_blocking_gaps": list(candidate["active_blocking_gaps"]),
                "finished_at": self._now(),
            },
        ), lease_id=lease_id)
        terminal = self.agent.complete(work_item_id, lease_id=lease_id)
        return {"status": "COMPLETED", "attempt_id": lease_id, "artifact_ref": artifact_ref, "convergence_authority": "CENTER_ONLY", "terminal": terminal}

    @staticmethod
    def validate_candidate(value: Any) -> Dict[str, Any]:
        if not isinstance(value, dict):
            raise MissionSufficiencyObservationWorkerError("N10_OUTPUT_OBJECT_REQUIRED")
        evidence = value.get("evidence_refs")
        if not isinstance(evidence, list) or not evidence or any(not str(ref).strip() for ref in evidence):
            raise MissionSufficiencyObservationWorkerError("N10_EVIDENCE_DENOMINATOR_NONEMPTY_REQUIRED")
        normalized = [str(ref).strip() for ref in evidence]
        if len(set(normalized)) != len(normalized):
            raise MissionSufficiencyObservationWorkerError("N10_EVIDENCE_DENOMINATOR_UNIQUE_REQUIRED")
        dimensions = value.get("dimensions")
        if not isinstance(dimensions, dict):
            raise MissionSufficiencyObservationWorkerError("N10_DIMENSIONS_OBJECT_REQUIRED")
        required = ("test_sufficiency", "product_quality", "release_recommendation", "residual_risk")
        missing = [name for name in required if not isinstance(dimensions.get(name), dict)]
        if missing:
            raise MissionSufficiencyObservationWorkerError("N10_REQUIRED_DIMENSIONS_MISSING:%s" % ",".join(missing))
        for name in required:
            item = dimensions[name]
            state = str(item.get("state") or "").strip().upper()
            refs = item.get("evidence_refs")
            if not state:
                raise MissionSufficiencyObservationWorkerError("N10_DIMENSION_STATE_REQUIRED:%s" % name)
            if not isinstance(refs, list) or not refs or any(not str(ref).strip() for ref in refs):
                raise MissionSufficiencyObservationWorkerError("N10_DIMENSION_EVIDENCE_REQUIRED:%s" % name)
            if any(str(ref).strip() not in normalized for ref in refs):
                raise MissionSufficiencyObservationWorkerError("N10_DIMENSION_EVIDENCE_OUTSIDE_DENOMINATOR:%s" % name)
        gaps = value.get("active_blocking_gaps")
        if not isinstance(gaps, list):
            raise MissionSufficiencyObservationWorkerError("N10_ACTIVE_BLOCKING_GAPS_LIST_REQUIRED")
        if any(not str(gap).strip() for gap in gaps):
            raise MissionSufficiencyObservationWorkerError("N10_ACTIVE_BLOCKING_GAP_REF_REQUIRED")
        result = dict(value)
        result["authority"] = "NODE_OBSERVATION_ONLY"
        result["convergence_authority"] = "CENTER_ONLY"
        result["may_declare_mission_converged"] = False
        result["may_recommend_release"] = False
        return result

    def _upload(self, artifact_id: str, content: Dict[str, Any], test_run_id: str, work_item_id: str, stage_instance_id: str, lease_id: str, refs: Sequence[str]) -> str:
        target = self.work_dir / (artifact_id + ".json")
        raw = json.dumps(content, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        target.write_bytes(raw)
        manifest = ArtifactManifest(artifact_id=artifact_id, test_run_id=test_run_id, work_item_id=work_item_id, node_id=self.agent.identity.node_id, kind="MISSION_SUFFICIENCY_OBSERVATION", producer_kind=RuntimeProducerKind.WORKER, producer_ref=self.producer_ref, file_name="mission-sufficiency-observation.json", sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw), attempt_id=lease_id, refs=list(refs) + ["stage:%s" % stage_instance_id], metadata={"stage": self.stage, "authority": "NODE_OBSERVATION_ONLY", "convergence_authority": "CENTER_ONLY"}, created_at=self._now())
        self.agent.upload_artifact_file(manifest, str(target), lease_id=lease_id)
        return "artifact:%s" % artifact_id

    def _next_sequence(self, test_run_id: str) -> int:
        value = self.agent.center.get("/api/v1/test-runs/%s/nodes/%s/runtime-sequence" % (quote(test_run_id, safe=""), quote(self.agent.identity.node_id, safe="")))
        sequence = value.get("next_sequence")
        if not isinstance(sequence, int) or sequence < 0:
            raise MissionSufficiencyObservationWorkerError("R1_NEXT_SEQUENCE_INVALID")
        return sequence

    @staticmethod
    def _prompt(refs: Sequence[str]) -> str:
        return ("You are RC8 N10 mission-sufficiency observation. Use only frozen refs %s. Return strict JSON with non-empty unique evidence_refs, four independent dimensions test_sufficiency/product_quality/release_recommendation/residual_risk each with state and evidence_refs inside that denominator, plus explicit active_blocking_gaps. Do not declare MissionNode PASS, MISSION_CONVERGED, product quality, test sufficiency or release; Center owns all final convergence authority." % json.dumps(list(refs), ensure_ascii=False))

    @staticmethod
    def _required(value: Any, error: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise MissionSufficiencyObservationWorkerError(error)
        return normalized
