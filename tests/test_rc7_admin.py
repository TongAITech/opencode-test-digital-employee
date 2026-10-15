from __future__ import annotations

import hashlib
import json
import threading
import urllib.request
from pathlib import Path

from rc6_runtime.truth import TruthRuntime
from rc7_admin.derived import AdminDerivedViews
from rc7_admin.projection import AdminProjection
from rc7_admin.server import AdminApplication, create_server
from rc7_runtime.models import Artifact, ArtifactStatus, Gap, GapSeverity, Mission, MissionStatus, Task, TaskStatus
from rc7_runtime.truth_overlay import append_entity, install_rc7_truth_overlay

install_rc7_truth_overlay()
RELEASE = "BLOAN-PF1.2.0"; MISSION = "M-BLOAN-PF1.2.0-STBB19-322"


def _truth(tmp_path: Path) -> TruthRuntime:
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    append_entity(truth, Mission(mission_id=MISSION, release_id=RELEASE, goal="验证 STBB19-322 达到测试充分性", state=MissionStatus.RUNNING), release_id=RELEASE)
    append_entity(truth, Task(task_id="TASK-REQ-1", mission_id=MISSION, node="REQUIREMENT_ANALYSIS", task_type="ANALYZE", objective="分析 STBB19-322 / STB913-14130", state=TaskStatus.READY, required_capabilities=["requirement_reasoning"]), release_id=RELEASE)
    append_entity(truth, Gap(gap_id="GAP-BOUNDARY-1", mission_id=MISSION, source_node="TEST_DESIGN", category="MISSING_BOUNDARY", severity=GapSeverity.CRITICAL, target_node="TEST_DESIGN", description="STB913-14130 缺少边界用例", subject_refs=["STBB19-322", "STB913-14130"], acceptance_criteria=["补齐边界用例"]), release_id=RELEASE)
    return truth


def _case(version: int, objective: str, tc_id: str = "TC-STBB19-322-001"):
    return {"tc_id": tc_id, "case_version": version, "release_id": RELEASE, "requirement_id": "STBB19-322", "sst_id": "STB913-14130", "condition_id": "COND-1", "objective": objective, "layer": "L3", "preconditions": ["已登录"], "test_data": {"amount": 100}, "steps": ["提交请求"], "expected": "返回业务成功", "oracle": {"type": "API", "assert": "code == 0"}, "evidence_requirements": ["request", "response"], "status": "TEST_READY"}


def test_admin_projection_reads_live_r1_with_filters_and_pagination(tmp_path):
    truth = _truth(tmp_path); projection = AdminProjection(truth)
    assert projection.list_resource("missions", page=1, page_size=10, filters={"version": RELEASE})["total"] == 1
    assert projection.list_resource("tasks", page=1, page_size=1, filters={"q": "STB913-14130"})["total"] == 1
    gaps = projection.list_resource("gaps", page=1, page_size=20, filters={"status": "OPEN", "risk": "CRITICAL"})
    assert gaps["total"] == 1 and gaps["items"][0]["gap_id"] == "GAP-BOUNDARY-1"
    append_entity(truth, Task(task_id="TASK-CODE-1", mission_id=MISSION, node="CODE_ANALYSIS", task_type="ANALYZE", objective="代码分析", state=TaskStatus.READY, required_capabilities=["code_reasoning", "code_reality"]), release_id=RELEASE)
    assert projection.list_resource("tasks", page=1, page_size=20)["total"] == 2


def test_test_case_maintenance_create_revision_and_quarantine_are_append_only(tmp_path):
    truth = _truth(tmp_path); projection = AdminProjection(truth)
    created = projection.create_test_case(_case(1, "初始目标")); assert created["status"] == "CREATED"
    revised = projection.append_test_case_revision("TC-STBB19-322-001", _case(2, "更新后的目标")); assert revised["case"]["case_version"] == 2
    quarantined = projection.quarantine_test_case("TC-STBB19-322-001", "需求已撤回")
    assert quarantined["case"]["case_version"] == 3 and quarantined["case"]["status"] == "QUARANTINED"
    history = truth.projection.history("test_case", "TC-STBB19-322-001")
    assert [row["case_version"] for row in history] == [1, 2, 3]
    assert history[0]["objective"] == "初始目标" and history[-1]["quarantine_reason"] == "需求已撤回"


def test_test_obligation_view_reads_verified_candidate_artifact(tmp_path):
    truth = _truth(tmp_path); path = tmp_path / "design.json"
    envelope = {"task_id": "TASK-DESIGN-1", "artifact": {"artifact_id": "ART-DESIGN-1", "artifact_type": "test_design_candidate"}, "semantic_payload": {"obligations": [{"obligation_id": "OBL-BOUNDARY-1", "kind": "BOUNDARY", "layer": "L3", "risk": "CRITICAL", "required": True, "evidence_refs": ["source://r1"]}], "cases": [{"tc_id": "TC-BOUNDARY-1", "coverage_links": [{"subject_id": "OBL-BOUNDARY-1", "evidence_ref": "source://r1"}]}]}}
    raw = json.dumps(envelope, ensure_ascii=False, sort_keys=True).encode("utf-8"); path.write_bytes(raw)
    append_entity(truth, Task(task_id="TASK-DESIGN-1", mission_id=MISSION, node="TEST_DESIGN", task_type="ANALYZE", objective="测试设计", state=TaskStatus.OUTPUT_PRODUCED, required_capabilities=["test_design"], output_artifact_refs=["ART-DESIGN-1"]), release_id=RELEASE)
    append_entity(truth, Artifact(artifact_id="ART-DESIGN-1", mission_id=MISSION, artifact_type="test_design_candidate", producer_task_id="TASK-DESIGN-1", content_ref="file://" + str(path), content_hash="sha256:" + hashlib.sha256(raw).hexdigest(), state=ArtifactStatus.VALID), release_id=RELEASE)
    result = AdminDerivedViews(truth).test_obligations(filters={"risk": "CRITICAL"})
    assert result["total"] == 1; assert result["items"][0]["obligation_id"] == "OBL-BOUNDARY-1"; assert result["items"][0]["covered_by"] == ["TC-BOUNDARY-1"]


def test_admin_http_serves_chinese_phase2_ui_and_r1_api(tmp_path):
    truth = _truth(tmp_path); app = AdminApplication(str(truth.store.path)); server = create_server(app, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        base = "http://127.0.0.1:%d" % server.server_address[1]
        with urllib.request.urlopen(base + "/api/missions?version=" + RELEASE, timeout=5) as response: payload = json.loads(response.read().decode("utf-8"))
        assert payload["total"] == 1
        with urllib.request.urlopen(base + "/api/missions/" + MISSION + "/detail", timeout=5) as response: detail_payload = json.loads(response.read().decode("utf-8"))
        assert detail_payload["summary"]["critical_open_gaps"] == 1
        with urllib.request.urlopen(base + "/", timeout=5) as response: html = response.read().decode("utf-8")
        for text in ("RC7 测试数字员工", "测试义务", "脚本就绪", "源码 Revision", "新增测试用例", "缺陷中心"):
            assert text in html
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
    assert not list(tmp_path.glob("**/aitest.db"))
