from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from rc8_center.api.execution_bundle_routes import register_execution_bundle_routes
from rc8_center.formal_control import CenterControlError


class _Store:
    def __init__(self, path: Path) -> None:
        self.path = path

    def content_path(self, artifact_id: str) -> Path:
        if artifact_id != "bundle-1":
            raise ValueError("ARTIFACT_NOT_FOUND")
        return self.path


class _Repository:
    def __init__(self, work: object) -> None:
        self.work = work

    def get_work_item(self, work_item_id: str):
        return self.work if work_item_id == "work-n7" else None


class _Control:
    def __init__(self, work: object) -> None:
        self.work = work

    def authorize_work_item_write(self, *, test_run_id: str, work_item_id: str, node_id: str, lease_id: str):
        if (test_run_id, work_item_id, node_id, lease_id) != ("run-1", "work-n7", "node-1", "lease-1"):
            raise CenterControlError("ACTIVE_WORK_ITEM_LEASE_REQUIRED")
        return self.work

    def stage_instance_id_for_work_item(self, work_item_id: str):
        return "stage-n7" if work_item_id == "work-n7" else None


class _AdmissionGate:
    def __init__(self, artifact_store: object) -> None:
        self.artifact_store = artifact_store

    def authorize_start(self, *, work: object, stage_instance_id: str):
        if stage_instance_id != "stage-n7":
            raise ValueError("N7_STAGE_INSTANCE_REQUIRED")
        return SimpleNamespace(
            bundle_sha256="a" * 64,
            bundle_size_bytes=9,
            bundle_project_subdir="project",
            script_artifact_ref="artifact:bundle-1",
            executable_spec_id="executable:prepared-1",
            prepared_attempt_id="prepared-1",
            case_execution_attempt_id="case-attempt-1",
            stage_instance_id="stage-n7",
            mission_node_id="n7-1",
            case_id="CASE-1",
        )


class ExecutionBundleRouteContractTest(unittest.TestCase):
    def _client(self):
        temp = tempfile.TemporaryDirectory(prefix="rc8-execution-bundle-route-")
        path = Path(temp.name) / "bundle.zip"
        path.write_bytes(b"zip-bytes")
        work = SimpleNamespace(identity=SimpleNamespace(test_run_id="run-1"))
        store = _Store(path)
        app = FastAPI()
        register_execution_bundle_routes(app)
        app.state.artifact_store = store
        app.state.control_repository = _Repository(work)
        app.state.formal_control = _Control(work)
        app.state.n7_execution_admission = _AdmissionGate(store)
        return temp, TestClient(app)

    def test_current_n7_lease_downloads_exact_admitted_bundle(self):
        temp, client = self._client()
        try:
            response = client.get(
                "/api/v1/work-items/work-n7/execution-bundle",
                headers={"X-RC8-Node-Id": "node-1", "X-RC8-Lease-Id": "lease-1"},
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.content, b"zip-bytes")
            self.assertEqual(response.headers["x-rc8-artifact-id"], "bundle-1")
            self.assertEqual(response.headers["x-rc8-sha256"], "a" * 64)
            self.assertEqual(response.headers["x-rc8-project-subdir"], "project")
            self.assertEqual(response.headers["x-rc8-executable-spec-id"], "executable:prepared-1")
            self.assertEqual(response.headers["x-rc8-prepared-attempt-id"], "prepared-1")
            self.assertEqual(response.headers["x-rc8-case-execution-attempt-id"], "case-attempt-1")
            self.assertEqual(response.headers["x-rc8-stage-instance-id"], "stage-n7")
            self.assertEqual(response.headers["x-rc8-mission-node-id"], "n7-1")
            self.assertEqual(response.headers["x-rc8-case-id"], "CASE-1")
            self.assertEqual(response.headers["x-rc8-truth"], "LEASE_AUTHORIZED_CURRENT_N7_EXECUTABLE_BUNDLE")
        finally:
            temp.cleanup()

    def test_stale_or_foreign_lease_cannot_download_bundle(self):
        temp, client = self._client()
        try:
            response = client.get(
                "/api/v1/work-items/work-n7/execution-bundle",
                headers={"X-RC8-Node-Id": "node-1", "X-RC8-Lease-Id": "stale"},
            )
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(response.json()["detail"], "ACTIVE_WORK_ITEM_LEASE_REQUIRED")
        finally:
            temp.cleanup()

    def test_download_route_fails_closed_without_bundle_authority(self):
        temp, client = self._client()
        try:
            client.app.state.n7_execution_admission.artifact_store = None
            response = client.get(
                "/api/v1/work-items/work-n7/execution-bundle",
                headers={"X-RC8-Node-Id": "node-1", "X-RC8-Lease-Id": "lease-1"},
            )
            self.assertEqual(response.status_code, 503, response.text)
            self.assertEqual(response.json()["detail"], "EXECUTABLE_BUNDLE_AUTHORITY_NOT_CONFIGURED")
        finally:
            temp.cleanup()


if __name__ == "__main__":
    unittest.main()
