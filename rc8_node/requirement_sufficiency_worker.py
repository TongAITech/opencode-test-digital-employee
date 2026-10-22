"""Deterministic REQUIREMENT_SUFFICIENCY worker.

DSH/model output is an analysis candidate, never sufficiency truth.  This worker
reads the exact AVAILABLE REQUIREMENT_ANALYSIS artifact referenced by its
leased WorkItem, applies a versioned deterministic policy, publishes a policy
artifact, then writes GAP_OPENED/GAP_CLOSED and SUFFICIENCY_EVALUATED facts to
R1 before completing the WorkItem.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote

from rc8_runtime import RuntimeProducerKind, runtime_event
from rc8_runtime.artifacts import ArtifactManifest


class RequirementSufficiencyWorkerError(RuntimeError):
    pass


POLICY_VERSION = "rc8.requirement-sufficiency.v1"
EVALUATOR_ID = "RC8_REQUIREMENT_SUFFICIENCY_POLICY"


class RequirementSufficiencyWorker:
    producer_ref = "RC8_REQUIREMENT_SUFFICIENCY_WORKER"

    def __init__(self, *, agent: Any, work_dir: str, now_fn: Optional[Any] = None) -> None:
        self.agent = agent
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._now = now_fn or (lambda: int(time.time()))

    def execute(self, claimed: Any) -> Dict[str, Any]:
        work = getattr(claimed, "work_item", None)
        if not isinstance(work, dict):
            raise RequirementSufficiencyWorkerError("CLAIMED_WORK_ITEM_REQUIRED")
        identity = work.get("identity")
        if not isinstance(identity, dict):
            raise RequirementSufficiencyWorkerError("WORK_ITEM_IDENTITY_REQUIRED")
        if str(identity.get("stage") or "") != "REQUIREMENT_SUFFICIENCY":
            raise RequirementSufficiencyWorkerError("WORK_ITEM_STAGE_NOT_REQUIREMENT_SUFFICIENCY")

        work_item_id = self._required(identity.get("work_item_id"), "WORK_ITEM_ID_REQUIRED")
        test_run_id = self._required(identity.get("test_run_id"), "TEST_RUN_ID_REQUIRED")
        lease_id = self._required(getattr(claimed, "lease_id", None), "WORK_ITEM_LEASE_ID_REQUIRED")
        stage_instance_id = self._required(
            getattr(claimed, "stage_instance_id", None),
            "STAGE_INSTANCE_ID_REQUIRED",
        )
        scope_refs = tuple(str(value).strip() for value in identity.get("scope_refs") or [] if str(value).strip())
        requirement_revision_id = self._one_ref(scope_refs, "requirement-revision:")
        scope_revision_id = self._one_ref(scope_refs, "scope-revision:")
        gap_ids = tuple(dict.fromkeys(value[len("gap:"):] for value in scope_refs if value.startswith("gap:") and value[len("gap:"):]))
        analysis_ref, analysis = self._load_requirement_analysis(
            test_run_id=test_run_id,
            work_item_id=work_item_id,
            lease_id=lease_id,
            scope_refs=scope_refs,
        )
        if str(analysis.get("requirement_revision_id") or "") != requirement_revision_id:
            raise RequirementSufficiencyWorkerError("ANALYSIS_REQUIREMENT_REVISION_MISMATCH")
        if str(analysis.get("scope_revision_id") or "") != scope_revision_id:
            raise RequirementSufficiencyWorkerError("ANALYSIS_SCOPE_REVISION_MISMATCH")

        candidate = analysis.get("candidate")
        if not isinstance(candidate, dict):
            raise RequirementSufficiencyWorkerError("REQUIREMENT_ANALYSIS_CANDIDATE_REQUIRED")
        evaluation = self._evaluate(candidate)
        result = "SUFFICIENT" if not evaluation["unsatisfied_requirement_refs"] else "INSUFFICIENT"
        gap_id = None
        if result == "INSUFFICIENT":
            gap_id = self._gap_id(test_run_id, stage_instance_id, analysis_ref)

        attempt_id = "att-req-suff-%s" % uuid.uuid4().hex
        input_snapshot_ref = "requirement-revision:%s|scope-revision:%s|%s" % (
            requirement_revision_id,
            scope_revision_id,
            analysis_ref,
        )
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

        policy_artifact = {
            "schema_version": "rc8.requirement-sufficiency.v1",
            "test_run_id": test_run_id,
            "work_item_id": work_item_id,
            "stage_instance_id": stage_instance_id,
            "requirement_revision_id": requirement_revision_id,
            "scope_revision_id": scope_revision_id,
            "analysis_artifact_ref": analysis_ref,
            "policy_version": POLICY_VERSION,
            "evaluator_id": EVALUATOR_ID,
            "result": result,
            "dimension_refs": evaluation["dimension_refs"],
            "satisfied_requirement_refs": evaluation["satisfied_requirement_refs"],
            "unsatisfied_requirement_refs": evaluation["unsatisfied_requirement_refs"],
            "gap_id": gap_id,
            "generated_at": self._now(),
        }
        artifact_id = "artifact-req-suff-%s" % uuid.uuid4().hex
        artifact_ref = self._upload_json_artifact(
            artifact_id=artifact_id,
            content=policy_artifact,
            test_run_id=test_run_id,
            work_item_id=work_item_id,
            stage_instance_id=stage_instance_id,
            attempt_id=attempt_id,
            lease_id=lease_id,
            refs=list(scope_refs) + [analysis_ref],
        )

        if result == "INSUFFICIENT":
            self._event(
                test_run_id=test_run_id,
                work_item_id=work_item_id,
                lease_id=lease_id,
                event_type="GAP_OPENED",
                attempt_id=attempt_id,
                refs=scope_refs,
                data={
                    "gap_id": gap_id,
                    "source_stage_instance_id": stage_instance_id,
                    "gap_type": "REQUIREMENT_UNCLEAR",
                    "severity": "P1",
                    "description": "需求分析充分度未达到策略要求：%s" % ",".join(evaluation["unsatisfied_requirement_refs"]),
                    "owner_stage": "REQUIREMENT_ANALYSIS",
                    "repair_strategy": "基于冻结 RequirementRevision/ScopeRevision 补充分析后重新评估",
                    "evidence_refs": [artifact_ref],
                    "invalidates": [],
                },
            )
        else:
            for existing_gap_id in gap_ids:
                self._event(
                    test_run_id=test_run_id,
                    work_item_id=work_item_id,
                    lease_id=lease_id,
                    event_type="GAP_CLOSED",
                    attempt_id=attempt_id,
                    refs=scope_refs,
                    data={
                        "gap_id": existing_gap_id,
                        "closure_evidence_refs": [artifact_ref],
                    },
                )

        unresolved_gap_ids = [gap_id] if gap_id else []
        self._event(
            test_run_id=test_run_id,
            work_item_id=work_item_id,
            lease_id=lease_id,
            event_type="SUFFICIENCY_EVALUATED",
            attempt_id=attempt_id,
            refs=scope_refs,
            data={
                "evaluation_id": "eval-req-%s" % uuid.uuid4().hex,
                "scope": "STAGE",
                "subject_id": stage_instance_id,
                "evaluator_id": EVALUATOR_ID,
                "policy_version": POLICY_VERSION,
                "result": result,
                "dimension_refs": evaluation["dimension_refs"],
                "evidence_refs": [artifact_ref],
                "satisfied_requirement_refs": evaluation["satisfied_requirement_refs"],
                "unsatisfied_requirement_refs": evaluation["unsatisfied_requirement_refs"],
                "unresolved_gap_ids": unresolved_gap_ids,
                "accepted_waiver_ids": [],
                "explanation": "需求分析达到最小可追溯性与正常路径策略" if result == "SUFFICIENT" else "需求分析存在未满足的充分度维度",
            },
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
                "gap_refs": unresolved_gap_ids,
                "finished_at": self._now(),
            },
        )
        terminal = self.agent.complete(work_item_id, lease_id=lease_id)
        return {
            "status": "COMPLETED",
            "result": result,
            "attempt_id": attempt_id,
            "artifact_ref": artifact_ref,
            "gap_id": gap_id,
            "closed_gap_ids": list(gap_ids) if result == "SUFFICIENT" else [],
            "terminal": terminal,
        }

    def _load_requirement_analysis(
        self,
        *,
        test_run_id: str,
        work_item_id: str,
        lease_id: str,
        scope_refs: Sequence[str],
    ) -> Tuple[str, Dict[str, Any]]:
        candidates: List[Tuple[str, Dict[str, Any]]] = []
        headers = {
            "X-RC8-Node-Id": self.agent.identity.node_id,
            "X-RC8-Lease-Id": lease_id,
        }
        for ref in scope_refs:
            if not ref.startswith("artifact:"):
                continue
            artifact_id = ref.split(":", 1)[1]
            payload = self.agent.center.get(
                "/api/v1/artifacts/%s/json?work_item_id=%s" % (
                    quote(artifact_id, safe=""),
                    quote(work_item_id, safe=""),
                ),
                headers=headers,
            )
            content = payload.get("content")
            if isinstance(content, dict) and content.get("schema_version") == "rc8.requirement-analysis.v1":
                candidates.append((ref, content))
        if len(candidates) != 1:
            raise RequirementSufficiencyWorkerError("REQUIREMENT_ANALYSIS_ARTIFACT_REQUIRED_EXACTLY_ONCE")
        return candidates[0]

    @staticmethod
    def _evaluate(candidate: Dict[str, Any]) -> Dict[str, List[str]]:
        unsatisfied: List[str] = []
        dimensions = [
            "requirement-source-assertions",
            "requirement-atomic-statements",
            "requirement-traceability",
            "requirement-evidence",
            "requirement-normal-path",
            "requirement-open-question",
        ]
        source_assertions = candidate.get("source_assertions")
        atomic = candidate.get("atomic_statements")
        traces = candidate.get("trace_links")
        evidence = candidate.get("evidence_refs")
        normal_paths = candidate.get("normal_paths")
        if not isinstance(source_assertions, list) or not source_assertions:
            unsatisfied.append("dimension:requirement-source-assertions")
        if not isinstance(atomic, list) or not atomic:
            unsatisfied.append("dimension:requirement-atomic-statements")
        if not isinstance(evidence, list) or not [value for value in evidence if str(value or "").strip()]:
            unsatisfied.append("dimension:requirement-evidence")
        if not isinstance(normal_paths, list) or not normal_paths:
            unsatisfied.append("dimension:requirement-normal-path")

        statement_refs = {RequirementSufficiencyWorker._statement_ref(value) for value in (atomic or [])}
        statement_refs.discard("")
        traced_refs = {
            str(value.get("statement_ref") or "").strip()
            for value in (traces or [])
            if isinstance(value, dict)
        }
        if not statement_refs or not statement_refs.issubset(traced_refs):
            unsatisfied.append("dimension:requirement-traceability")

        open_questions = []
        for field in ("ambiguities", "open_questions", "unresolved_questions"):
            value = candidate.get(field)
            if isinstance(value, list):
                open_questions.extend(item for item in value if str(item or "").strip())
        if open_questions:
            unsatisfied.append("dimension:requirement-open-question")

        unsatisfied = list(dict.fromkeys(unsatisfied))
        satisfied = ["dimension:%s" % value for value in dimensions if "dimension:%s" % value not in unsatisfied]
        return {
            "dimension_refs": ["dimension:%s" % value for value in dimensions],
            "satisfied_requirement_refs": satisfied,
            "unsatisfied_requirement_refs": unsatisfied,
        }

    @staticmethod
    def _statement_ref(value: Any) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            for key in ("statement_ref", "id", "ref"):
                found = str(value.get(key) or "").strip()
                if found:
                    return found
        return ""

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
            kind="REQUIREMENT_SUFFICIENCY",
            producer_kind=RuntimeProducerKind.WORKER,
            producer_ref=self.producer_ref,
            file_name="requirement-sufficiency.json",
            sha256=hashlib.sha256(raw).hexdigest(),
            size_bytes=len(raw),
            attempt_id=attempt_id,
            refs=list(refs) + ["stage:%s" % stage_instance_id],
            metadata={"stage": "REQUIREMENT_SUFFICIENCY", "policy_version": POLICY_VERSION},
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
                event_id="evt-req-suff-%s" % uuid.uuid4().hex,
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
            raise RequirementSufficiencyWorkerError("R1_NEXT_SEQUENCE_INVALID")
        return sequence

    @staticmethod
    def _gap_id(test_run_id: str, stage_instance_id: str, analysis_ref: str) -> str:
        digest = hashlib.sha256(
            (test_run_id + "\x1f" + stage_instance_id + "\x1f" + analysis_ref).encode("utf-8")
        ).hexdigest()[:32]
        return "gap-requirement-%s" % digest

    @staticmethod
    def _one_ref(scope_refs: Sequence[str], prefix: str) -> str:
        values = [value[len(prefix):] for value in scope_refs if value.startswith(prefix) and value[len(prefix):]]
        if len(values) != 1:
            raise RequirementSufficiencyWorkerError(
                "%sREF_REQUIRED_EXACTLY_ONCE" % prefix.upper().replace("-", "_").replace(":", "_")
            )
        return values[0]

    @staticmethod
    def _required(value: Any, error: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise RequirementSufficiencyWorkerError(error)
        return normalized
