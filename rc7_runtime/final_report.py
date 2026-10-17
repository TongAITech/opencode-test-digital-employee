"""RC7 final mission report derived exclusively from R1 truth.

Report generation is deliberately downstream of Mission convergence. A report
cannot make a Mission complete and cannot repair, hide or reinterpret runtime
truth. In particular, a trustworthy product TEST_RESULT=FAIL remains FAIL in
the report even when the corresponding Defect has later been fixed and closed.
"""

from __future__ import annotations

import hashlib
import json
import time
from html import escape
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from rc6_runtime.truth import TruthRuntime

from .mission_convergence_conformance import MissionConvergenceConformanceChecker


class FinalReportError(RuntimeError):
    pass


_OPEN_GAP_STATES = {
    "OPEN",
    "PLANNED",
    "REPAIRING",
    "EVIDENCE_PENDING",
    "HUMAN_REQUIRED",
    "BLOCKED",
}

_ACTIVE_TASK_STATES = {
    "REGISTERED",
    "READY",
    "LEASED",
    "RUNNING",
    "OUTPUT_PRODUCED",
    "EVALUATING",
    "REPAIR_REQUIRED",
    "BLOCKED",
    "HUMAN_REQUIRED",
    "FAILED",
    "STALE",
}


def _count_by(rows: Iterable[Mapping[str, Any]], field: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in rows:
        key = str(row.get(field, "UNKNOWN"))
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _ids(rows: Sequence[Mapping[str, Any]], field: str) -> List[str]:
    return sorted(str(row[field]) for row in rows)


def _digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class RC7FinalReportBuilder:
    def __init__(self, truth: TruthRuntime) -> None:
        self.truth = truth

    def build(self, mission_id: str, output_dir: str) -> Dict[str, Any]:
        snapshot = self.snapshot(mission_id)
        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        manifest_path = root / "manifest.json"
        html_path = root / "index.html"
        manifest_path.write_text(
            json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        html_path.write_text(self._html(snapshot), encoding="utf-8")
        return snapshot

    def snapshot(self, mission_id: str) -> Dict[str, Any]:
        missions = self.truth.query("rc7_mission", mission_id=mission_id)
        if len(missions) != 1:
            raise FinalReportError("FINAL_REPORT_REQUIRES_EXACTLY_ONE_MISSION")
        mission = missions[0]
        if mission.get("state") != "CONVERGED":
            raise FinalReportError("FINAL_REPORT_REQUIRES_CONVERGED_MISSION")

        # CONVERGED is necessary but not sufficient for a contracted RC7 Bank
        # Mission. Re-read canonical R1 truth before emitting any report so a
        # forged/direct Mission state transition cannot bypass Recovery,
        # Actual Result/Oracle or Defect Review authorities. Legacy Missions
        # without the additive recovery contract remain NOT_ENFORCED here.
        try:
            convergence_guard = MissionConvergenceConformanceChecker(self.truth).require_pass(mission_id)
        except Exception as exc:
            raise FinalReportError(
                "FINAL_REPORT_CONVERGENCE_CONFORMANCE_FAILED:%s" % str(exc)
            ) from exc
        if convergence_guard.enforced and convergence_guard.status != "PASS":
            raise FinalReportError("FINAL_REPORT_CONVERGENCE_CONFORMANCE_FAILED")

        evaluation_id = mission.get("latest_evaluation_id")
        evaluations = self.truth.query("rc7_evaluation", mission_id=mission_id)
        final_evaluations = [
            row for row in evaluations if row.get("evaluation_id") == evaluation_id
        ]
        if len(final_evaluations) != 1:
            raise FinalReportError("FINAL_REPORT_MISSION_EVALUATION_MISSING")
        final_evaluation = final_evaluations[0]
        if final_evaluation.get("node") != "MISSION_EVALUATION" or final_evaluation.get("result") != "PASS":
            raise FinalReportError("FINAL_REPORT_MISSION_EVALUATION_INVALID")
        if final_evaluation.get("dimensions", {}).get("sufficiency_state") != mission.get("sufficiency_state"):
            raise FinalReportError("FINAL_REPORT_SUFFICIENCY_STATE_MISMATCH")

        tasks = self.truth.query("rc7_task", mission_id=mission_id)
        gaps = self.truth.query("rc7_gap", mission_id=mission_id)
        defects = self.truth.query("rc7_defect", mission_id=mission_id)
        artifacts = self.truth.query("rc7_artifact", mission_id=mission_id)
        evidence = self.truth.query("rc7_evidence", mission_id=mission_id)

        active_tasks = [row for row in tasks if row.get("state") in _ACTIVE_TASK_STATES]
        open_gaps = [row for row in gaps if row.get("state") in _OPEN_GAP_STATES]
        if active_tasks:
            raise FinalReportError("FINAL_REPORT_ACTIVE_TASKS_REMAIN")
        if open_gaps:
            raise FinalReportError("FINAL_REPORT_OPEN_GAPS_REMAIN")

        execution_evaluations = [row for row in evaluations if row.get("node") == "EXECUTION"]
        execution_results = []
        for row in execution_evaluations:
            dimensions = row.get("dimensions", {})
            execution_results.append(
                {
                    "evaluation_id": row["evaluation_id"],
                    "test_result": dimensions.get("test_result"),
                    "execution_status": dimensions.get("execution_status"),
                    "failure_class": dimensions.get("failure_class"),
                    "conclusive": dimensions.get("conclusive"),
                    "evidence_refs": list(row.get("evidence_refs", [])),
                }
            )

        identity_index = {
            "tasks": _ids(tasks, "task_id"),
            "gaps": _ids(gaps, "gap_id"),
            "defects": _ids(defects, "defect_id"),
            "artifacts": _ids(artifacts, "artifact_id"),
            "evidence": _ids(evidence, "evidence_id"),
            "evaluations": _ids(evaluations, "evaluation_id"),
        }
        truth_basis = {
            "mission_id": mission_id,
            "mission_version": mission.get("artifact_version"),
            "mission_evaluation_id": evaluation_id,
            "identity_index": identity_index,
            "task_status": _count_by(tasks, "state"),
            "gap_status": _count_by(gaps, "state"),
            "defect_status": _count_by(defects, "state"),
            "execution_results": execution_results,
            "residual_risk_ids": sorted(str(x) for x in mission.get("residual_risk_ids", [])),
        }
        manifest = {
            "schema_version": "RC7_FINAL_REPORT_V1",
            "source": "R1_EVENT_STREAM_PROJECTION",
            "generated_at": int(time.time()),
            "mission_id": mission_id,
            "release_id": mission["release_id"],
            "mission_state": mission["state"],
            "sufficiency_state": mission["sufficiency_state"],
            "mission_evaluation_id": evaluation_id,
            "counts": {
                "tasks": len(tasks),
                "gaps": len(gaps),
                "defects": len(defects),
                "artifacts": len(artifacts),
                "evidence": len(evidence),
                "evaluations": len(evaluations),
            },
            "task_status": truth_basis["task_status"],
            "gap_status": truth_basis["gap_status"],
            "defect_status": truth_basis["defect_status"],
            "execution_results": execution_results,
            "residual_risk_ids": truth_basis["residual_risk_ids"],
            "identity_index": identity_index,
            "truth_digest": _digest(truth_basis),
        }
        return manifest

    def reconcile(self, manifest: Mapping[str, Any]) -> Dict[str, Any]:
        mission_id = str(manifest.get("mission_id", ""))
        current = self.snapshot(mission_id)
        mismatches: List[str] = []
        for field in (
            "release_id",
            "mission_state",
            "sufficiency_state",
            "mission_evaluation_id",
            "counts",
            "task_status",
            "gap_status",
            "defect_status",
            "execution_results",
            "residual_risk_ids",
            "identity_index",
            "truth_digest",
        ):
            if manifest.get(field) != current.get(field):
                mismatches.append(field)
        return {
            "mission_id": mission_id,
            "status": "PASS" if not mismatches else "FAIL",
            "mismatches": mismatches,
            "source": "R1_EVENT_STREAM_PROJECTION",
        }

    @staticmethod
    def _html(manifest: Mapping[str, Any]) -> str:
        execution_rows = "".join(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
            % (
                escape(str(item.get("evaluation_id", ""))),
                escape(str(item.get("test_result", ""))),
                escape(str(item.get("failure_class", ""))),
                escape(str(item.get("conclusive", ""))),
            )
            for item in manifest.get("execution_results", [])
        )
        return """<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">
<title>RC7 最终测试报告</title><style>body{font-family:Arial,'Microsoft YaHei',sans-serif;max-width:1100px;margin:32px auto}table{border-collapse:collapse;width:100%%}td,th{border:1px solid #ddd;padding:8px;text-align:left}pre{white-space:pre-wrap}</style></head><body>
<h1>RC7 最终测试报告</h1><p>Mission：%s</p><p>版本：%s</p><p>Mission 状态：%s</p><p>测试充分度：%s</p><p>数据源：R1 Event Stream 派生投影</p>
<h2>执行结论</h2><table><tr><th>Evaluation</th><th>测试结果</th><th>失败分类</th><th>结论可信</th></tr>%s</table>
<h2>缺陷状态</h2><pre>%s</pre><h2>Gap 状态</h2><pre>%s</pre><h2>残余风险</h2><pre>%s</pre><p>Truth digest：%s</p></body></html>""" % (
            escape(str(manifest.get("mission_id", ""))),
            escape(str(manifest.get("release_id", ""))),
            escape(str(manifest.get("mission_state", ""))),
            escape(str(manifest.get("sufficiency_state", ""))),
            execution_rows,
            escape(json.dumps(manifest.get("defect_status", {}), ensure_ascii=False, indent=2)),
            escape(json.dumps(manifest.get("gap_status", {}), ensure_ascii=False, indent=2)),
            escape(json.dumps(manifest.get("residual_risk_ids", []), ensure_ascii=False, indent=2)),
            escape(str(manifest.get("truth_digest", ""))),
        )
