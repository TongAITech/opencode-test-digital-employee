"""RC7 DSH launcher hardening for field reality proof.

RC6/BANK_FINAL already fails closed on signed lease tool authorization. RC7
adds two release-specific guarantees without modifying the frozen RC6 runtime:
verify that the RC7 MCP patch is actually composed when DSH exposes
``--dump-config``, and preserve tool arguments/input/params in R1 so field
qualification can prove the exact target/query that was executed.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Dict, List, Optional, Sequence

from rc6_runtime.agent_runtime import AgentRuntimeError
from rc6_runtime.agent_runtime_hardening import BankFinalDshHeadlessWorkerLauncher


_ARGUMENT_KEYS = {"arguments", "args", "input", "parameters", "params"}


class RC7BankFinalDshHeadlessWorkerLauncher(BankFinalDshHeadlessWorkerLauncher):
    """BANK_FINAL authority plus RC7 composition and argument-level proof."""

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
