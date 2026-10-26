from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

from rc8_node.autonomous_claim_client import ClaimedWork
from rc8_node.dsh_json_runner import DshJsonResult
from rc8_node.n7_execution_worker import N7ExecutionDispatchError, N7ExecutionDispatchWorker


class _FakeAgent:
    def __init__(self) -> None:
        self.identity = SimpleNamespace(node_id="node-n7")
        self.center = SimpleNamespace(base_url="http://center.invalid")
        self.started = []

    def start(self, work_item_id: str, *, lease_id: str):
        self.started.append((work_item_id, lease_id))
        return {"work_item": {"state": "RUNNING"}}


class _FakeDshRunner:
    def __init__(self, *, tool_name: str = "dsh-agent-teams", output=None) -> None:
        self.tool_name = tool_name
        self.output = output
        self.prompts = []

    def run(self, prompt: str) -> DshJsonResult:
        self.prompts.append(prompt)
        output = self.output or {
            "dispatch_status": "ACCEPTED",
            "case_id": "CASE-7",
            "executable_spec_id": "executable:case-attempt-7",
        }
        return DshJsonResult(
            session_id="session-n7-dispatch",
            tool_calls=({"call_ref": "tool:1", "tool_name": self.tool_name},),
            output=output,
            stdout="",
            stderr="",
            exit_code=0,
        )


class _Worker(N7ExecutionDispatchWorker):
    def __init__(self, *args, bundle_bytes: bytes, headers, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.bundle_bytes = bundle_bytes
        self.headers = headers

    def _download_bundle(self, work_item_id: str, lease_id: str):
        return self.bundle_bytes, self.headers


def _bundle() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("project/pom.xml", "<project/>")
        archive.writestr("project/src/test/java/Case7Test.java", "class Case7Test {}")
    return buffer.getvalue()


def _claim() -> ClaimedWork:
    return ClaimedWork(
        claimed=True,
        work_item={
            "identity": {
                "work_item_id": "work-n7",
                "stage": "APPLICABLE_LAYER_EXECUTION",
            },
            "lease_id": "lease-n7-governance",
        },
        stage_instance_id="stage-n7",
        truth_note="CENTER_LEASE",
    )


def _headers(bundle: bytes):
    return {
        "X-RC8-Case-Id": "CASE-7",
        "X-RC8-Prepared-Attempt-Id": "prepared:case-attempt-7",
        "X-RC8-Case-Execution-Attempt-Id": "case-attempt-7",
        "X-RC8-Executable-Spec-Id": "executable:case-attempt-7",
        "X-RC8-Stage-Instance-Id": "stage-n7",
        "X-RC8-Mission-Node-Id": "mission-n7",
        "X-RC8-SHA256": hashlib.sha256(bundle).hexdigest(),
        "X-RC8-Project-Subdir": "project",
    }


class N7ExecutionDispatchWorkerContractTest(unittest.TestCase):
    def _worker(self, temp: str, *, runner=None, headers=None, bundle=None):
        content = bundle or _bundle()
        return _Worker(
            agent=_FakeAgent(),
            dsh_runner=runner or _FakeDshRunner(),
            work_dir=temp,
            center_url="http://center.invalid",
            bundle_bytes=content,
            headers=headers or _headers(content),
        )

    def test_current_center_bundle_is_dispatched_to_agent_teams_without_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            worker = self._worker(temp)
            result = worker.execute(_claim())
        self.assertEqual("DISPATCHED", result["status"])
        self.assertEqual("N7_DISPATCH_ONLY_NOT_EXECUTION_RESULT_NOT_PASS", result["truth_note"])
        self.assertEqual("case-attempt-7", result["case_execution_attempt_id"])
        self.assertEqual([("work-n7", "lease-n7-governance")], worker.agent.started)
        self.assertFalse(hasattr(worker.agent, "complete"), "dispatch slice must not terminalize N7")
        self.assertIn('"required_orchestrator": "dsh-agent-teams"', worker.dsh_runner.prompts[0])
        self.assertIn('"governance_attempt_id": "lease-n7-governance"', worker.dsh_runner.prompts[0])
        self.assertIn('"case_execution_attempt_id": "case-attempt-7"', worker.dsh_runner.prompts[0])

    def test_dsh_agent_teams_tool_call_is_mandatory(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            worker = self._worker(temp, runner=_FakeDshRunner(tool_name="shell"))
            with self.assertRaisesRegex(N7ExecutionDispatchError, "N7_DSH_AGENT_TEAMS_TOOL_CALL_REQUIRED"):
                worker.execute(_claim())

    def test_center_stage_identity_cannot_be_replaced_by_worker(self) -> None:
        bundle = _bundle()
        headers = _headers(bundle)
        headers["X-RC8-Stage-Instance-Id"] = "stage-forged"
        with tempfile.TemporaryDirectory() as temp:
            worker = self._worker(temp, bundle=bundle, headers=headers)
            with self.assertRaisesRegex(N7ExecutionDispatchError, "N7_BUNDLE_STAGE_AUTHORITY_MISMATCH"):
                worker.execute(_claim())

    def test_bundle_sha_is_verified_before_dsh_dispatch(self) -> None:
        bundle = _bundle()
        headers = _headers(bundle)
        headers["X-RC8-SHA256"] = "0" * 64
        runner = _FakeDshRunner()
        with tempfile.TemporaryDirectory() as temp:
            worker = self._worker(temp, runner=runner, bundle=bundle, headers=headers)
            with self.assertRaisesRegex(N7ExecutionDispatchError, "N7_EXECUTABLE_BUNDLE_SHA256_MISMATCH"):
                worker.execute(_claim())
        self.assertEqual([], runner.prompts)

    def test_zip_path_traversal_is_fail_closed(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("../escape.txt", "forbidden")
        bundle = buffer.getvalue()
        headers = _headers(bundle)
        with tempfile.TemporaryDirectory() as temp:
            worker = self._worker(temp, bundle=bundle, headers=headers)
            with self.assertRaisesRegex(N7ExecutionDispatchError, "N7_EXECUTABLE_BUNDLE_PATH_TRAVERSAL"):
                worker.execute(_claim())

    def test_agent_teams_output_cannot_change_case_or_spec_identity(self) -> None:
        runner = _FakeDshRunner(output={
            "dispatch_status": "ACCEPTED",
            "case_id": "CASE-FORGED",
            "executable_spec_id": "executable:case-attempt-7",
        })
        with tempfile.TemporaryDirectory() as temp:
            worker = self._worker(temp, runner=runner)
            with self.assertRaisesRegex(N7ExecutionDispatchError, "N7_DSH_DISPATCH_CASE_AUTHORITY_MISMATCH"):
                worker.execute(_claim())


if __name__ == "__main__":
    unittest.main()
