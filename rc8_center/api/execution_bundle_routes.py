"""Lease-authorized executable-bundle delivery for admitted N7 WorkItems."""
from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException, status
from fastapi.responses import FileResponse

from rc8_center.executable_bundle import ExecutableBundleError, artifact_id_from_ref
from rc8_center.execution_admission import N7ExecutionAdmissionError
from rc8_center.formal_control import CenterControlError


def register_execution_bundle_routes(app: FastAPI) -> None:
    @app.get("/api/v1/work-items/{work_item_id}/execution-bundle")
    def download_execution_bundle(
        work_item_id: str,
        x_rc8_node_id: str = Header(alias="X-RC8-Node-Id", min_length=1),
        x_rc8_lease_id: str = Header(alias="X-RC8-Lease-Id", min_length=1),
    ):
        store = getattr(app.state, "artifact_store", None)
        control = getattr(app.state, "formal_control", None)
        control_repository = getattr(app.state, "control_repository", None)
        admission_gate = getattr(app.state, "n7_execution_admission", None)
        if store is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="ARTIFACT_STORE_NOT_CONFIGURED")
        if control is None or control_repository is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="FORMAL_CONTROL_NOT_CONFIGURED")
        if admission_gate is None or getattr(admission_gate, "artifact_store", None) is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="EXECUTABLE_BUNDLE_AUTHORITY_NOT_CONFIGURED")

        work = control_repository.get_work_item(work_item_id)
        if work is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WORK_ITEM_NOT_FOUND")
        try:
            current = control.authorize_work_item_write(
                test_run_id=work.identity.test_run_id,
                work_item_id=work_item_id,
                node_id=x_rc8_node_id,
                lease_id=x_rc8_lease_id,
            )
            stage_instance_id = control.stage_instance_id_for_work_item(work_item_id)
            admission = admission_gate.authorize_start(
                work=current,
                stage_instance_id=stage_instance_id,
            )
            if admission is None:
                raise N7ExecutionAdmissionError("N7_EXECUTION_ADMISSION_REQUIRED")
            if not admission.bundle_sha256 or admission.bundle_size_bytes is None or admission.bundle_project_subdir is None:
                raise N7ExecutionAdmissionError("N7_EXECUTABLE_BUNDLE_AUTHORITY_REQUIRED")
            artifact_id = artifact_id_from_ref(admission.script_artifact_ref)
            path = store.content_path(artifact_id)
        except (CenterControlError, N7ExecutionAdmissionError, ExecutableBundleError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

        # All dispatch identities are Center-derived from the same admission
        # snapshot. The node consumes these response headers; it never supplies
        # case/prepared/spec/execution Attempt authority in the request.
        return FileResponse(
            path=str(path),
            media_type="application/zip",
            filename="%s.zip" % artifact_id,
            headers={
                "X-RC8-Artifact-Id": artifact_id,
                "X-RC8-SHA256": admission.bundle_sha256,
                "X-RC8-Project-Subdir": admission.bundle_project_subdir,
                "X-RC8-Executable-Spec-Id": admission.executable_spec_id,
                "X-RC8-Prepared-Attempt-Id": admission.prepared_attempt_id,
                "X-RC8-Case-Execution-Attempt-Id": admission.case_execution_attempt_id,
                "X-RC8-Stage-Instance-Id": admission.stage_instance_id,
                "X-RC8-Mission-Node-Id": admission.mission_node_id,
                "X-RC8-Case-Id": admission.case_id,
                "X-RC8-Truth": "LEASE_AUTHORIZED_CURRENT_N7_EXECUTABLE_BUNDLE",
            },
        )
