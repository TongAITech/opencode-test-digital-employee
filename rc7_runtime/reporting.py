from __future__ import annotations

import html
import json
import time
import uuid
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

from rc6_runtime.truth import TruthRuntime


def _safe_query(truth: TruthRuntime, artifact_type: str, **filters) -> List[Dict[str, Any]]:
    try:
        rows = truth.query(artifact_type, **filters)
    except Exception:
        return []
    return [dict(row) for row in rows if isinstance(row, dict)]


def _mission_rows(truth: TruthRuntime, artifact_type: str, mission_id: str) -> List[Dict[str, Any]]:
    rows = _safe_query(truth, artifact_type, mission_id=mission_id)
    if rows:
        return rows
    all_rows = _safe_query(truth, artifact_type)
    out = []
    for row in all_rows:
        if mission_id and mission_id in json.dumps(row, ensure_ascii=False, sort_keys=True):
            out.append(row)
    return out


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _count_by(rows: Iterable[Mapping[str, Any]], keys) -> Dict[str, int]:
    counter = Counter()
    for row in rows:
        value = None
        for key in keys:
            candidate = row.get(key)
            if candidate not in (None, ""):
                value = candidate
                break
        counter[str(value or "UNKNOWN").upper()] += 1
    return dict(sorted(counter.items()))


class MissionReportBuilder:
    """Build a deterministic report projection from R1 truth.

    The report is a renderer/projection only. It never becomes a second truth
    store and never upgrades Mission/Test/Defect state.
    """

    def __init__(self, truth: TruthRuntime) -> None:
        self.truth = truth

    @classmethod
    def from_r1_path(cls, r1_path: str) -> "MissionReportBuilder":
        return cls(TruthRuntime(Path(r1_path).expanduser().resolve()))

    def build(self, mission_id: str) -> Dict[str, Any]:
        self.truth.rebuild_projection()
        mission_rows = _safe_query(self.truth, "rc7_mission", mission_id=mission_id)
        if not mission_rows:
            raise ValueError("MISSION_NOT_FOUND:%s" % mission_id)
        mission = mission_rows[0]

        tasks = _mission_rows(self.truth, "rc7_task", mission_id)
        gaps = _mission_rows(self.truth, "rc7_gap", mission_id)
        evaluations = _mission_rows(self.truth, "rc7_evaluation", mission_id)
        evidence = _mission_rows(self.truth, "rc7_evidence", mission_id)
        defects = _mission_rows(self.truth, "rc7_defect", mission_id)
        requirements = _mission_rows(self.truth, "requirement_analysis", mission_id)
        code_impacts = _mission_rows(self.truth, "code_analysis", mission_id)
        test_cases = _mission_rows(self.truth, "test_case", mission_id)
        executions = _mission_rows(self.truth, "execution_attempt", mission_id)
        diagnoses = _mission_rows(self.truth, "failure_diagnosis", mission_id)

        terminal_gap_states = {"RESOLVED", "WAIVED", "DUPLICATE", "SUPERSEDED"}
        open_gaps = [row for row in gaps if str(row.get("state") or "").upper() not in terminal_gap_states]

        return {
            "schema_version": "pfc.aitest.rc7.mission-report.v1",
            "report_id": "RPT-" + uuid.uuid4().hex,
            "generated_at": int(time.time()),
            "truth_source": "R1_EVENT_STREAM",
            "mission_id": mission_id,
            "release_id": mission.get("release_id"),
            "mission": mission,
            "summary": {
                "mission_state": mission.get("state"),
                "mission_sufficiency_state": mission.get("sufficiency_state"),
                "task_total": len(tasks),
                "task_pass": sum(1 for row in tasks if str(row.get("state") or "").upper() == "PASS"),
                "requirement_artifact_total": len(requirements),
                "code_analysis_artifact_total": len(code_impacts),
                "test_case_total": len(test_cases),
                "execution_total": len(executions),
                "execution_results": _count_by(executions, ("result", "status", "test_result")),
                "diagnosis_total": len(diagnoses),
                "failure_classes": _count_by(diagnoses, ("failure_class", "class", "category")),
                "defect_total": len(defects),
                "defect_states": _count_by(defects, ("state", "status")),
                "evidence_total": len(evidence),
                "evaluation_total": len(evaluations),
                "open_gap_total": len(open_gaps),
                "critical_open_gap_total": sum(
                    1 for row in open_gaps
                    if str(row.get("severity") or "").upper() in {"CRITICAL", "BLOCKER"}
                ),
            },
            "coverage": {
                "test_layers": _count_by(test_cases, ("layer",)),
                "execution_layers": _count_by(executions, ("layer",)),
                "requirement_refs_covered": sorted({
                    str(ref)
                    for case in test_cases
                    for ref in _as_list(case.get("requirement_refs") or case.get("requirement_ref"))
                }) if test_cases else [],
            },
            "tasks": tasks,
            "requirements": requirements,
            "code_impacts": code_impacts,
            "test_cases": test_cases,
            "executions": executions,
            "diagnoses": diagnoses,
            "defects": defects,
            "evidence": evidence,
            "gaps": gaps,
            "evaluations": evaluations,
            "residual_risk": {
                "open_gaps": open_gaps,
                "blocked_executions": [
                    row for row in executions
                    if str(row.get("status") or row.get("result") or "").upper().startswith("BLOCKED")
                ],
                "unknown_diagnoses": [
                    row for row in diagnoses
                    if str(row.get("failure_class") or "").upper() == "UNKNOWN"
                ],
            },
        }


class ReportRenderer:
    def write_all(self, report: Mapping[str, Any], output_dir: str) -> Dict[str, str]:
        root = Path(output_dir).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        json_path = root / "rc7-mission-report.json"
        html_path = root / "rc7-mission-report.html"
        junit_path = root / "rc7-mission-report-junit.xml"
        allure_dir = root / "allure-results"
        json_path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        html_path.write_text(self.to_html(report), encoding="utf-8")
        ET.ElementTree(self.to_junit(report)).write(str(junit_path), encoding="utf-8", xml_declaration=True)
        self.write_allure_results(report, allure_dir)
        return {
            "json": str(json_path),
            "html": str(html_path),
            "junit": str(junit_path),
            "allure_results": str(allure_dir),
        }

    def to_html(self, report: Mapping[str, Any]) -> str:
        summary = dict(report.get("summary") or {})
        rows = "".join(
            "<tr><th>%s</th><td>%s</td></tr>" % (html.escape(str(key)), html.escape(str(value)))
            for key, value in summary.items()
        )
        defects = report.get("defects") or []
        gaps = report.get("residual_risk", {}).get("open_gaps", []) if isinstance(report.get("residual_risk"), dict) else []
        defect_rows = "".join(
            "<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                html.escape(str(item.get("defect_id") or "")),
                html.escape(str(item.get("severity") or "")),
                html.escape(str(item.get("state") or "")),
            ) for item in defects if isinstance(item, dict)
        ) or "<tr><td colspan='3'>None</td></tr>"
        gap_rows = "".join(
            "<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                html.escape(str(item.get("gap_id") or "")),
                html.escape(str(item.get("severity") or "")),
                html.escape(str(item.get("description") or "")),
            ) for item in gaps if isinstance(item, dict)
        ) or "<tr><td colspan='3'>None</td></tr>"
        return """<!doctype html>
<html><head><meta charset="utf-8"><title>RC7 Mission Report</title>
<style>body{font-family:Arial,sans-serif;margin:24px;line-height:1.45}table{border-collapse:collapse;width:100%%;margin:12px 0 24px}th,td{border:1px solid #ddd;padding:8px;text-align:left}th{background:#f4f4f4}h1,h2{margin-top:24px}.meta{color:#555}</style>
</head><body>
<h1>RC7 Mission Report</h1>
<div class="meta">Mission: %s &nbsp; Release: %s &nbsp; Truth: R1 Event Stream</div>
<h2>Summary</h2><table>%s</table>
<h2>Defects</h2><table><tr><th>ID</th><th>Severity</th><th>State</th></tr>%s</table>
<h2>Residual Risks / Open Gaps</h2><table><tr><th>ID</th><th>Severity</th><th>Description</th></tr>%s</table>
</body></html>""" % (
            html.escape(str(report.get("mission_id") or "")),
            html.escape(str(report.get("release_id") or "")),
            rows,
            defect_rows,
            gap_rows,
        )

    def to_junit(self, report: Mapping[str, Any]) -> ET.Element:
        executions = [row for row in report.get("executions", []) if isinstance(row, dict)]
        failures = 0
        skipped = 0
        suite = ET.Element("testsuite", {
            "name": "RC7-%s" % str(report.get("mission_id") or "mission"),
            "tests": str(len(executions)),
            "failures": "0",
            "errors": "0",
            "skipped": "0",
        })
        for row in executions:
            tc_id = str(row.get("tc_id") or row.get("attempt_id") or "execution")
            layer = str(row.get("layer") or "unknown")
            status = str(row.get("result") or row.get("status") or "UNKNOWN").upper()
            case = ET.SubElement(suite, "testcase", {"name": tc_id, "classname": "RC7.%s" % layer})
            if status in {"FAIL", "FAILED", "ERROR"}:
                failures += 1
                node = ET.SubElement(case, "failure", {"message": status})
                node.text = json.dumps(row, ensure_ascii=False, sort_keys=True)
            elif status.startswith("BLOCKED") or status in {"SKIP", "SKIPPED", "NOT_RUN"}:
                skipped += 1
                ET.SubElement(case, "skipped", {"message": status})
        suite.set("failures", str(failures))
        suite.set("skipped", str(skipped))
        return suite

    def write_allure_results(self, report: Mapping[str, Any], root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        now_ms = int(time.time() * 1000)
        executions = [row for row in report.get("executions", []) if isinstance(row, dict)]
        for index, row in enumerate(executions, 1):
            status_raw = str(row.get("result") or row.get("status") or "unknown").upper()
            if status_raw in {"PASS", "PASSED"}:
                status = "passed"
            elif status_raw in {"FAIL", "FAILED", "ERROR"}:
                status = "failed"
            elif status_raw.startswith("BLOCKED") or status_raw in {"SKIP", "SKIPPED", "NOT_RUN"}:
                status = "skipped"
            else:
                status = "unknown"
            uid = str(row.get("attempt_id") or uuid.uuid4())
            payload = {
                "uuid": uid,
                "historyId": str(row.get("tc_id") or uid),
                "name": str(row.get("tc_id") or uid),
                "fullName": "RC7.%s.%s" % (str(row.get("layer") or "unknown"), str(row.get("tc_id") or uid)),
                "status": status,
                "stage": "finished",
                "start": int(row.get("started_at") or now_ms),
                "stop": int(row.get("finished_at") or now_ms),
                "labels": [
                    {"name": "suite", "value": str(report.get("release_id") or "RC7")},
                    {"name": "parentSuite", "value": str(report.get("mission_id") or "mission")},
                    {"name": "layer", "value": str(row.get("layer") or "unknown")},
                ],
                "parameters": [],
                "links": [],
                "attachments": [],
            }
            (root / ("%04d-%s-result.json" % (index, uid))).write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
