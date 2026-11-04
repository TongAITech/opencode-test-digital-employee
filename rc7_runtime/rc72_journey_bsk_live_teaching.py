"""Live BrowserSkill-native teaching capture with strict one-operation receipts.

The B group owns BrowserSkill session/profile/browser daemon and grants the
tab/Attempt/4A binding. C09 never starts a second browser or borrows a user's
tab. Debug evidence capture MUST start before teaching actions. Each completed
human/agent operation is checkpointed immediately, through BSK cooperate sync
and a physical BSK screenshot. Multiple unobserved actions fail closed rather
than attaching the final screen to a prior click. The debug export is imported
by the canonical C09 R1 importer; no fake Field approval.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

from .models import ContractError
from .rc72_journey_bsk_import import BSKJourneyTeachingImporter
from .rc72_journey_playwright import _safe_id
from .rc72_journey_png import verify_png_file


class JourneyBSKLiveTeaching:
    def __init__(
        self, *, importer: BSKJourneyTeachingImporter,
        bsk_executable: Path, bsk_session_receipt: Mapping[str, Any],
        recording_args: Mapping[str, Any],
        runner: Optional[Callable[[Sequence[str]], Mapping[str, Any]]] = None,
        timeout_seconds: int = 45,
    ) -> None:
        if not isinstance(importer, BSKJourneyTeachingImporter):
            raise ContractError("JOURNEY_BSK_LIVE_IMPORTER_REQUIRED")
        if not isinstance(bsk_session_receipt, Mapping):
            raise ContractError("JOURNEY_BSK_LIVE_SESSION_RECEIPT_REQUIRED")
        if not isinstance(recording_args, Mapping):
            raise ContractError("JOURNEY_BSK_LIVE_RECORDING_ARGS_REQUIRED")
        if type(timeout_seconds) is not int or not 5 <= timeout_seconds <= 120:
            raise ContractError("JOURNEY_BSK_LIVE_TIMEOUT_INVALID")
        binary = Path(bsk_executable).resolve()
        if runner is None and not binary.is_file():
            raise ContractError("JOURNEY_BSK_LIVE_EXECUTABLE_MISSING")
        self.importer = importer
        self.receipt = dict(bsk_session_receipt)
        self.args = dict(recording_args)
        self.binary = binary
        self.runner = runner
        self.timeout_seconds = timeout_seconds
        self.started = False
        self.stopped = False
        self.run_id = None
        self.last_sequence = 0
        self.evidence: Dict[str, Dict[str, Any]] = {}

    def _call(self, parts: Sequence[str]) -> Dict[str, Any]:
        cmd = [str(self.binary)] + list(parts)
        if self.runner is not None:
            response = self.runner(cmd)
            if not isinstance(response, Mapping):
                raise ContractError("JOURNEY_BSK_LIVE_CLI_REPLY_INVALID")
            code, stdout = response.get("returncode"), response.get("stdout")
        else:
            env = dict(os.environ)
            env["BSK_AUTO_START"] = "0"
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, shell=False,
                    check=False, timeout=self.timeout_seconds, env=env)
            except subprocess.TimeoutExpired as exc:
                raise ContractError("JOURNEY_BSK_LIVE_COMMAND_EFFECT_UNKNOWN") from exc
            except OSError as exc:
                raise ContractError("JOURNEY_BSK_LIVE_CLI_UNAVAILABLE") from exc
            code, stdout = result.returncode, result.stdout
        if code != 0:
            raise ContractError("JOURNEY_BSK_LIVE_COMMAND_FAILED_OR_UNKNOWN")
        try:
            value = json.loads(stdout)
        except (ValueError, TypeError) as exc:
            raise ContractError("JOURNEY_BSK_LIVE_JSON_REPLY_REQUIRED") from exc
        if not isinstance(value, Mapping):
            raise ContractError("JOURNEY_BSK_LIVE_JSON_REPLY_INVALID")
        return dict(value)

    def _scope(self) -> Sequence[str]:
        owned = self.receipt
        session = owned.get("bsk_session_id")
        tab = owned.get("tab_id")
        if not isinstance(session, str) or not session:
            raise ContractError("JOURNEY_BSK_LIVE_SESSION_REQUIRED")
        if type(tab) is not int or tab <= 0:
            raise ContractError("JOURNEY_BSK_LIVE_TAB_REQUIRED")
        if owned.get("state") != "ACTIVE" or not owned.get("source_receipt_ref"):
            raise ContractError("JOURNEY_BSK_LIVE_OWNERSHIP_REQUIRED")
        # This lightweight gate runs before any CLI command. The importer
        # does the full BrowserPool/Attempt/4A lineage check before R1 commit.
        expected = {
            "mission_id": self.args.get("mission_id"),
            "workitem_id": self.args.get("workitem_id"),
            "attempt_id": self.args.get("attempt_id"),
            "worker_id": self.args.get("worker_id"),
            "dsh_session_id": self.args.get("session_id"),
            "browser_lease_id": self.args.get("browser_lease_id"),
            "auth_asset_ref": self.args.get("auth_asset_ref"),
        }
        if any(owned.get(k) != v for k, v in expected.items()):
            raise ContractError("JOURNEY_BSK_LIVE_OWNERSHIP_SCOPE_MISMATCH")
        lease = self.importer.teaching._assert_browser(self.args)
        rows = self.importer.teaching.truth.query(
            "rc72_browser_instance", browser_instance_id=lease["browser_instance_id"])
        if len(rows) != 1 or rows[0].get("state") != "READY":
            raise ContractError("JOURNEY_BSK_LIVE_BROWSER_INSTANCE_UNAVAILABLE")
        instance = rows[0]
        expected_instance = {
            "browser_instance_id": instance["browser_instance_id"],
            "profile_dir": instance["profile_dir"],
            "bsk_endpoint": instance["bsk_endpoint"],
            "auth_asset_ref": instance.get("auth_asset_ref"),
        }
        if any(owned.get(key) != value for key, value in expected_instance.items()):
            raise ContractError("JOURNEY_BSK_LIVE_BROWSER_IDENTITY_MISMATCH")
        try:
            accepted = self.importer.verify_session(owned, self.args, instance)
        except Exception as exc:
            raise ContractError("JOURNEY_BSK_LIVE_EXTERNAL_AUTHORITY_REJECTED") from exc
        if accepted is not True:
            raise ContractError("JOURNEY_BSK_LIVE_EXTERNAL_AUTHORITY_REJECTED")
        return ["--session", session, "--tab-id", str(tab)]

    def start(self, *, capture_name: str) -> str:
        if self.started or self.stopped:
            raise ContractError("JOURNEY_BSK_LIVE_ALREADY_STARTED")
        if not isinstance(capture_name, str) or not capture_name.strip():
            raise ContractError("JOURNEY_BSK_LIVE_CAPTURE_NAME_REQUIRED")
        scope = self._scope()
        result = self._call([
            "debug", "start", *scope, "--name", capture_name, "--json"])
        run = result.get("run")
        if (not isinstance(run, Mapping) or run.get("state") != "capturing"
                or not isinstance(run.get("id"), str) or not run["id"]
                or run.get("session_id") != self.receipt["bsk_session_id"]
                or run.get("tab_id") != self.receipt["tab_id"]):
            raise ContractError("JOURNEY_BSK_LIVE_CAPTURE_NOT_CONFIRMED")
        self.run_id = run["id"]
        self.started = True
        return self.run_id

    def capture_next(self, *, locator_ref: Optional[str] = None,
                     page_role: str = "BSK_PAGE",
                     value_ref: Optional[str] = None,
                     credential_ref: Optional[str] = None,
                     press_key: Optional[str] = None,
                     drag_target_ref: Optional[str] = None,
                     wait_semantics: str = "domcontentloaded") -> str:
        if not self.started or self.stopped:
            raise ContractError("JOURNEY_BSK_LIVE_NOT_CAPTURING")
        scope = self._scope()
        result = self._call([
            "debug", "operations", *scope, "--since", str(self.last_sequence),
            "--limit", "10", "--json"])
        current = result.get("run")
        if not isinstance(current, Mapping) or current.get("id") != self.run_id:
            raise ContractError("JOURNEY_BSK_LIVE_DEBUG_RUN_SWITCH")
        operations = result.get("operations")
        if not isinstance(operations, list) or len(operations) != 1:
            raise ContractError("JOURNEY_BSK_LIVE_EXACTLY_ONE_OPERATION_REQUIRED")
        op = operations[0]
        if (not isinstance(op, Mapping) or op.get("run_id") != self.run_id
                or type(op.get("sequence")) is not int
                or op["sequence"] != self.last_sequence + 1
                or op.get("state") != "completed"
                or not isinstance(op.get("id"), str) or not op["id"]):
            raise ContractError("JOURNEY_BSK_LIVE_OPERATION_NOT_STABLE")
        if op["id"] in self.evidence:
            raise ContractError("JOURNEY_BSK_LIVE_DUPLICATE_OPERATION")
        key = _safe_id(str(self.args["recording_id"]))
        folder = self.importer.capture_root / key
        folder.mkdir(parents=True, exist_ok=True)
        seq = op["sequence"]
        dom = folder / ("operation-%04d-sync.json" % seq)
        screenshot = folder / ("operation-%04d.png" % seq)
        if dom.exists() or screenshot.exists():
            raise ContractError("JOURNEY_BSK_LIVE_EVIDENCE_ALREADY_EXISTS")
        # BSK's save-full sync is an actual session-bound, immutable
        # observation with a fresh context, not an invented DOM state.
        sync = self._call([
            "cooperate", "sync", *scope, "--policy", "strict",
            "--save-full", str(dom), "--json"])
        if (sync.get("session_id") != self.receipt["bsk_session_id"]
                or sync.get("tab_id") != self.receipt["tab_id"]
                or not isinstance(sync.get("context_id"), str)
                or not sync["context_id"] or not dom.is_file()):
            raise ContractError("JOURNEY_BSK_LIVE_OBSERVATION_UNVERIFIED")
        screen = self._call([
            "screenshot", *scope, "--out", str(screenshot), "--json"])
        png = verify_png_file(screenshot)
        if screen.get("tab_id") != self.receipt["tab_id"] or screen.get("byte_size") != png["bytes"]:
            raise ContractError("JOURNEY_BSK_LIVE_SCREENSHOT_UNVERIFIED")
        # Human/browser operations can arrive while snapshot and PNG are
        # written. Re-read native debug state: a later operation must not
        # reuse the previous operation's final-page evidence.
        stable = self._call([
            "debug", "operations", *scope, "--since", str(self.last_sequence),
            "--limit", "10", "--json"])
        observed = stable.get("operations")
        if (not isinstance(stable.get("run"), Mapping)
                or stable["run"].get("id") != self.run_id
                or not isinstance(observed, list)
                or len(observed) != 1
                or observed[0].get("id") != op["id"]
                or observed[0].get("sequence") != seq
                or observed[0].get("state") != "completed"):
            raise ContractError("JOURNEY_BSK_LIVE_CONCURRENT_ACTION_EVIDENCE_UNSAFE")
        self._scope()
        binding: Dict[str, Any] = {
            "dom_ref": dom.resolve().as_uri(),
            "screenshot_ref": screenshot.resolve().as_uri(),
            "page_role": page_role,
            "wait_semantics": wait_semantics,
        }
        if locator_ref is not None:
            binding["locator_ref"] = locator_ref
        if value_ref is not None:
            binding["value_ref"] = value_ref
        if credential_ref is not None:
            binding["credential_ref"] = credential_ref
        if press_key is not None:
            binding["key"] = press_key
        if drag_target_ref is not None:
            binding["target_ref"] = drag_target_ref
        self.evidence[op["id"]] = binding
        self.last_sequence = seq
        return op["id"]

    def finish(self, *, assertions: Sequence[Mapping[str, Any]] = ()):
        if not self.started or self.stopped or not self.evidence:
            raise ContractError("JOURNEY_BSK_LIVE_NOT_READY_TO_FINISH")
        scope = self._scope()
        stopped = self._call(["debug", "stop", *scope, "--json"])
        run = stopped.get("run")
        if (not isinstance(run, Mapping) or run.get("id") != self.run_id
                or run.get("state") != "stopped"):
            raise ContractError("JOURNEY_BSK_LIVE_STOP_UNCONFIRMED")
        self.stopped = True
        export = self.importer.capture_root / _safe_id(str(self.args["recording_id"])) / "bsk-debug-export.json"
        if export.exists():
            raise ContractError("JOURNEY_BSK_LIVE_EXPORT_ALREADY_EXISTS")
        self._call(["debug", "export", *scope, "--output", str(export), "--json"])
        if not export.is_file() or export.stat().st_size == 0:
            raise ContractError("JOURNEY_BSK_LIVE_EXPORT_MISSING")
        return self.importer.import_export(
            export_file=export,
            bsk_session_id=self.receipt["bsk_session_id"],
            recording_args=self.args,
            bsk_session_receipt=self.receipt,
            evidence_map=self.evidence,
            assertions=assertions)
