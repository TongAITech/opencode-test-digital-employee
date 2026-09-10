"""Recovery browser checks; real local Chromium smoke is explicitly labelled."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT / "ai-test/runtime"))
from aitest_runtime.autonomous_orchestration import FakeOpenCodeSessionProvider
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
from aitest_runtime.g4.service import G4RealExecutionService
from aitest_runtime.recovery_browser import CDPBrowserProvider, TeachingObserver, load_binding, safe_url, scrub
from test_g2_1_session_router_control_loop import request, one_task
from aitest_runtime.recovery_executors import OfflineExecutor
from test_recovery_g4_execution import make_repo, RecoveryIntakeService, G3TestingIntelligenceService, R33ApplicationService, RISK_DIMENSIONS, exec_task


def governed_case(root, runtime, mission, execution_profile=None):
    repo, base, head = make_repo(root, 'local-target',
        {'src/loan.py': 'def accepts(amount):\n    return amount > 1\n'},
        {'src/loan.py': 'def accepts(amount):\n    return amount > 0\n'})
    document = root / 'requirement.md'
    document.write_text('Loan amount must be positive. The local service must expose readiness in API and browser.\n', encoding='utf-8')
    intake = RecoveryIntakeService(runtime)
    source = intake.import_document(mission, document, 'LOCAL-REQUIREMENT')['document']['fact_id']
    artifacts = [
        {'artifact_id': 'BR-1', 'kind': 'BR', 'text': 'Loan amount must be positive', 'source_refs': [source], 'asset_refs': [{'kind': 'CODE', 'ref': 'src/loan.py'}]},
        {'artifact_id': 'SR-1', 'kind': 'SR', 'text': 'The local service readiness API responds with ok true', 'source_refs': [source], 'parent_refs': ['BR-1'], 'asset_refs': [{'kind': 'CODE', 'ref': 'src/loan.py'}]},
        {'artifact_id': 'TR-1', 'kind': 'TR', 'text': 'Validate local readiness over HTTP, browser rendering and native unit assertions', 'source_refs': [source], 'parent_refs': ['SR-1'], 'asset_refs': [{'kind': 'CODE', 'ref': 'src/loan.py'}]},
    ]
    analysis = intake.analyze_requirements(mission, 'LOCAL-REQUIREMENT', artifacts)
    g3 = G3TestingIntelligenceService(runtime)
    change = g3.analyze_changes(mission, 'LOCAL-REQUIREMENT', [{'repository_id': 'local-target', 'application_id': 'local-target', 'repository_path': str(repo), 'base_ref': base, 'head_ref': head}], analysis['r3_1_reference'])
    risk = {'dimensions': {name: 2 for name in RISK_DIMENSIONS}, 'evidence_refs': [analysis['analysis']['requirement']['fact_id'], change['change_analysis']['fact_id']]}
    strategy = g3.create_strategy(mission, 'LOCAL-REQUIREMENT', analysis['r3_1_reference'], change['r3_2_references'], risk)
    sid = strategy['strategy']['strategy_version_id']
    points = [point for point in R33ApplicationService(runtime).state(mission).test_points if point.strategy_version_id == sid and point.designability == 'DESIGNABLE'][:1]
    assert points, 'real G3 strategy produced no designable case'
    specs = {point.point_id: {
        'objective': 'Verify local readiness through concrete execution assertions',
        'preconditions': ['Approved loopback fixture is listening'],
        'test_data': {'amount': 1, 'readiness_path': '/api'},
        'ordered_steps': [{'step': 1, 'action': 'Execute the locally approved readiness runner'}],
        'expected_results': [{'step': 1, 'expected': 'HTTP 200 and ok true; page shows Ready; unit assertion succeeds'}],
        'oracle': {'type': 'EXPLICIT_ASSERTIONS', 'pass': 'Runner assertions all succeed'},
        'evidence_requirements': [{'channel': 'PROVIDER_RESULT', 'required': 'hashed execution receipt bound to the canonical attempt'}],
        'postcondition': {'cleanup': 'close temporary resources'},
        'execution_profile': execution_profile or {},
    } for point in points}
    if execution_profile and execution_profile.get('ui_journey'):
        for spec in specs.values():
            spec['ordered_steps']=[{'step':i+1,**action} for i,action in enumerate(execution_profile['ui_journey']['steps'])]
            spec['expected_results']=[{'step':i+1,'expected':{'action':action['action'],'required':'Approved action and its frozen assertion succeed',
                 'value':action.get('value'),'state':action.get('state'),'url':action.get('url')}} for i,action in enumerate(execution_profile['ui_journey']['steps'])]
    if execution_profile and execution_profile.get('api_journey'):
        from api_case_fixture import api_case_spec
        for spec in specs.values():
            detail = api_case_spec(execution_profile)
            spec['ordered_steps'] = detail['ordered_steps']
            spec['expected_results'] = detail['expected_results']
            spec['oracle'].update(detail['oracle'])
    designed = g3.design_cases(mission, sid, strategy['strategy']['strategy_fingerprint'], specs)
    assert designed['ready_cases'], designed
    case_fact = designed['ready_cases'][0]['case']
    case = case_fact['payload']['r3_3_case']
    return case_fact, sid


class PageServer(BaseHTTPRequestHandler):
    def log_message(self, *_args): pass
    def do_GET(self):
        if self.path == "/data":
            data = json.dumps({"status": "ok", "password": "DO_NOT_STORE", "access_token": "DO_NOT_STORE", "detail": "public mock response"}).encode()
            mime = "application/json"
        elif self.path == "/login":
            data = b'<html><body><input type="password" value="DO_NOT_STORE"></body></html>'
            mime = "text/html"
        else:
            data = b'''<html><body><input value="DO_NOT_STORE"><button id="action" onclick="fetch('/data')">Click to query</button>
              <button id="finish" onclick="document.querySelector('#authenticated').hidden=false;document.querySelector('#business-ready').hidden=false">Finish local example</button>
              <div id="page-ready">Local test page</div><div id="authenticated" hidden>Example signed in</div><div id="business-ready" hidden>Ready</div></body></html>'''
            mime = "text/html"
        self.send_response(200); self.send_header("Content-Type", mime); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)


class BrowserTests(unittest.TestCase):
    def test_binding_requires_approval_and_loopback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / "bindings").mkdir()
            path = root / "bindings/browser.json"
            for config in ({}, {"approved": True, "approval_ref": "test", "allowed_origins": ["http://example.test"], "cdp_endpoint": "http://example.test:9222"}):
                path.write_text(json.dumps(config))
                with self.assertRaises(RuntimeError): load_binding(root)

    def test_scrubbing_removes_nested_secrets_and_url_parameters(self):
        value = scrub({"password": "DO_NOT_STORE", "nested": [{"access_token": "DO_NOT_STORE", "detail": "Authorization: Bearer abc"}], "safe": "yes"})
        self.assertNotIn("DO_NOT_STORE", json.dumps(value))
        self.assertNotIn("Bearer abc", json.dumps(value))
        self.assertEqual(safe_url("https://user:pass@example.test/page?otp=123#token"), "https://example.test/page")

    def test_teaching_asset_survives_canonical_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); runtime = create_canonical_runtime(root, db_path=root / "runtime-spine.db")
            service = G21AutonomousOrchestrationService(runtime, root, session_provider=FakeOpenCodeSessionProvider(root))
            mission = service.start_test(request("teaching", "TEACHING"))["intake"]["intake"]["mission_id"]
            provider = CDPBrowserProvider(root, config={"cdp_endpoint": "http://127.0.0.1:9222", "approved": True, "approval_ref": "local-test", "allowed_origins": ["http://127.0.0.1"]}, runtime=runtime)
            observer = TeachingObserver(provider, mission)
            observer._add({"kind": "PAGE", "url": "http://127.0.0.1/", "password": "DO_NOT_STORE"})
            fact = observer.flush()
            restored = create_canonical_runtime(root, db_path=root / "runtime-spine.db")
            state = restored.replay_composed(mission).extension_state("g3_testing_intelligence_product_integration")
            result = state.by_id(fact["fact_id"])
            self.assertEqual(result.payload["g6"], "HOLD")
            self.assertFalse(result.payload["automatic_promotion"])
            self.assertNotIn("DO_NOT_STORE", json.dumps(result.to_dict()))
            self.assertFalse((root / "ai-test/state/aitest.db").exists())

    @unittest.skipUnless(os.environ.get("AITEST_BROWSER_SMOKE_CHROMIUM"), "Explicit native Chromium path required for LOCAL_BROWSER_SMOKE")
    def test_real_local_chromium_observation_human_gate_and_page_crash(self):
        from playwright.sync_api import sync_playwright
        server = ThreadingHTTPServer(("127.0.0.1", 0), PageServer)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True); server_thread.start()
        browser_process = None
        browser_log = None
        try:
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
                root = Path(directory)
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
                origin = f"http://127.0.0.1:{server.server_port}"
                endpoint = f"http://127.0.0.1:{port}"
                browser_log = (root / "browser.log").open("w")
                runtime = create_canonical_runtime(root, db_path=root / "runtime-spine.db")
                service = G21AutonomousOrchestrationService(runtime, root, session_provider=FakeOpenCodeSessionProvider(root))
                mission = service.start_test(request("browser-real", "BROWSER-REAL"))["intake"]["intake"]["mission_id"]
                case_fact, sid = governed_case(root, runtime, mission)
                case = case_fact["payload"]["r3_3_case"]
                first = service.propose_plan(mission, {"objective": "Local real browser human gate validation", "tasks": [exec_task("local-browser", case_fact["fact_id"])], "dependencies": []})["next"]
                checks = {"authenticated_selector": "#authenticated", "page_selector": "#page-ready", "business_selector": "#business-ready"}
                config = {"cdp_endpoint": endpoint, "start_url": origin, "approved": True, "approval_ref": "LOCAL_TEST_ONLY", "allowed_origins": [origin], "response_body_paths": ["/data"], "resume_checks": checks}
                provider = CDPBrowserProvider(root, config=config, runtime=runtime)
                chrome = Path(os.environ["AITEST_BROWSER_SMOKE_CHROMIUM"]).resolve()
                real_popen = subprocess.Popen
                launched_chrome = []

                def capture_browser_process(argv, *popen_args, **popen_kwargs):
                    nonlocal browser_process
                    # Patching the module's subprocess object also intercepts
                    # Playwright's driver process. Preserve its pipe arguments.
                    is_chrome = isinstance(argv, (list, tuple)) and Path(argv[0]).resolve() == chrome
                    if is_chrome:
                        popen_kwargs.update(stdout=browser_log, stderr=browser_log)
                    process = real_popen(argv, *popen_args, **popen_kwargs)
                    if is_chrome:
                        browser_process = process
                        launched_chrome.append(process.pid)
                    return process

                with mock.patch.object(provider, "_chromium_path", return_value=chrome), mock.patch(
                    "aitest_runtime.recovery_browser.subprocess.Popen", side_effect=capture_browser_process
                ):
                    try:
                        launched = provider.launch_browser(headless=True)
                    except Exception as exc:
                        browser_log.flush()
                        raise RuntimeError("Product browser startup failed: " + (root / "browser.log").read_text(errors="replace")[-3000:]) from exc
                self.assertEqual(launched["status"], "READY")
                self.assertFalse(launched["reused"])
                self.assertEqual(launched_chrome, [browser_process.pid])
                self.assertEqual(launched["pid"], browser_process.pid)
                ref = provider.context_ref()
                self.assertEqual(launched["browser_context_ref"]["context_binding_digest"], ref.context_binding_digest)
                reused = provider.launch_browser(headless=True)
                self.assertEqual(reused["status"], "READY")
                self.assertTrue(reused["reused"])
                observer = TeachingObserver(provider, mission)
                with sync_playwright() as driver:
                    browser = driver.chromium.connect_over_cdp(endpoint, timeout=45000)
                    page = browser.contexts[0].pages[0]
                    page.wait_for_load_state("domcontentloaded")
                    page.set_viewport_size({"width": 1000, "height": 700})
                    observer.snapshot(page)
                    page.click("#action"); page.wait_for_timeout(300)
                    fact = observer.flush()
                    kinds = {item["kind"] for item in fact["payload"]["observations"]}
                    self.assertTrue({"PAGE", "SCREENSHOT", "ELEMENT", "NETWORK_RESPONSE"}.issubset(kinds))
                    responses = [item for item in fact["payload"]["observations"] if item["kind"] == "NETWORK_RESPONSE"]
                    self.assertEqual(responses[-1]["response_body"]["status"], "ok")
                    self.assertNotIn("DO_NOT_STORE", json.dumps(fact))
                    page.goto(origin + "/login"); observer.snapshot(page)
                    self.assertEqual(observer.events[-1]["capture_status"], "AUTH_SCREEN_CONTENT_SUPPRESSED")
                    observer.flush()
                    page.goto(origin)
                # Verify actual DOM from a fresh provider connection; boolean
                # claims in the caller cannot mark the HumanGate complete.
                g4 = G4RealExecutionService(runtime, orchestration=service, browser_provider=provider)
                g4.create_goal(mission, {"goal_id": "local-browser-goal", "project_id": "LOCAL-VALIDATION", "release_id": "1.12.0", "requirement_scope": ["LOCAL-REQUIREMENT"], "affected_applications": ["local-target"], "affected_application_target_versions": {"local-target": "1.12.0"}, "coverage_policy": {"target_pct": 95}})
                g4.create_batch(mission, {"batch_id": "local-browser-batch", "goal_id": "local-browser-goal", "case_refs": [case_fact["fact_id"]], "strategy_version_id": sid, "target_application": "local-target", "status": "RUNNING"})
                g4.record_cursor(mission, {"task_id": first["task_id"], "attempt_id": first["attempt"]["attempt_id"], "case_id": case["tc_id"], "case_version": case["case_version_id"], "case_spec_fact_id": case_fact["fact_id"], "execution_batch_id": "local-browser-batch", "pending_step_id": "local-human-step"})
                takeover = g4.request_human_takeover(mission, {"task_id": first["task_id"], "attempt_id": first["attempt"]["attempt_id"], "human_gate_id": "local-human-gate", "browser_context_ref": ref.to_dict(), "required_action": "Complete local example", "resume_mode": "EXPLICIT", "resume_condition": checks})
                self.assertEqual(takeover["status"], "WAITING_HUMAN")
                self.assertEqual(CDPBrowserProvider(root, config=config, runtime=runtime).inspect_lease(ref), "HUMAN")
                with self.assertRaises(Exception):
                    g4.complete_human_takeover(mission, {"human_gate_id": "local-human-gate", "completion_mode": "EXPLICIT", "authenticated": True})
                with sync_playwright() as driver:
                    browser = driver.chromium.connect_over_cdp(endpoint, timeout=45000)
                    page = browser.contexts[0].pages[0]
                    page.click("#finish")
                    # Reopening the product entry must retain the exact live
                    # authenticated document, even when start_url is identical.
                    page.evaluate("window.__aitestReuseSentinel = 'authenticated-document'")
                    current_url = page.url
                    reused = provider.launch_browser(headless=True)
                    self.assertTrue(reused["reused"])
                    self.assertEqual(page.url, current_url)
                    self.assertEqual(page.evaluate("window.__aitestReuseSentinel"), "authenticated-document")
                    self.assertTrue(page.locator("#authenticated").is_visible())
                    self.assertTrue(page.locator("#business-ready").is_visible())
                    self.assertEqual(reused["browser_context_ref"]["context_binding_digest"], ref.context_binding_digest)
                completed = g4.complete_human_takeover(mission, {"human_gate_id": "local-human-gate", "completion_mode": "EXPLICIT"})
                self.assertIn(completed["status"], {"PASS", "RESUMED", "RESUME_SAFE"})
                self.assertEqual(CDPBrowserProvider(root, config=config, runtime=runtime).inspect_lease(ref), "AI")
                (root / 'bindings').mkdir(exist_ok=True)
                (root / 'bindings/browser.json').write_text(json.dumps(config))
                previous_db = os.environ.get('AITEST_RUNTIME_SPINE_DB')
                os.environ['AITEST_RUNTIME_SPINE_DB'] = str(root / 'runtime-spine.db')
                try:
                    runner = OfflineExecutor(root, 'BROWSER_UI', {'approved': True, 'approval_ref': 'LOCAL_TEST_ONLY', 'allowed_origins': [origin]})
                    result, passed = runner._run_browser_ui({'expected': {'selector': '#authenticated', 'text': 'Example signed in'}},
                        {'url': origin + '/', 'authorized_scope': {'origins': [origin]}, 'browser_context_ref': provider.context_ref().to_dict()})
                    self.assertTrue(passed)
                    self.assertEqual(result['runner'], 'playwright-existing-governed-context')
                finally:
                    if previous_db is None: os.environ.pop('AITEST_RUNTIME_SPINE_DB', None)
                    else: os.environ['AITEST_RUNTIME_SPINE_DB'] = previous_db
                with sync_playwright() as driver:
                    browser = driver.chromium.connect_over_cdp(endpoint, timeout=45000)
                    page = browser.contexts[0].pages[0]
                    # Crash the renderer while retaining the actual browser
                    # profile/context. The observer must reload and keep recording.
                    try:
                        page.goto("chrome://crash", timeout=1500)
                    except Exception:
                        pass
                result = TeachingObserver(provider, mission).run(duration=30, interval=0.2)
                self.assertEqual(result["status"], "RECORDED")
                assets = runtime.replay_composed(mission).extension_state("g3_testing_intelligence_product_integration")
                recovered_kinds = {observation["kind"] for fact_id in result["asset_refs"] for observation in assets.by_id(fact_id).payload["observations"]}
                self.assertTrue({"PAGE", "SCREENSHOT"}.issubset(recovered_kinds), {"kinds": list(recovered_kinds), "assets": [assets.by_id(f).to_dict() for f in result["asset_refs"]]})
                self.assertEqual(provider.context_ref().context_binding_digest, ref.context_binding_digest)
                self.assertFalse((root / "ai-test/state/aitest.db").exists())
        finally:
            if browser_process is not None:
                browser_process.terminate()
                try: browser_process.wait(timeout=5)
                except subprocess.TimeoutExpired: browser_process.kill()
            if browser_log is not None: browser_log.close()
            server.shutdown(); server.server_close(); server_thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
