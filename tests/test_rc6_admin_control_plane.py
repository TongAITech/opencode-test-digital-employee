import json
import threading
from pathlib import Path
from urllib.request import urlopen

from rc6_release import admin_server


def _write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _fixture(tmp_path, monkeypatch):
    home = tmp_path / "pkg"
    state = home / "runtime-state"
    ws = tmp_path / "PFC"
    home.mkdir()
    (home / "SOURCE_COMMIT").write_text("a" * 40, encoding="utf-8")
    (home / "BUILD_ID").write_text("RC6-test", encoding="utf-8")
    (home / "RELEASE_STATUS").write_text("ENGINEERING_CANDIDATE_NOT_BANK_FINAL", encoding="utf-8")
    monkeypatch.setenv("PFC_AITEST_HOME", str(home))
    monkeypatch.setenv("PFC_AITEST_STATE_DIR", str(state))
    monkeypatch.setenv("PFC_WORKSPACE", str(ws))
    events = [
        {"seq": 1, "event_id": "e1", "event_type": "REQUIREMENT_ANALYSIS_UPSERTED", "entity_type": "requirement_analysis", "entity_id": "ra-1", "entity_version": 1, "payload": {"id": "ra-1", "release_id": "BLOAN-PF1.2.0", "requirement_id": "STBB19-322", "summary": "需求分析"}},
        {"seq": 2, "event_id": "e2", "event_type": "CODE_ANALYSIS_UPSERTED", "entity_type": "code_analysis", "entity_id": "ca-1", "entity_version": 1, "payload": {"id": "ca-1", "release_id": "BLOAN-PF1.2.0", "requirement_id": "STBB19-322", "summary": "代码分析"}},
        {"seq": 3, "event_id": "e3", "event_type": "TEST_CASE_UPSERTED", "entity_type": "test_case", "entity_id": "tc-1", "entity_version": 1, "payload": {"tc_id": "tc-1", "release_id": "BLOAN-PF1.2.0", "requirement_id": "STBB19-322", "layer": "L3", "objective": "接口验证"}},
        {"seq": 4, "event_id": "e4", "event_type": "EXECUTION_ATTEMPT_UPSERTED", "entity_type": "execution_attempt", "entity_id": "at-1", "entity_version": 1, "payload": {"attempt_id": "at-1", "release_id": "BLOAN-PF1.2.0", "requirement_id": "STBB19-322", "status": "PASS"}},
        {"seq": 5, "event_id": "e5", "event_type": "EVIDENCE_UPSERTED", "entity_type": "evidence", "entity_id": "ev-1", "entity_version": 1, "payload": {"id": "ev-1", "release_id": "BLOAN-PF1.2.0", "ref": "evidence://1"}},
        {"seq": 6, "event_id": "e6", "event_type": "DEFECT_UPSERTED", "entity_type": "defect", "entity_id": "df-1", "entity_version": 1, "payload": {"id": "df-1", "release_id": "BLOAN-PF1.2.0", "title": "真实缺陷"}},
        {"seq": 7, "event_id": "w1", "event_type": "WORKER_STARTED", "payload": {"worker_id": "pfc-requirement-analysis", "session_id": "S-A", "password": "MUST_NOT_LEAK"}},
    ]
    event_path = state / "r1" / "event-stream.jsonl"
    event_path.parent.mkdir(parents=True)
    event_path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in events) + "\n", encoding="utf-8")
    _write_json(state / "missions" / "M-BLOAN-PF1.2.0.json", {"mission_id": "M-BLOAN-PF1.2.0", "release_id": "BLOAN-PF1.2.0", "stage": "CODE_ANALYSIS", "open_gaps": []})
    _write_json(state / "bank-reality.json", {"repository": {"cfg-admin": {"status": "READY", "attributes": {"repo": "cfg-admin"}}}})
    _write_json(ws / ".dsh" / "rc6" / "TOOL_PROFILE.json", {"tools": [{"tool_id": "codegraph", "status": "PROBE_PASS", "path": "D:/tools/codegraph-server-win32-x64.exe", "password": "MUST_NOT_LEAK"}]})
    return home, state, ws


def test_admin_projects_only_from_r1_and_supports_filters(tmp_path, monkeypatch):
    _fixture(tmp_path, monkeypatch)
    req = admin_server._api("requirements", {"version": ["BLOAN-PF1.2.0"], "requirement": ["STBB19-322"], "page": ["1"], "page_size": ["20"]})
    assert req["total"] == 1
    assert req["items"][0]["id"] == "ra-1"
    cases = admin_server._api("l1-l7", {"layer": ["L3"]})
    assert cases["total"] == 1
    assert cases["items"][0]["tc_id"] == "tc-1"
    assert admin_server._api("versions", {})["items"][0]["release_id"] == "BLOAN-PF1.2.0"


def test_admin_exposes_mission_tools_reality_without_secrets(tmp_path, monkeypatch):
    _fixture(tmp_path, monkeypatch)
    assert admin_server._api("missions", {})["items"][0]["mission_id"] == "M-BLOAN-PF1.2.0"
    tools = admin_server._api("tools", {})
    assert tools["items"][0]["tool_id"] == "codegraph"
    assert tools["items"][0]["password"] == "[REDACTED]"
    workers = admin_server._api("workers", {})
    assert workers["total"] == 1
    assert workers["items"][0]["payload"]["password"] == "[REDACTED]"
    assert admin_server._api("bank-reality", {})["total"] == 1


def test_admin_http_health_and_chinese_ui(tmp_path, monkeypatch):
    _fixture(tmp_path, monkeypatch)
    server = admin_server.ThreadingHTTPServer(("127.0.0.1", 0), admin_server.Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        with urlopen("http://%s:%s/api/health" % (host, port), timeout=2) as response:
            health = json.loads(response.read().decode("utf-8"))
        assert health["status"] == "PASS"
        assert health["service"] == "RC6_ADMIN"
        assert health["runtime"]["durable_truth"] == "R1_EVENT_STREAM"
        assert health["runtime"]["legacy_aitest_db_used"] is False
        with urlopen("http://%s:%s/" % (host, port), timeout=2) as response:
            page = response.read().decode("utf-8")
        assert "RC6 测试后管" in page
        assert "版本管理" in page
        assert "需求分析" in page
        assert "测试用例" in page
        assert "Mission" in page
        assert "Bank Reality" in page
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_admin_is_read_only_and_never_creates_legacy_db(tmp_path, monkeypatch):
    home, state, _ = _fixture(tmp_path, monkeypatch)
    before = (state / "r1" / "event-stream.jsonl").read_bytes()
    admin_server._api("overview", {})
    admin_server._api("defects", {})
    after = (state / "r1" / "event-stream.jsonl").read_bytes()
    assert before == after
    assert not list(home.rglob("aitest.db"))
    assert not list(state.rglob("aitest.db"))
