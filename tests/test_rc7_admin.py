from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path

from rc6_runtime.truth import TruthRuntime
from rc7_admin.projection import AdminProjection
from rc7_admin.server import AdminApplication, create_server
from rc7_runtime.models import Gap, GapSeverity, Mission, MissionStatus, Task, TaskStatus
from rc7_runtime.truth_overlay import append_entity, install_rc7_truth_overlay

install_rc7_truth_overlay()

RELEASE = "BLOAN-PF1.2.0"
MISSION = "M-BLOAN-PF1.2.0-STBB19-322"


def _truth(tmp_path: Path) -> TruthRuntime:
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    append_entity(
        truth,
        Mission(
            mission_id=MISSION,
            release_id=RELEASE,
            goal="验证 STBB19-322 达到测试充分性",
            state=MissionStatus.RUNNING,
        ),
        release_id=RELEASE,
    )
    append_entity(
        truth,
        Task(
            task_id="TASK-REQ-1",
            mission_id=MISSION,
            node="REQUIREMENT_ANALYSIS",
            task_type="ANALYZE",
            objective="分析 STBB19-322 / STB913-14130",
            state=TaskStatus.READY,
            required_capabilities=["requirement_reasoning"],
        ),
        release_id=RELEASE,
    )
    append_entity(
        truth,
        Gap(
            gap_id="GAP-BOUNDARY-1",
            mission_id=MISSION,
            source_node="TEST_DESIGN",
            category="MISSING_BOUNDARY",
            severity=GapSeverity.CRITICAL,
            target_node="TEST_DESIGN",
            description="STB913-14130 缺少边界用例",
            subject_refs=["STBB19-322", "STB913-14130"],
            acceptance_criteria=["补齐边界用例"],
        ),
        release_id=RELEASE,
    )
    return truth


def _case(version: int, objective: str):
    return {
        "tc_id": "TC-STBB19-322-001",
        "case_version": version,
        "release_id": RELEASE,
        "requirement_id": "STBB19-322",
        "sst_id": "STB913-14130",
        "condition_id": "COND-1",
        "objective": objective,
        "layer": "L3",
        "preconditions": ["已登录"],
        "test_data": {"amount": 100},
        "steps": ["提交请求"],
        "expected": "返回业务成功",
        "oracle": {"type": "API", "assert": "code == 0"},
        "evidence_requirements": ["request", "response"],
        "status": "TEST_READY",
    }


def test_admin_projection_reads_live_r1_with_filters_and_pagination(tmp_path):
    truth = _truth(tmp_path)
    projection = AdminProjection(truth)

    missions = projection.list_resource("missions", page=1, page_size=10, filters={"version": RELEASE})
    assert missions["total"] == 1
    assert missions["items"][0]["mission_id"] == MISSION

    tasks = projection.list_resource("tasks", page=1, page_size=1, filters={"q": "STB913-14130"})
    assert tasks["total"] == 1
    assert tasks["page_size"] == 1

    gaps = projection.list_resource("gaps", page=1, page_size=20, filters={"status": "OPEN", "risk": "CRITICAL"})
    assert gaps["total"] == 1
    assert gaps["items"][0]["gap_id"] == "GAP-BOUNDARY-1"

    append_entity(
        truth,
        Task(
            task_id="TASK-CODE-1",
            mission_id=MISSION,
            node="CODE_ANALYSIS",
            task_type="ANALYZE",
            objective="代码分析",
            state=TaskStatus.READY,
            required_capabilities=["code_reasoning", "code_reality"],
        ),
        release_id=RELEASE,
    )
    # Same projection object must see newly appended R1 truth without server restart.
    assert projection.list_resource("tasks", page=1, page_size=20)["total"] == 2


def test_test_case_maintenance_appends_new_r1_revision(tmp_path):
    truth = _truth(tmp_path)
    truth.append_atomic("TEST_CASE_UPSERTED", _case(1, "初始目标"))
    projection = AdminProjection(truth)

    result = projection.append_test_case_revision("TC-STBB19-322-001", _case(2, "更新后的目标"))
    assert result["status"] == "REVISION_APPENDED"
    assert result["case"]["case_version"] == 2
    assert result["case"]["objective"] == "更新后的目标"
    history = truth.projection.history("test_case", "TC-STBB19-322-001")
    assert [row["case_version"] for row in history] == [1, 2]
    assert history[0]["objective"] == "初始目标"


def test_admin_http_serves_chinese_ui_and_r1_api(tmp_path):
    truth = _truth(tmp_path)
    truth_path = str(truth.store.path)
    app = AdminApplication(truth_path)
    server = create_server(app, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = "http://127.0.0.1:%d" % server.server_address[1]
        with urllib.request.urlopen(base + "/api/missions?version=" + RELEASE, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["total"] == 1
        assert payload["items"][0]["mission_id"] == MISSION

        with urllib.request.urlopen(base + "/", timeout=5) as response:
            html = response.read().decode("utf-8")
        assert "RC7 测试数字员工" in html
        assert "测试用例" in html
        assert "缺陷中心" in html
        assert "查询" in html
        assert "分页" not in html or "page" in html
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert not list(tmp_path.glob("**/aitest.db"))
