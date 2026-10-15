from pathlib import Path

from rc7_runtime.diagnosis_providers import MultiToolLogDiagnoser
from rc7_runtime.requirement_toolchain import RequirementDiffEngine, RequirementDocumentParser
from rc7_runtime.reporting import ReportRenderer


def test_requirement_parser_and_diff(tmp_path: Path):
    before = tmp_path / "before.md"
    after = tmp_path / "after.md"
    before.write_text("金额必须大于0\n上限500000.00\n", encoding="utf-8")
    after.write_text("金额必须大于0\n上限500000.00\n500000.01必须拒绝\n", encoding="utf-8")
    parser = RequirementDocumentParser()
    old = parser.parse(str(before))
    new = parser.parse(str(after))
    changes = RequirementDiffEngine().diff(old, new)
    assert len(old) == 2
    assert len(new) == 3
    assert changes
    assert any(item.after == "500000.01必须拒绝" for item in changes)


def test_diagnosis_provider_routes_404_to_route():
    result = MultiToolLogDiagnoser().analyze("HTTP 404 route not found /cfg-data/test", ["api"])
    assert result["failure_class"] == "ROUTE"


def test_diagnosis_provider_does_not_turn_500_into_product():
    result = MultiToolLogDiagnoser().analyze("HTTP 500 Internal Server Error", ["api"])
    assert result["failure_class"] == "UNKNOWN"


def test_report_renderer_outputs_json_html_junit_and_allure(tmp_path: Path):
    report = {
        "mission_id": "M1",
        "release_id": "R1",
        "summary": {"execution_total": 2, "execution_results": {"PASS": 1, "FAIL": 1}},
        "executions": [
            {"attempt_id": "A1", "tc_id": "TC1", "layer": "L3", "status": "PASS"},
            {"attempt_id": "A2", "tc_id": "TC2", "layer": "L5", "status": "FAIL"},
        ],
        "defects": [],
        "residual_risk": {"open_gaps": []},
    }
    paths = ReportRenderer().write_all(report, str(tmp_path))
    assert Path(paths["json"]).is_file()
    assert Path(paths["html"]).is_file()
    assert Path(paths["junit"]).is_file()
    assert len(list(Path(paths["allure_results"]).glob("*-result.json"))) == 2
