import json
import tempfile
import unittest
from pathlib import Path

from rc6_runtime.contracts import DomainValidationError
from rc6_runtime.presentation import (
    ADMIN_ENTITIES,
    AdminHtmlRenderer,
    AdminReadModel,
    AllureRenderer,
    AllureResultsAdapter,
    MissionReportBuilder,
    PresentationError,
    TruthReconciler,
)
from rc6_runtime.truth import TruthRuntime


RELEASE = "BLOAN-PF1.2.0"
REQ = "STBB19-320"


def seed_truth(path):
    rt = TruthRuntime(path)
    rt.append_atomic("REQUIREMENT_ANALYSIS_UPSERTED", {
        "id": "REQA-320-v1", "release_id": RELEASE, "requirement_id": REQ, "sst_id": "STB915-7489",
        "br": [{"id": "BR-1"}], "sr": [{"id": "SR-1"}], "tr": [{"id": "TR-1"}],
        "evidence_refs": ["evidence://requirement/320"], "artifact_version": 1,
    })
    rt.append_atomic("CODE_ANALYSIS_UPSERTED", {
        "id": "CODE-320-v1", "release_id": RELEASE, "requirement_id": REQ,
        "revision_refs": ["git://cfg-data@abc"], "impact_refs": ["symbol://LoanService.approve"],
        "evidence_refs": ["evidence://codegraph/320"], "artifact_version": 1,
    })
    rt.append_atomic("TEST_INTENT_UPSERTED", {
        "id": "INT-320-1", "release_id": RELEASE, "requirement_id": REQ, "sst_id": "STB915-7489",
        "objective": "验证贷款审批规则", "source_refs": ["source://BR-1"], "artifact_version": 1,
    })
    rt.append_atomic("TEST_CONDITION_UPSERTED", {
        "id": "COND-320-1", "release_id": RELEASE, "requirement_id": REQ, "sst_id": "STB915-7489",
        "intent_id": "INT-320-1", "condition": "合法申请可审批", "risk": "HIGH",
        "source_refs": ["source://INT-320-1"], "artifact_version": 1,
    })
    for i in range(1, 4):
        rt.append_atomic("TEST_CASE_UPSERTED", {
            "tc_id": f"TC-320-{i}", "case_version": 1, "release_id": RELEASE, "requirement_id": REQ,
            "sst_id": "STB915-7489", "condition_id": "COND-320-1", "layer": "L3",
            "objective": f"接口场景{i}", "preconditions": ["FAT1 ready"], "test_data": {"n": i},
            "steps": ["调用审批接口"], "expected": "返回预期业务结果",
            "oracle": {"type": "business"}, "evidence_requirements": ["actual_result", "tool_call_ref"],
            "status": "FROZEN",
        })
    rt.append_atomic("EXECUTION_ATTEMPT_UPSERTED", {
        "attempt_id": "ATT-320-1", "release_id": RELEASE, "requirement_id": REQ,
        "tc_id": "TC-320-1", "case_version": 1, "target_id": "TARGET-FAT1", "layer": "L3",
        "status": "FAIL", "actual_result": {"http": 200, "business": "WRONG"},
        "tool_call_refs": ["toolcall://api/1"], "evidence_refs": ["evidence://actual/1"], "artifact_version": 1,
    })
    rt.append_atomic("ASSERTION_UPSERTED", {
        "id": "ASSERT-320-1", "release_id": RELEASE, "attempt_id": "ATT-320-1", "tc_id": "TC-320-1",
        "oracle_ref": "oracle://TC-320-1", "passed": False,
        "evidence_refs": ["evidence://assertion/1"], "artifact_version": 1,
    })
    rt.append_atomic("EVIDENCE_UPSERTED", {
        "id": "EVD-320-1", "release_id": RELEASE, "requirement_id": REQ, "tc_id": "TC-320-1", "attempt_id": "ATT-320-1",
        "kind": "API_ACTUAL", "ref": "evidence://actual/1", "source_artifact_ref": "execution://ATT-320-1",
        "metadata": {"http_status": 200}, "artifact_version": 1,
    })
    rt.append_atomic("DEFECT_UPSERTED", {
        "id": "DEF-320-1", "release_id": RELEASE, "requirement_id": REQ, "tc_id": "TC-320-1", "attempt_id": "ATT-320-1",
        "title": "审批结果与规则不一致", "severity": "HIGH", "status": "CONFIRMED",
        "evidence_refs": ["evidence://actual/1", "evidence://assertion/1"], "artifact_version": 1,
    })
    rt.append_atomic("COVERAGE_OBSERVATION_UPSERTED", {
        "id": "COV-320-1", "release_id": RELEASE, "target_id": "TARGET-FAT1", "attempt_id": "ATT-320-1",
        "tc_id": "TC-320-1", "layer": "L3", "subject_id": "S-L3-ROUTE", "dimension": "route", "covered": True,
        "tool_call_ref": "toolcall://api/coverage/1", "evidence_ref": "evidence://api/coverage/1", "artifact_version": 1,
    })
    rt.append_atomic("REPORT_UPSERTED", {
        "id": "REPORT-MISSION-1", "release_id": RELEASE, "mission_id": "MISSION-1", "status": "GENERATED",
        "artifact_refs": ["execution://ATT-320-1", "defect://DEF-320-1"], "generated_at": 1, "artifact_version": 1,
    })
    return rt


class Wave12PresentationTests(unittest.TestCase):
    def test_extended_r1_replay_is_deterministic_and_queryable(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "r1.jsonl"
            rt = seed_truth(path)
            before = rt.projection.snapshot()
            inventory = rt.full_inventory()
            self.assertEqual(inventory["requirement_analysis"], 1)
            self.assertEqual(inventory["code_analysis"], 1)
            self.assertEqual(inventory["execution_attempt"], 1)
            self.assertEqual(inventory["defect"], 1)
            self.assertEqual(rt.rebuild_projection(), before)
            rt2 = TruthRuntime(path)
            self.assertEqual(rt2.projection.snapshot(), before)

    def test_admin_is_live_r1_projection_with_filters_and_pagination(self):
        with tempfile.TemporaryDirectory() as d:
            rt = seed_truth(Path(d) / "r1.jsonl")
            admin = AdminReadModel(rt)
            page1 = admin.list("test_case", release_id=RELEASE, requirement_id=REQ, page=1, page_size=2)
            self.assertEqual(page1.total, 3)
            self.assertEqual(len(page1.items), 2)
            page2 = admin.list("test_case", release_id=RELEASE, requirement_id=REQ, page=2, page_size=2)
            self.assertEqual(len(page2.items), 1)
            self.assertEqual(admin.list("test_case", layer="L3").total, 3)
            # No shadow store: append to R1 and the same Admin object sees it immediately.
            rt.append_atomic("EVIDENCE_UPSERTED", {
                "id": "EVD-NEW", "release_id": RELEASE, "kind": "LOG", "ref": "evidence://new",
                "source_artifact_ref": "execution://ATT-320-1", "metadata": {}, "artifact_version": 1,
            })
            self.assertEqual(admin.list("evidence", release_id=RELEASE).total, 2)

    def test_admin_shell_is_chinese_query_oriented_not_dashboard_only(self):
        html = AdminHtmlRenderer.index_html()
        for text in ("需求分析", "代码分析", "测试用例", "测试执行", "缺陷", "测试报告", "版本", "需求编号", "SST编号", "查询", "上一页", "下一页"):
            self.assertIn(text, html)
        self.assertIn("/api/", html)

    def test_allure_is_generated_from_r1_execution_truth(self):
        with tempfile.TemporaryDirectory() as d:
            rt = seed_truth(Path(d) / "r1.jsonl")
            results = Path(d) / "allure-results"
            manifest = AllureResultsAdapter(rt).generate(RELEASE, results)
            self.assertEqual(manifest["execution_attempt_ids"], ["ATT-320-1"])
            self.assertEqual(manifest["result_count"], 1)
            files = list(results.glob("*-result.json"))
            self.assertEqual(len(files), 1)
            payload = json.loads(files[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "failed")
            self.assertEqual(payload["fullName"], "ATT-320-1")
            self.assertIn("TARGET-FAT1", [x["value"] for x in payload["labels"]])

    def test_allure_renderer_invokes_configured_cli_automatically(self):
        with tempfile.TemporaryDirectory() as d:
            rt = seed_truth(Path(d) / "r1.jsonl")
            results = Path(d) / "allure-results"
            AllureResultsAdapter(rt).generate(RELEASE, results)
            calls = []
            renderer = AllureRenderer(r"D:\AIsoftware\allure-commandline-2.13.8\allure-2.13.8\bin\allure.bat", runner=lambda args: calls.append(args))
            out = renderer.render(results, Path(d) / "report" / "allure")
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][1], "generate")
            self.assertIn("--clean", calls[0])
            self.assertTrue(out["report_index"].endswith("index.html"))

    def test_report_and_admin_and_allure_reconcile_to_same_r1_identities(self):
        with tempfile.TemporaryDirectory() as d:
            rt = seed_truth(Path(d) / "r1.jsonl")
            admin = AdminReadModel(rt)
            allure_manifest = AllureResultsAdapter(rt).generate(RELEASE, Path(d) / "allure-results")
            report_manifest = MissionReportBuilder(admin).build(RELEASE, "MISSION-1", Path(d) / "report", "../allure/index.html")
            result = TruthReconciler(rt, admin).reconcile(RELEASE, report_manifest, allure_manifest)
            self.assertTrue(result["passed"], result)
            for entity in ADMIN_ENTITIES:
                self.assertEqual(result["truth_counts"][entity], admin.summary(RELEASE)["counts"][entity])

    def test_reconciler_detects_missing_allure_execution(self):
        with tempfile.TemporaryDirectory() as d:
            rt = seed_truth(Path(d) / "r1.jsonl")
            admin = AdminReadModel(rt)
            report_manifest = MissionReportBuilder(admin).build(RELEASE, "MISSION-1", Path(d) / "report", "../allure/index.html")
            bad_allure = {"generated_from": "R1_EVENT_STREAM_PROJECTION", "execution_attempt_ids": [], "result_count": 0}
            result = TruthReconciler(rt, admin).reconcile(RELEASE, report_manifest, bad_allure)
            self.assertFalse(result["passed"])
            self.assertIn("ALLURE_EXECUTION_ID_MISMATCH", result["mismatches"])

    def test_evidence_secret_fields_are_rejected_from_r1(self):
        with tempfile.TemporaryDirectory() as d:
            rt = TruthRuntime(Path(d) / "r1.jsonl")
            with self.assertRaises(Exception) as ctx:
                rt.append_atomic("EVIDENCE_UPSERTED", {
                    "id": "EVD-SECRET", "release_id": RELEASE, "kind": "CAT", "ref": "evidence://cat/x",
                    "source_artifact_ref": "diagnosis://x", "metadata": {"auth_token": "must-not-persist"}, "artifact_version": 1,
                })
            self.assertIn("SECRET_FIELD_FORBIDDEN_IN_R1_EVIDENCE", str(ctx.exception))

    def test_report_manifest_contains_all_r1_entity_identity_sets(self):
        with tempfile.TemporaryDirectory() as d:
            rt = seed_truth(Path(d) / "r1.jsonl")
            admin = AdminReadModel(rt)
            manifest = MissionReportBuilder(admin).build(RELEASE, "MISSION-1", Path(d) / "report", "../allure/index.html")
            self.assertEqual(set(manifest["identities"]), set(ADMIN_ENTITIES))
            self.assertEqual(manifest["identities"]["test_case"], ["TC-320-1", "TC-320-2", "TC-320-3"])
            self.assertEqual(manifest["identities"]["defect"], ["DEF-320-1"])
            self.assertEqual(manifest["source"], "R1_EVENT_STREAM_PROJECTION")


if __name__ == "__main__":
    unittest.main()
