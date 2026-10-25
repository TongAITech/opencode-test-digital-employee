"""RC7 DSH launcher hardening for field reality proof.

RC6/BANK_FINAL already fails closed on signed lease tool authorization. RC7
adds release-specific guarantees without modifying the frozen RC6 runtime:
verify that the RC7 MCP patch is actually composed when DSH exposes
``--dump-config``, preserve tool arguments/input/params in R1, and bind each
observed call to the corresponding DSH tool result digest so downstream gates
can prove a query actually returned rather than merely being listed/called.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from typing import Any, Dict, List, Optional, Sequence, Tuple

from rc6_runtime.agent_runtime import AgentRuntimeError
from rc6_runtime.agent_runtime_hardening import BankFinalDshHeadlessWorkerLauncher


_ARGUMENT_KEYS = {"arguments", "args", "input", "parameters", "params"}
_RESULT_KEYS = {"result", "output", "content", "data", "value", "response"}


class RC7BankFinalDshHeadlessWorkerLauncher(BankFinalDshHeadlessWorkerLauncher):
    """BANK_FINAL authority plus RC7 composition and argument/result proof."""

    def _preflight_headless_composition(self, mission_id: str) -> None:
        if not self._dsh_available():
            self._emit_routing_fail(mission_id, "DSH_NOT_AVAILABLE")
            raise AgentRuntimeError("ROUTING_INTEGRITY_FAIL:DSH_NOT_AVAILABLE")

        run_env = os.environ.copy()
        run_env.update(self.env)
        probe_timeout = max(1, min(self.timeout_seconds, 30))
        try:
            help_proc = self.command_runner(
                [self.dsh_bin, "--help"],
                cwd=self.cwd,
                env=run_env,
                capture_output=True,
                text=True,
                timeout=probe_timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self._emit_routing_fail(mission_id, "DSH_CAPABILITY_PROBE_FAILED:%s" % type(exc).__name__)
            raise AgentRuntimeError("ROUTING_INTEGRITY_FAIL:DSH_CAPABILITY_PROBE_FAILED") from exc
        if int(help_proc.returncode) != 0:
            self._emit_routing_fail(mission_id, "DSH_CAPABILITY_PROBE_NONZERO")
            raise AgentRuntimeError("ROUTING_INTEGRITY_FAIL:DSH_CAPABILITY_PROBE_NONZERO")

        help_text = (help_proc.stdout or "") + "\n" + (help_proc.stderr or "")
        if "--dump-config" not in help_text:
            return
        try:
            dump_proc = self.command_runner(
                [
                    self.dsh_bin,
                    "--profile", "headless",
                    "--patch", self.patch_path,
                    "--dump-config",
                ],
                cwd=self.cwd,
                env=run_env,
                capture_output=True,
                text=True,
                timeout=probe_timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self._emit_routing_fail(mission_id, "DSH_COMPOSITION_PREFLIGHT_FAILED:%s" % type(exc).__name__)
            raise AgentRuntimeError("ROUTING_INTEGRITY_FAIL:DSH_COMPOSITION_PREFLIGHT_FAILED") from exc
        if int(dump_proc.returncode) != 0:
            self._emit_routing_fail(mission_id, "DSH_COMPOSITION_PREFLIGHT_NONZERO")
            raise AgentRuntimeError("ROUTING_INTEGRITY_FAIL:DSH_COMPOSITION_PREFLIGHT_NONZERO")

        dump_text = (dump_proc.stdout or "") + "\n" + (dump_proc.stderr or "")
        if "pfc_aitest_rc7" not in dump_text and "mcp-pfc-aitest-rc7" not in dump_text:
            self._emit_routing_fail(mission_id, "DSH_RC7_MCP_PATCH_NOT_COMPOSED")
            raise AgentRuntimeError("ROUTING_INTEGRITY_FAIL:DSH_RC7_MCP_PATCH_NOT_COMPOSED")

    @classmethod
    def _tool_calls(cls, events: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        calls = super()._tool_calls(events)
        enriched: List[Dict[str, Any]] = []
        for call in calls:
            row = dict(call)
            event = cls._event_for_call_ref(events, str(call.get("call_ref") or ""))
            arguments = cls._extract_arguments(event) if event is not None else None
            if arguments is not None:
                row["arguments"] = arguments
            result = cls._result_for_call(events, str(call.get("call_ref") or ""), str(call.get("tool_name") or ""))
            if result is not None:
                result_index, result_event = result
                row["result_ref"] = "dsh-event://tool-result/%d" % result_index
                row["result_sha256"] = cls._event_hash(result_event)
                row["result_status"] = cls._result_status(result_event)
            enriched.append(row)
        return enriched

    @staticmethod
    def _event_for_call_ref(
        events: Sequence[Dict[str, Any]],
        call_ref: str,
    ) -> Optional[Dict[str, Any]]:
        prefix = "dsh-event://tool-call/"
        if not call_ref.startswith(prefix):
            return None
        try:
            index = int(call_ref[len(prefix):])
        except (TypeError, ValueError):
            return None
        if index < 0 or index >= len(events):
            return None
        event = events[index]
        return event if isinstance(event, dict) else None

    @classmethod
    def _result_for_call(
        cls,
        events: Sequence[Dict[str, Any]],
        call_ref: str,
        tool_name: str,
    ) -> Optional[Tuple[int, Dict[str, Any]]]:
        prefix = "dsh-event://tool-call/"
        if not call_ref.startswith(prefix):
            return None
        try:
            call_index = int(call_ref[len(prefix):])
        except (TypeError, ValueError):
            return None
        wanted = str(tool_name or "").strip().lower()
        for index in range(call_index + 1, len(events)):
            event = events[index]
            if not isinstance(event, dict):
                continue
            kind = str(event.get("type") or event.get("event") or event.get("kind") or "").lower()
            if "tool_call" in kind or "toolcall" in kind:
                break
            if "tool_result" not in kind and "toolresult" not in kind and not ("tool" in kind and "result" in kind):
                continue
            observed = cls._extract_tool_name(event).lower()
            if wanted and observed and observed != wanted:
                continue
            return index, event
        return None

    @classmethod
    def _extract_tool_name(cls, value: Any) -> str:
        if isinstance(value, dict):
            for key in ("tool_name", "toolName", "tool", "name"):
                child = value.get(key)
                if isinstance(child, str) and child.strip():
                    return child.strip()
                if isinstance(child, dict):
                    nested = cls._extract_tool_name(child)
                    if nested:
                        return nested
            for child in value.values():
                nested = cls._extract_tool_name(child)
                if nested:
                    return nested
        elif isinstance(value, list):
            for child in value:
                nested = cls._extract_tool_name(child)
                if nested:
                    return nested
        return ""

    @staticmethod
    def _event_hash(event: Dict[str, Any]) -> str:
        raw = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return "sha256:" + hashlib.sha256(raw).hexdigest()

    @classmethod
    def _result_status(cls, event: Dict[str, Any]) -> str:
        if event.get("ok") is False or event.get("success") is False:
            return "FAIL"
        if event.get("error") not in (None, "", False, [], {}):
            return "FAIL"
        status = event.get("status")
        if isinstance(status, str) and status.strip().upper() in {"FAIL", "FAILED", "ERROR", "BLOCKED"}:
            return "FAIL"
        # Presence of a real DSH tool-result event is the receipt. Its payload is
        # hashed above; no semantic success claim from the Worker is consulted.
        return "SUCCESS"

    @classmethod
    def _extract_arguments(cls, value: Any) -> Optional[Any]:
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in _ARGUMENT_KEYS and child is not None:
                    return cls._normalize_arguments(child)
            for child in value.values():
                nested = cls._extract_arguments(child)
                if nested is not None:
                    return nested
        elif isinstance(value, list):
            for child in value:
                nested = cls._extract_arguments(child)
                if nested is not None:
                    return nested
        return None

    @staticmethod
    def _normalize_arguments(value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped and stripped[:1] in {"{", "["}:
                try:
                    parsed = json.loads(stripped)
                except json.JSONDecodeError:
                    return value
                if isinstance(parsed, (dict, list)):
                    return parsed
        return value
