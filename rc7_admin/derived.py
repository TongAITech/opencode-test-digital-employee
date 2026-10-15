"""Derived administration views over immutable R1 truth and verified artifacts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.candidate_payload import CandidatePayloadReader, CandidatePayloadError

from .projection import AdminProjection, AdminProjectionError


class AdminDerivedViews:
    def __init__(self, truth: TruthRuntime) -> None:
        self.truth = truth
        self.base = AdminProjection(truth)
        self.reader = CandidatePayloadReader()

    def test_obligations(self, *, page: int = 1, page_size: int = 20,
                         filters: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
        self.base.refresh()
        rows: List[Dict[str, Any]] = []
        for task in self.truth.query("rc7_task"):
            if str(task.get("node") or "").upper() != "TEST_DESIGN":
                continue
            for artifact_id in task.get("output_artifact_refs", []) or []:
                try:
                    candidate = self.reader.load(
                        self.truth, str(artifact_id),
                        expected_mission_id=str(task.get("mission_id") or ""),
                        expected_task_id=str(task.get("task_id") or ""),
                    )
                except CandidatePayloadError:
                    continue
                obligations = candidate.semantic_payload.get("obligations")
                cases = candidate.semantic_payload.get("cases")
                if not isinstance(obligations, list):
                    continue
                case_rows = cases if isinstance(cases, list) else []
                for obligation in obligations:
                    if not isinstance(obligation, dict):
                        continue
                    oid = str(obligation.get("obligation_id") or "")
                    covered_by = []
                    for case in case_rows:
                        if not isinstance(case, dict):
                            continue
                        links = case.get("coverage_links")
                        if not isinstance(links, list):
                            continue
                        if any(isinstance(link, dict) and str(link.get("subject_id") or "") == oid for link in links):
                            tc_id = str(case.get("tc_id") or "")
                            if tc_id:
                                covered_by.append(tc_id)
                    row = dict(obligation)
                    row.update({
                        "mission_id": task.get("mission_id"),
                        "task_id": task.get("task_id"),
                        "artifact_id": artifact_id,
                        "content_hash": candidate.content_hash,
                        "covered_by": sorted(set(covered_by)),
                        "coverage_count": len(set(covered_by)),
                    })
                    rows.append(row)
        return self.base.paginate_rows("test-obligations", rows, page=page, page_size=page_size, filters=filters)

    def script_readiness(self, *, page: int = 1, page_size: int = 20,
                         filters: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
        self.base.refresh()
        evaluations = {str(row.get("evaluation_id")): row for row in self.truth.query("rc7_evaluation")}
        artifacts = {str(row.get("artifact_id")): row for row in self.truth.query("rc7_artifact")}
        rows: List[Dict[str, Any]] = []
        for task in self.truth.query("rc7_task"):
            if str(task.get("node") or "").upper() != "SCRIPT_READINESS":
                continue
            evaluation = evaluations.get(str(task.get("evaluation_id") or ""), {})
            refs = task.get("output_artifact_refs") or [None]
            for artifact_id in refs:
                artifact = artifacts.get(str(artifact_id or ""), {})
                rows.append({
                    "task_id": task.get("task_id"), "mission_id": task.get("mission_id"),
                    "state": task.get("state"), "objective": task.get("objective"),
                    "artifact_id": artifact_id, "artifact_type": artifact.get("artifact_type_name"),
                    "content_hash": artifact.get("content_hash"), "content_ref": artifact.get("content_ref"),
                    "evaluation_id": task.get("evaluation_id"), "result": evaluation.get("result"),
                    "evaluator_ref": evaluation.get("evaluator_ref"), "updated_at": task.get("updated_at"),
                })
        return self.base.paginate_rows("scripts", rows, page=page, page_size=page_size, filters=filters)

    def mission_detail(self, mission_id: str) -> Dict[str, Any]:
        overview = self.base.mission_overview(mission_id)
        related = overview["related"]
        gaps = related.get("gaps", [])
        tasks = related.get("tasks", [])
        defects = related.get("defects", [])
        artifacts = related.get("artifacts", [])
        evaluations = related.get("evaluations", [])
        snapshot = None
        snapshot_artifact = None
        for artifact in artifacts:
            payload = self._verified_json(artifact)
            if isinstance(payload, dict) and (
                "critical_requirement_refs" in payload or "verified_obligation_refs" in payload
            ):
                snapshot = payload
                snapshot_artifact = artifact
                break
        return {
            "mission": overview["mission"],
            "summary": {
                "task_total": len(tasks),
                "task_pass": sum(1 for row in tasks if row.get("state") == "PASS"),
                "open_gaps": sum(1 for row in gaps if row.get("state") not in {"RESOLVED", "WAIVED", "DUPLICATE", "SUPERSEDED"}),
                "critical_open_gaps": sum(1 for row in gaps if row.get("severity") in {"CRITICAL", "BLOCKER"} and row.get("state") not in {"RESOLVED", "WAIVED", "DUPLICATE", "SUPERSEDED"}),
                "defect_total": len(defects),
                "defect_closed": sum(1 for row in defects if row.get("state") == "CLOSED"),
                "evaluation_total": len(evaluations),
            },
            "sufficiency_snapshot": snapshot,
            "snapshot_artifact": snapshot_artifact,
            "related": related,
        }

    def defect_detail(self, defect_id: str) -> Dict[str, Any]:
        self.base.refresh()
        rows = self.truth.query("rc7_defect", defect_id=defect_id)
        if not rows:
            raise AdminProjectionError("DEFECT_NOT_FOUND")
        defect = rows[0]
        mission_id = str(defect.get("mission_id") or "")
        source_gap = str(defect.get("source_gap_id") or "")
        tokens = {defect_id}
        if source_gap:
            tokens.add(source_gap)
        related: Dict[str, List[Dict[str, Any]]] = {}
        for name, artifact_type in {
            "tasks": "rc7_task", "gaps": "rc7_gap", "evaluations": "rc7_evaluation",
            "evidence": "rc7_evidence", "artifacts": "rc7_artifact",
        }.items():
            matches = []
            for row in self.truth.query(artifact_type, mission_id=mission_id):
                text = json.dumps(row, ensure_ascii=False, sort_keys=True)
                if any(token in text for token in tokens):
                    matches.append(row)
            related[name] = matches
        return {"defect": defect, "lineage": related}

    @staticmethod
    def _verified_json(artifact: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        ref = str(artifact.get("content_ref") or "")
        expected = str(artifact.get("content_hash") or "")
        if not ref.startswith("file://") or not expected.startswith("sha256:"):
            return None
        path = Path(ref[len("file://"):])
        if not path.is_file():
            return None
        raw = path.read_bytes()
        if "sha256:" + hashlib.sha256(raw).hexdigest() != expected:
            return None
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None
