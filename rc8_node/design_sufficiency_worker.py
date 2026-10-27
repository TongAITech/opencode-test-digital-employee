"""Fail-closed N4 DESIGN_SUFFICIENCY node worker.

Evaluates exactly one frozen TEST_DESIGN artifact. The result is node-local
observation/Evidence only; Center retains final design-sufficiency authority.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple
from urllib.parse import quote

from rc8_runtime import RuntimeProducerKind, runtime_event
from rc8_runtime.artifacts import ArtifactManifest


class DesignSufficiencyWorkerError(RuntimeError):
    pass


class DesignSufficiencyWorker:
    producer_ref = "RC8_DESIGN_SUFFICIENCY_WORKER"
    policy_version = "rc8.design-sufficiency.v1"

    def __init__(self, *, agent: Any, work_dir: str, now_fn: Optional[Any] = None) -> None:
        self.agent = agent
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._now = now_fn or (lambda: int(time.time()))

    def execute(self, claimed: Any) -> Dict[str, Any]:
        work = getattr(claimed, "work_item", None)
        identity = work.get("identity") if isinstance(work, dict) else None
        if not isinstance(identity, dict):
            raise DesignSufficiencyWorkerError("CLAIMED_WORK_ITEM_IDENTITY_REQUIRED")
        if str(identity.get("stage") or "") != "DESIGN_SUFFICIENCY":
            raise DesignSufficiencyWorkerError("WORK_ITEM_STAGE_NOT_DESIGN_SUFFICIENCY")
        work_item_id = self._required(identity.get("work_item_id"), "WORK_ITEM_ID_REQUIRED")
        test_run_id = self._required(identity.get("test_run_id"), "TEST_RUN_ID_REQUIRED")
        lease_id = self._required(getattr(claimed, "lease_id", None), "WORK_ITEM_LEASE_ID_REQUIRED")
        stage_instance_id = self._required(getattr(claimed, "stage_instance_id", None), "STAGE_INSTANCE_ID_REQUIRED")
        refs = tuple(str(v).strip() for v in identity.get("scope_refs") or [] if str(v).strip())
        source_ref, source_id, design = self._load_design(work_item_id, lease_id, refs)
        observation = self.evaluate(source_id, design)

        self.agent.start(work_item_id, lease_id=lease_id)
        payload = {"schema_version": "rc8.design-sufficiency-observation.v1",
                   "authority": "NODE_OBSERVATION_ONLY", "policy_version": self.policy_version,
                   "test_run_id": test_run_id, "work_item_id": work_item_id,
                   "stage_instance_id": stage_instance_id, "source_artifact_ref": source_ref,
                   "candidate_sufficient": observation["candidate_sufficient"],
                   "missing": observation["missing"], "generated_at": self._now()}
        artifact_id = "artifact-design-suff-%s" % uuid.uuid4().hex
        target = self.work_dir / (artifact_id + ".json")
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        target.write_bytes(raw)
        manifest = ArtifactManifest(
            artifact_id=artifact_id, test_run_id=test_run_id, work_item_id=work_item_id,
            node_id=self.agent.identity.node_id, kind="DESIGN_SUFFICIENCY_OBSERVATION",
            producer_kind=RuntimeProducerKind.WORKER, producer_ref=self.producer_ref,
            file_name="design-sufficiency-observation.json", sha256=hashlib.sha256(raw).hexdigest(),
            size_bytes=len(raw), attempt_id=lease_id,
            refs=list(refs) + [source_ref, "stage:%s" % stage_instance_id],
            metadata={"stage": "DESIGN_SUFFICIENCY", "authority": "NODE_OBSERVATION_ONLY",
                      "policy_version": self.policy_version}, created_at=self._now())
        self.agent.upload_artifact_file(manifest, str(target), lease_id=lease_id)
        artifact_ref = "artifact:%s" % artifact_id
        self.agent.append_runtime_event(runtime_event(
            event_id="evt-design-suff-%s" % uuid.uuid4().hex, test_run_id=test_run_id,
            work_item_id=work_item_id, node_id=self.agent.identity.node_id,
            producer_kind=RuntimeProducerKind.WORKER, producer_ref=self.producer_ref,
            event_type="ATTEMPT_COMPLETED", sequence=self._next_sequence(test_run_id),
            attempt_id=lease_id, refs=list(refs), data={"stage_instance_id": stage_instance_id,
                "evidence_refs": [artifact_ref], "source_artifact_ref": source_ref,
                "candidate_sufficient": observation["candidate_sufficient"],
                "missing": observation["missing"], "authority": "NODE_OBSERVATION_ONLY",
                "finished_at": self._now()}), lease_id=lease_id)
        terminal = self.agent.complete(work_item_id, lease_id=lease_id)
        return {"status": "COMPLETED", "artifact_ref": artifact_ref,
                "candidate_sufficient": observation["candidate_sufficient"],
                "missing": observation["missing"], "terminal": terminal}

    @staticmethod
    def evaluate(artifact_id: str, design: Mapping[str, Any]) -> Dict[str, Any]:
        if not str(artifact_id or "").strip():
            raise DesignSufficiencyWorkerError("TEST_DESIGN_ARTIFACT_ID_REQUIRED")
        if not isinstance(design, Mapping) or design.get("schema_version") != "rc8.test-design.v1":
            raise DesignSufficiencyWorkerError("TEST_DESIGN_ARTIFACT_REQUIRED")
        candidate = design.get("candidate")
        if not isinstance(candidate, Mapping):
            raise DesignSufficiencyWorkerError("TEST_DESIGN_CANDIDATE_REQUIRED")
        risks = candidate.get("risk_denominator")
        cases = candidate.get("test_cases")
        evidence = candidate.get("evidence_refs")
        missing = []
        if not isinstance(risks, list) or not risks:
            missing.append("risk_denominator:non-empty")
            denominator = set()
        else:
            normalized = [str(v).strip() for v in risks if str(v).strip()]
            if len(normalized) != len(risks) or len(set(normalized)) != len(normalized):
                missing.append("risk_denominator:unique-nonblank")
            denominator = set(normalized)
        if not isinstance(evidence, list) or not [v for v in evidence if str(v).strip()]:
            missing.append("evidence_refs:non-empty")
        covered = set()
        if not isinstance(cases, list) or not cases:
            missing.append("test_cases:non-empty")
        else:
            for case in cases:
                if not isinstance(case, Mapping):
                    missing.append("test_case:object")
                    continue
                mapped = {str(v).strip() for v in case.get("risk_ids") or [] if str(v).strip()}
                if not mapped or not mapped.issubset(denominator):
                    missing.append("test_case:risk_mapping_valid")
                covered.update(mapped)
                for field in ("preconditions", "steps", "expected_results"):
                    if not isinstance(case.get(field), list) or not case.get(field):
                        missing.append("test_case:%s_non_empty" % field)
        if denominator and covered != denominator:
            missing.append("risk_denominator:fully_covered")
        deduped = list(dict.fromkeys(missing))
        return {"candidate_sufficient": not deduped, "missing": deduped}

    def _load_design(self, work_item_id: str, lease_id: str, refs: Sequence[str]) -> Tuple[str, str, Dict[str, Any]]:
        candidates = []
        headers = {"X-RC8-Node-Id": self.agent.identity.node_id, "X-RC8-Lease-Id": lease_id}
        for ref in refs:
            if not ref.startswith("artifact:"):
                continue
            artifact_id = ref.split(":", 1)[1]
            payload = self.agent.center.get("/api/v1/artifacts/%s/json?work_item_id=%s" %
                (quote(artifact_id, safe=""), quote(work_item_id, safe="")), headers=headers)
            content = payload.get("content")
            if isinstance(content, dict) and content.get("schema_version") == "rc8.test-design.v1":
                candidates.append((ref, artifact_id, content))
        if len(candidates) != 1:
            raise DesignSufficiencyWorkerError("TEST_DESIGN_ARTIFACT_REQUIRED_EXACTLY_ONCE")
        return candidates[0]

    def _next_sequence(self, test_run_id: str) -> int:
        payload = self.agent.center.get("/api/v1/test-runs/%s/nodes/%s/runtime-sequence" %
            (quote(test_run_id, safe=""), quote(self.agent.identity.node_id, safe="")))
        value = payload.get("next_sequence")
        if not isinstance(value, int) or value < 0:
            raise DesignSufficiencyWorkerError("R1_NEXT_SEQUENCE_INVALID")
        return value

    @staticmethod
    def _required(value: Any, error: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise DesignSufficiencyWorkerError(error)
        return normalized
