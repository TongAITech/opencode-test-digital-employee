"""N7 execution dispatch worker for the RC8 office node.

This slice deliberately stops at a real DSH Agent Teams dispatch boundary. It
never converts a model/team response into PASS and never completes the N7
WorkItem. Center remains authoritative for the lease, N4/N5/N6 admission and
immutable executable bundle identity.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from .agent import NodeAgentError
from .autonomous_claim_client import ClaimedWork
from .dsh_json_runner import DshJsonResult, DshJsonRunner
from .formal_agent import FormalNodeAgent


class N7ExecutionDispatchError(RuntimeError):
    pass


@dataclass(frozen=True)
class N7DispatchAuthority:
    case_id: str
    prepared_attempt_id: str
    case_execution_attempt_id: str
    executable_spec_id: str
    stage_instance_id: str
    mission_node_id: str
    sha256: str
    project_subdir: str


class N7ExecutionDispatchWorker:
    """Start an admitted N7 WorkItem and dispatch its exact bundle to Agent Teams."""

    STAGE = "APPLICABLE_LAYER_EXECUTION"
    REQUIRED_TEAM_TOOL = "dsh-agent-teams"

    def __init__(
        self,
        *,
        agent: FormalNodeAgent,
        dsh_runner: DshJsonRunner,
        work_dir: str,
        center_url: Optional[str] = None,
        http_timeout_seconds: int = 30,
    ) -> None:
        self.agent = agent
        self.dsh_runner = dsh_runner
        self.work_dir = Path(work_dir)
        self.center_url = str(center_url or getattr(agent.center, "base_url", "") or "").strip().rstrip("/")
        self.http_timeout_seconds = int(http_timeout_seconds)
        if not self.center_url:
            raise N7ExecutionDispatchError("N7_CENTER_URL_REQUIRED")
        if self.http_timeout_seconds <= 0:
            raise N7ExecutionDispatchError("N7_HTTP_TIMEOUT_INVALID")
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def execute(self, claimed: ClaimedWork) -> Dict[str, Any]:
        stage = str(claimed.stage or "").strip()
        work_item_id = str(claimed.work_item_id or "").strip()
        lease_id = str(claimed.lease_id or "").strip()
        stage_instance_id = str(claimed.stage_instance_id or "").strip()
        if stage != self.STAGE:
            raise N7ExecutionDispatchError("N7_STAGE_REQUIRED")
        if not work_item_id or not lease_id or not stage_instance_id:
            raise N7ExecutionDispatchError("N7_CLAIM_IDENTITY_INCOMPLETE")

        # Center re-runs the deterministic N7 admission gate here and creates
        # the governance Attempt. No DSH/model identity participates in start.
        self.agent.start(work_item_id, lease_id=lease_id)

        bundle_bytes, headers = self._download_bundle(work_item_id, lease_id)
        authority = self._authority_from_headers(headers, stage_instance_id=stage_instance_id)
        actual_sha = hashlib.sha256(bundle_bytes).hexdigest()
        if actual_sha.lower() != authority.sha256.lower():
            raise N7ExecutionDispatchError("N7_EXECUTABLE_BUNDLE_SHA256_MISMATCH")

        dispatch_root = self.work_dir / self._safe_component(work_item_id) / self._safe_component(lease_id)
        if dispatch_root.exists():
            shutil.rmtree(str(dispatch_root))
        dispatch_root.mkdir(parents=True, exist_ok=False)
        bundle_path = dispatch_root / "executable-bundle.zip"
        bundle_path.write_bytes(bundle_bytes)
        extract_root = dispatch_root / "bundle"
        self._safe_extract(bundle_path, extract_root)
        project_dir = self._project_dir(extract_root, authority.project_subdir)

        prompt = self._dispatch_prompt(
            work_item_id=work_item_id,
            lease_id=lease_id,
            authority=authority,
            project_dir=project_dir,
        )
        result = self.dsh_runner.run(prompt)
        self._require_agent_teams_dispatch(result, authority)

        # This is intentionally not WorkItem completion and not PASS. The next
        # N7 slice must bind actual tool execution/assertions/evidence back to R1.
        return {
            "status": "DISPATCHED",
            "stage": self.STAGE,
            "work_item_id": work_item_id,
            "lease_id": lease_id,
            "case_id": authority.case_id,
            "prepared_attempt_id": authority.prepared_attempt_id,
            "case_execution_attempt_id": authority.case_execution_attempt_id,
            "executable_spec_id": authority.executable_spec_id,
            "stage_instance_id": authority.stage_instance_id,
            "mission_node_id": authority.mission_node_id,
            "bundle_sha256": authority.sha256,
            "project_dir": str(project_dir),
            "dsh_session_id": result.session_id,
            "team_tool": self.REQUIRED_TEAM_TOOL,
            "truth_note": "N7_DISPATCH_ONLY_NOT_EXECUTION_RESULT_NOT_PASS",
        }

    def _download_bundle(self, work_item_id: str, lease_id: str) -> Tuple[bytes, Mapping[str, str]]:
        encoded = urllib.parse.quote(work_item_id, safe="")
        request = urllib.request.Request(
            self.center_url + "/api/v1/work-items/%s/execution-bundle" % encoded,
            method="GET",
            headers={
                "Accept": "application/zip",
                "X-RC8-Node-Id": self.agent.identity.node_id,
                "X-RC8-Lease-Id": lease_id,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.http_timeout_seconds) as response:
                return response.read(), {str(k): str(v) for k, v in response.headers.items()}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise N7ExecutionDispatchError("N7_BUNDLE_HTTP_%s:%s" % (exc.code, detail)) from exc
        except OSError as exc:
            raise N7ExecutionDispatchError("N7_BUNDLE_UNREACHABLE:%s" % type(exc).__name__) from exc

    @classmethod
    def _authority_from_headers(
        cls,
        headers: Mapping[str, str],
        *,
        stage_instance_id: str,
    ) -> N7DispatchAuthority:
        normalized = {str(k).lower(): str(v).strip() for k, v in headers.items()}

        def required(name: str) -> str:
            value = normalized.get(name.lower(), "")
            if not value:
                raise N7ExecutionDispatchError("N7_BUNDLE_AUTHORITY_HEADER_MISSING:%s" % name)
            return value

        header_stage = required("X-RC8-Stage-Instance-Id")
        if header_stage != stage_instance_id:
            raise N7ExecutionDispatchError("N7_BUNDLE_STAGE_AUTHORITY_MISMATCH")
        return N7DispatchAuthority(
            case_id=required("X-RC8-Case-Id"),
            prepared_attempt_id=required("X-RC8-Prepared-Attempt-Id"),
            case_execution_attempt_id=required("X-RC8-Case-Execution-Attempt-Id"),
            executable_spec_id=required("X-RC8-Executable-Spec-Id"),
            stage_instance_id=header_stage,
            mission_node_id=required("X-RC8-Mission-Node-Id"),
            sha256=required("X-RC8-SHA256"),
            project_subdir=required("X-RC8-Project-Subdir"),
        )

    @staticmethod
    def _safe_component(value: str) -> str:
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
        return digest

    @staticmethod
    def _safe_extract(bundle_path: Path, extract_root: Path) -> None:
        extract_root.mkdir(parents=True, exist_ok=False)
        root = extract_root.resolve()
        try:
            with zipfile.ZipFile(str(bundle_path), "r") as archive:
                for member in archive.infolist():
                    target = (extract_root / member.filename).resolve()
                    try:
                        target.relative_to(root)
                    except ValueError as exc:
                        raise N7ExecutionDispatchError("N7_EXECUTABLE_BUNDLE_PATH_TRAVERSAL") from exc
                archive.extractall(str(extract_root))
        except zipfile.BadZipFile as exc:
            raise N7ExecutionDispatchError("N7_EXECUTABLE_BUNDLE_ZIP_INVALID") from exc

    @staticmethod
    def _project_dir(extract_root: Path, project_subdir: str) -> Path:
        root = extract_root.resolve()
        target = (extract_root / project_subdir).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise N7ExecutionDispatchError("N7_EXECUTABLE_PROJECT_SUBDIR_INVALID") from exc
        if not target.is_dir():
            raise N7ExecutionDispatchError("N7_EXECUTABLE_PROJECT_DIR_MISSING")
        return target

    @classmethod
    def _dispatch_prompt(
        cls,
        *,
        work_item_id: str,
        lease_id: str,
        authority: N7DispatchAuthority,
        project_dir: Path,
    ) -> str:
        payload = {
            "task": "RC8_N7_EXECUTION_DISPATCH",
            "required_orchestrator": cls.REQUIRED_TEAM_TOOL,
            "constraints": [
                "DIRECTOR_MUST_NOT_EXECUTE_DOMAIN_WORK",
                "USE_DSH_AGENT_TEAMS_FOR_DOMAIN_EXECUTION",
                "DO_NOT_DECLARE_PASS",
                "DO_NOT_CHANGE_AUTHORITY_IDENTITIES",
                "DO_NOT_USE_HISTORICAL_RUNTIME_STATE",
            ],
            "authority": {
                "work_item_id": work_item_id,
                "governance_attempt_id": lease_id,
                "case_id": authority.case_id,
                "prepared_attempt_id": authority.prepared_attempt_id,
                "case_execution_attempt_id": authority.case_execution_attempt_id,
                "executable_spec_id": authority.executable_spec_id,
                "stage_instance_id": authority.stage_instance_id,
                "mission_node_id": authority.mission_node_id,
                "bundle_sha256": authority.sha256,
                "project_dir": str(project_dir),
            },
            "instruction": (
                "Invoke dsh-agent-teams now and dispatch this exact case execution to a domain worker. "
                "Do not execute domain work in Director. For this slice only acknowledge dispatch; "
                "actual execution/result/assertion/evidence publication is handled by the next controlled step. "
                "Return strict JSON with dispatch_status=ACCEPTED, case_id and executable_spec_id."
            ),
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    @classmethod
    def _require_agent_teams_dispatch(cls, result: DshJsonResult, authority: N7DispatchAuthority) -> None:
        def norm(value: str) -> str:
            return "-".join(part for part in value.strip().lower().replace("_", "-").split("-") if part)

        observed = [norm(str(call.get("tool_name") or "")) for call in result.tool_calls]
        if norm(cls.REQUIRED_TEAM_TOOL) not in observed:
            raise N7ExecutionDispatchError("N7_DSH_AGENT_TEAMS_TOOL_CALL_REQUIRED")
        output = result.output
        if str(output.get("dispatch_status") or "").upper() != "ACCEPTED":
            raise N7ExecutionDispatchError("N7_DSH_AGENT_TEAMS_DISPATCH_NOT_ACCEPTED")
        if str(output.get("case_id") or "") != authority.case_id:
            raise N7ExecutionDispatchError("N7_DSH_DISPATCH_CASE_AUTHORITY_MISMATCH")
        if str(output.get("executable_spec_id") or "") != authority.executable_spec_id:
            raise N7ExecutionDispatchError("N7_DSH_DISPATCH_SPEC_AUTHORITY_MISMATCH")
