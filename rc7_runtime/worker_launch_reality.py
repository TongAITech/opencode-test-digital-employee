"""RC7.1 diagnostics for fail-closed DSH Worker launch timeouts.

The RC7 base launcher already fails closed on TimeoutExpired. The field gap is
that timeout happens before the normal raw-output persistence point, so partial
DSH stdout/stderr and a session id already emitted by DSH can be lost. This
module adds evidence capture without changing authorization, retry, or PASS
semantics, and redacts the prompt from TimeoutExpired command text before the
base launcher records the failure in R1.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from rc6_runtime import agent_runtime as _agent_runtime
from rc6_runtime.agent_runtime import AgentRuntimeError, WorkerAssignment


def _process_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _redacted_timeout(cause: subprocess.TimeoutExpired) -> subprocess.TimeoutExpired:
    """Return an equivalent timeout whose string form cannot expose the prompt."""
    command = getattr(cause, "cmd", None)
    if isinstance(command, (list, tuple)):
        redacted_command = []
        redact_next = False
        for part in command:
            text = str(part)
            if redact_next:
                redacted_command.append("<PROMPT_REDACTED>")
                redact_next = False
                continue
            redacted_command.append(text)
            if text == "--json":
                redact_next = True
    else:
        redacted_command = "<DSH_COMMAND_REDACTED>"
    clean = subprocess.TimeoutExpired(
        cmd=redacted_command,
        timeout=getattr(cause, "timeout", None),
        output=getattr(cause, "output", None),
        stderr=getattr(cause, "stderr", None),
    )
    return clean


def _persist_timeout_diagnostic(
    launcher: Any,
    assignment: WorkerAssignment,
    prompt: str,
    cause: subprocess.TimeoutExpired,
    stdout: str,
    stderr: str,
    raw_ref: str,
    partial_session_id: str,
) -> str:
    folder = Path(launcher.state_root) / "worker-evidence" / assignment.mission_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (assignment.assignment_id + ".launch-timeout.json")
    payload = {
        "schema": "rc7.1-dsh-worker-timeout-v1",
        "mission_id": assignment.mission_id,
        "attempt_id": assignment.attempt_id,
        "assignment_id": assignment.assignment_id,
        "worker_instance_id": assignment.worker_instance_id,
        "agent_id": assignment.agent_id,
        "dsh_bin": str(launcher.dsh_bin),
        "patch_path": str(launcher.patch_path),
        "cwd": str(launcher.cwd),
        "timeout_seconds": int(launcher.timeout_seconds),
        "captured_at": int(time.time()),
        "failure_type": "TimeoutExpired",
        "failure": str(cause),
        "partial_stdout_present": bool(stdout),
        "partial_stderr_present": bool(stderr),
        "partial_raw_output_ref": raw_ref,
        "partial_dsh_session_id": partial_session_id or None,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8", errors="replace")).hexdigest(),
        "prompt_persisted": False,
        "retry_authorized": False,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return "file://" + path.as_posix()


def install_rc7_1_worker_timeout_diagnostics() -> None:
    """Patch the existing launcher at the timeout/evidence boundary only."""

    current = _agent_runtime.DshHeadlessWorkerLauncher.execute
    if getattr(current, "_rc71_timeout_diagnostics", False):
        return

    original = current

    def execute_with_timeout_diagnostics(self, assignment, prompt):
        # The base launcher formats TimeoutExpired into R1 before re-raising it.
        # Wrap only the process runner so its exception is already redacted when
        # that happens; preserve partial stdout/stderr for post-failure evidence.
        original_runner = self.command_runner

        def redacting_runner(*args, **kwargs):
            try:
                return original_runner(*args, **kwargs)
            except subprocess.TimeoutExpired as cause:
                raise _redacted_timeout(cause)

        self.command_runner = redacting_runner
        try:
            try:
                return original(self, assignment, prompt)
            except AgentRuntimeError as exc:
                cause = exc.__cause__
                if not isinstance(cause, subprocess.TimeoutExpired):
                    raise

                stdout = _process_text(getattr(cause, "stdout", None) or getattr(cause, "output", None))
                stderr = _process_text(getattr(cause, "stderr", None))
                raw_ref = self._persist_raw_worker_output(assignment, stdout, stderr)
                events = tuple(self._parse_json_lines(stdout))
                session_id = self._session_id(events)
                diagnostic_ref = _persist_timeout_diagnostic(
                    self,
                    assignment,
                    prompt,
                    cause,
                    stdout,
                    stderr,
                    raw_ref,
                    session_id,
                )
                self.emit_control_event(
                    "ROUTING_INTEGRITY_FAIL",
                    assignment.mission_id,
                    reason="DSH_LAUNCH_TIMEOUT_DIAGNOSTIC",
                    assignment_id=assignment.assignment_id,
                    worker_instance_id=assignment.worker_instance_id,
                    attempt_id=assignment.attempt_id,
                    partial_raw_output_ref=raw_ref,
                    diagnostic_ref=diagnostic_ref,
                    partial_dsh_session_id=session_id or None,
                    retry_authorized=False,
                )
                raise
        finally:
            self.command_runner = original_runner

    execute_with_timeout_diagnostics._rc71_timeout_diagnostics = True
    _agent_runtime.DshHeadlessWorkerLauncher.execute = execute_with_timeout_diagnostics
