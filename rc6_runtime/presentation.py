"""RC6 Wave 12 R1-only Admin, Allure and mission reporting.

Presentation is derived from TruthRuntime projection/query only. It owns no
business database and cannot mutate testing truth. Allure is a derivative view
of R1 execution/assertion/evidence facts, never a second source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
import json
import os
import subprocess
import time
import uuid

from .truth import BUCKETS, IDENTITY_FIELDS, TruthRuntime


class PresentationError(RuntimeError):
    pass


ADMIN_ENTITIES = (
    "requirement_analysis",
    "code_analysis",
    "test_intent",
    "test_condition",
    "test_case",
    "execution_attempt",
    "assertion",
    "evidence",
    "defect",
    "coverage_observation",
    "report",
)

CHINESE_LABELS = {
    "requirement_analysis": "需求分析",
    "code_analysis": "代码分析",
    "test_intent": "测试意图",
    "test_condition": "测试条件",
    "test_case": "测试用例",
    "execution_attempt": "测试执行",
    "assertion": "断言",
    "evidence": "证据",
    "defect": "缺陷",
    "coverage_observation": "执行覆盖",
    "report": "测试报告",
}


@dataclass(frozen=True)
class PageResult:
    entity_type: str
    page: int
    page_size: int
    total: int
    items: Tuple[Dict[str, Any], ...]


class AdminReadModel:
    """Read-only Admin/API model backed directly by R1 projection."""

    def __init__(self, truth: TruthRuntime):
        self.truth = truth

    def list(
        self,
        entity_type: str,
        *,
        release_id: Optional[str] = None,
        requirement_id: Optional[str] = None,
        sst_id: Optional[str] = None,
        layer: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> PageResult:
        if entity_type not in ADMIN_ENTITIES:
            raise PresentationError("UNSUPPORTED_ADMIN_ENTITY")
        if page < 1 or page_size < 1 or page_size > 200:
            raise PresentationError("INVALID_PAGINATION")
        filters = {
            "release_id": release_id,
            "requirement_id": requirement_id,
            "sst_id": sst_id,
            "layer": layer,
            "status": status,
        }
        rows = self.truth.query(entity_type, **filters)
        start = (page - 1) * page_size
        end = start + page_size
        return PageResult(entity_type, page, page_size, len(rows), tuple(rows[start:end]))

    def summary(self, release_id: str) -> Dict[str, Any]:
        if not release_id:
            raise PresentationError("RELEASE_ID_REQUIRED")
        counts = {entity: len(self.truth.query(entity, release_id=release_id)) for entity in ADMIN_ENTITIES}
        executions = self.truth.query_execution_attempts(release_id=release_id)
        defects = self.truth.query_defects(release_id=release_id)
        return {
            "release_id": release_id,
            "counts": counts,
            "execution_status": self._count_by(executions, "status"),
            "defect_severity": self._count_by(defects, "severity"),
            "navigation": [{"entity": x, "label": CHINESE_LABELS[x]} for x in ADMIN_ENTITIES],
        }

    @staticmethod
    def _count_by(rows: Iterable[Dict[str, Any]], field: str) -> Dict[str, int]:
        result: Dict[str, int] = {}
        for row in rows:
            key = str(row.get(field, "UNKNOWN"))
            result[key] = result.get(key, 0) + 1
        return dict(sorted(result.items()))

    def ids(self, entity_type: str, release_id: str) -> Tuple[str, ...]:
        identity = IDENTITY_FIELDS[entity_type]
        return tuple(sorted(str(x[identity]) for x in self.truth.query(entity_type, release_id=release_id)))


class AdminHtmlRenderer:
    """Minimal Chinese, query-oriented Admin shell; no dashboard-only UX."""

    @staticmethod
    def index_html() -> str:
        menu = "".join(
            f'<button class="menu" data-entity="{escape(entity)}">{escape(CHINESE_LABELS[entity])}</button>'
            for entity in ADMIN_ENTITIES
        )
        return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI测试数字员工 RC6</title>
<style>
body{{margin:0;font-family:Arial,'Microsoft YaHei',sans-serif;display:flex;height:100vh}}aside{{width:180px;border-right:1px solid #ddd;padding:12px;overflow:auto}}main{{flex:1;padding:18px;overflow:auto}}.menu{{display:block;width:100%;margin:4px 0;padding:8px;text-align:left;background:white;border:1px solid #ddd;border-radius:4px}}.query{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}}input,select,button{{padding:7px}}table{{border-collapse:collapse;width:100%;font-size:13px}}th,td{{border-bottom:1px solid #ddd;padding:7px;text-align:left;vertical-align:top}}pre{{white-space:pre-wrap;word-break:break-word;margin:0}}.pager{{margin-top:12px}}
</style></head><body><aside><strong>测试资产</strong>{menu}</aside><main>
<div class="query"><input id="release" placeholder="版本，例如 BLOAN-PF1.2.0"><input id="req" placeholder="需求编号"><input id="sst" placeholder="SST编号"><select id="layer"><option value="">全部层级</option>{''.join(f'<option>L{i}</option>' for i in range(1,8))}</select><button id="search">查询</button></div>
<div id="title"></div><div id="table"></div><div class="pager"><button id="prev">上一页</button> <span id="pageInfo"></span> <button id="next">下一页</button></div>
<script>
let entity='test_case',page=1,pageSize=20,total=0;
function q(v){{return encodeURIComponent(v||'')}}
async function load(){{const u=`/api/${{entity}}?release_id=${{q(release.value)}}&requirement_id=${{q(req.value)}}&sst_id=${{q(sst.value)}}&layer=${{q(layer.value)}}&page=${{page}}&page_size=${{pageSize}}`;const r=await fetch(u);const d=await r.json();total=d.total;title.textContent=d.label+'（'+total+'）';table.innerHTML='<table><tbody>'+d.items.map(x=>'<tr><td><pre>'+JSON.stringify(x,null,2).replaceAll('&','&amp;').replaceAll('<','&lt;')+'</pre></td></tr>').join('')+'</tbody></table>';pageInfo.textContent=`第 ${{page}} 页 / 共 ${{Math.max(1,Math.ceil(total/pageSize))}} 页`;}}
document.querySelectorAll('.menu').forEach(b=>b.onclick=()=>{{entity=b.dataset.entity;page=1;load()}});search.onclick=()=>{{page=1;load()}};prev.onclick=()=>{{if(page>1){{page--;load()}}}};next.onclick=()=>{{if(page*pageSize<total){{page++;load()}}}};load();
</script></main></body></html>"""


class AllureResultsAdapter:
    """Generate Allure 2 result JSON from R1 execution/assertion/evidence truth."""

    STATUS_MAP = {"PASS": "passed", "FAIL": "failed", "BLOCKED": "broken", "SKIPPED": "skipped", "NOT_RUN": "skipped"}

    def __init__(self, truth: TruthRuntime):
        self.truth = truth

    def generate(self, release_id: str, results_dir: str | os.PathLike[str]) -> Dict[str, Any]:
        root = Path(results_dir)
        root.mkdir(parents=True, exist_ok=True)
        for existing in root.glob("*-result.json"):
            existing.unlink()
        executions = self.truth.query_execution_attempts(release_id=release_id)
        assertions = self.truth.query_assertions(release_id=release_id)
        assertion_by_attempt = {x["attempt_id"]: x for x in assertions}
        generated_ids: List[str] = []
        for execution in executions:
            attempt_id = execution["attempt_id"]
            assertion = assertion_by_attempt.get(attempt_id)
            status = self.STATUS_MAP[execution["status"]]
            message = None
            if execution["status"] == "FAIL" and assertion is not None:
                message = "Oracle assertion failed" if not assertion["passed"] else "Execution failed"
            test_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"rc6:{release_id}:{attempt_id}"))
            payload = {
                "uuid": test_uuid,
                "historyId": f"{execution['tc_id']}@{execution['case_version']}",
                "name": f"{execution['tc_id']} v{execution['case_version']} [{execution['layer']}]",
                "fullName": attempt_id,
                "status": status,
                "statusDetails": {"message": message} if message else {},
                "stage": "finished",
                "labels": [
                    {"name": "suite", "value": release_id},
                    {"name": "feature", "value": execution.get("requirement_id", "")},
                    {"name": "layer", "value": execution["layer"]},
                    {"name": "target", "value": execution["target_id"]},
                ],
                "parameters": [
                    {"name": "attempt_id", "value": attempt_id},
                    {"name": "case_version", "value": str(execution["case_version"])},
                ],
                "links": [
                    {"name": ref, "url": ref, "type": "evidence"}
                    for ref in execution.get("evidence_refs", []) if isinstance(ref, str) and ref
                ],
                "start": 0,
                "stop": 0,
            }
            if assertion:
                payload["links"].extend(
                    {"name": ref, "url": ref, "type": "assertion-evidence"}
                    for ref in assertion.get("evidence_refs", []) if isinstance(ref, str) and ref
                )
            (root / f"{test_uuid}-result.json").write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8"
            )
            generated_ids.append(attempt_id)
        manifest = {
            "release_id": release_id,
            "execution_attempt_ids": sorted(generated_ids),
            "result_count": len(generated_ids),
            "generated_from": "R1_EVENT_STREAM_PROJECTION",
        }
        (root / "rc6-allure-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        return manifest


class AllureRenderer:
    """Render automatically using a configured local Allure CLI."""

    def __init__(self, allure_cli: str, runner: Optional[Callable[[List[str]], Any]] = None):
        if not allure_cli:
            raise PresentationError("ALLURE_CLI_REQUIRED")
        self.allure_cli = allure_cli
        self.runner = runner or self._run

    @staticmethod
    def _run(args: List[str]) -> Any:
        return subprocess.run(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def render(self, results_dir: str | os.PathLike[str], report_dir: str | os.PathLike[str]) -> Dict[str, Any]:
        results = Path(results_dir)
        if not (results / "rc6-allure-manifest.json").exists():
            raise PresentationError("ALLURE_RESULTS_MANIFEST_MISSING")
        report = Path(report_dir)
        report.parent.mkdir(parents=True, exist_ok=True)
        args = [self.allure_cli, "generate", str(results), "-o", str(report), "--clean"]
        self.runner(args)
        return {"command": args, "report_index": str(report / "index.html")}


class MissionReportBuilder:
    """Generate Chinese mission report + machine-readable reconciliation manifest."""

    def __init__(self, admin: AdminReadModel):
        self.admin = admin

    def build(self, release_id: str, mission_id: str, output_dir: str | os.PathLike[str], allure_relative_url: str) -> Dict[str, Any]:
        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        summary = self.admin.summary(release_id)
        identities = {entity: list(self.admin.ids(entity, release_id)) for entity in ADMIN_ENTITIES}
        manifest = {
            "release_id": release_id,
            "mission_id": mission_id,
            "generated_at": int(time.time()),
            "counts": summary["counts"],
            "identities": identities,
            "execution_status": summary["execution_status"],
            "defect_severity": summary["defect_severity"],
            "allure_url": allure_relative_url,
            "source": "R1_EVENT_STREAM_PROJECTION",
        }
        (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        rows = "".join(f"<tr><td>{escape(CHINESE_LABELS[e])}</td><td>{summary['counts'][e]}</td></tr>" for e in ADMIN_ENTITIES)
        html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>{escape(release_id)} 测试报告</title><style>body{{font-family:Arial,'Microsoft YaHei',sans-serif;max-width:1100px;margin:30px auto}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ddd;padding:8px}}</style></head><body><h1>{escape(release_id)} 测试报告</h1><p>Mission：{escape(mission_id)}</p><p>报告数据源：R1 Event Stream 派生投影</p><p><a href="{escape(allure_relative_url)}">查看 Allure 执行明细</a></p><h2>资产统计</h2><table><tr><th>资产</th><th>数量</th></tr>{rows}</table><h2>执行状态</h2><pre>{escape(json.dumps(summary['execution_status'], ensure_ascii=False, indent=2))}</pre><h2>缺陷严重度</h2><pre>{escape(json.dumps(summary['defect_severity'], ensure_ascii=False, indent=2))}</pre></body></html>"""
        (root / "index.html").write_text(html, encoding="utf-8")
        return manifest


class TruthReconciler:
    """Prove that R1 projection, Admin query, report manifest and Allure agree."""

    def __init__(self, truth: TruthRuntime, admin: AdminReadModel):
        self.truth = truth
        self.admin = admin

    def reconcile(self, release_id: str, report_manifest: Dict[str, Any], allure_manifest: Dict[str, Any]) -> Dict[str, Any]:
        mismatches: List[str] = []
        truth_ids: Dict[str, List[str]] = {}
        for entity in ADMIN_ENTITIES:
            identity = IDENTITY_FIELDS[entity]
            ids = sorted(str(x[identity]) for x in self.truth.query(entity, release_id=release_id))
            truth_ids[entity] = ids
            admin_ids = list(self.admin.ids(entity, release_id))
            if ids != admin_ids:
                mismatches.append(f"ADMIN_ID_MISMATCH:{entity}")
            report_ids = sorted(str(x) for x in report_manifest.get("identities", {}).get(entity, []))
            if ids != report_ids:
                mismatches.append(f"REPORT_ID_MISMATCH:{entity}")
            report_count = report_manifest.get("counts", {}).get(entity)
            if report_count != len(ids):
                mismatches.append(f"REPORT_COUNT_MISMATCH:{entity}")

        execution_ids = truth_ids["execution_attempt"]
        allure_ids = sorted(str(x) for x in allure_manifest.get("execution_attempt_ids", []))
        if execution_ids != allure_ids:
            mismatches.append("ALLURE_EXECUTION_ID_MISMATCH")
        if allure_manifest.get("result_count") != len(execution_ids):
            mismatches.append("ALLURE_EXECUTION_COUNT_MISMATCH")
        if report_manifest.get("source") != "R1_EVENT_STREAM_PROJECTION":
            mismatches.append("REPORT_NOT_R1_DERIVED")
        if allure_manifest.get("generated_from") != "R1_EVENT_STREAM_PROJECTION":
            mismatches.append("ALLURE_NOT_R1_DERIVED")
        return {
            "passed": not mismatches,
            "release_id": release_id,
            "mismatches": mismatches,
            "truth_counts": {k: len(v) for k, v in truth_ids.items()},
        }
