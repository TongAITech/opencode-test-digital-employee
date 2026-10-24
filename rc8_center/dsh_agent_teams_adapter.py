"""Local dsh-node process adapter for the dsh-agent-teams gateway.

This is the concrete node-side transport for :class:`DshAgentTeamsGateway`.
It deliberately stays out of Center: Center has no AI dependency, while this
adapter is constructed only inside an AI-capable dsh-node runtime.

The adapter is capability/configuration driven.  It does not pin a DSH or
agent-teams version and it never uses ``shell=True``.  Windows may launch a
bridge through the configured Git Bash executable; Linux launches the same
bridge through system ``bash``.  A bank deployment must point the bridge at the
observed in-bank dsh-agent-teams integration surface and pass reality tests
before BANK_REALITY_VERIFIED can become true.
"""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple

from .node_team_runtime import DshAgentTeamsGateway


class DshAgentTeamsAdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class DshAgentTeamsProcessConfig:
    command: Tuple[str, ...]
    timeout_seconds: float = 120.0
    working_directory: Optional[str] = None
    extra_env: Optional[Dict[str, str]] = None

    def __post_init__(self) -> None:
        if not isinstance(self.command, (tuple, list)) or not self.command:
            raise DshAgentTeamsAdapterError("DSH_AGENT_TEAMS_COMMAND_REQUIRED")
        normalized = []
        for token in self.command:
            if not isinstance(token, str) or not token.strip():
                raise DshAgentTeamsAdapterError("DSH_AGENT_TEAMS_COMMAND_TOKEN_INVALID")
            normalized.append(token.strip())
        object.__setattr__(self, "command", tuple(normalized))
        if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float)):
            raise DshAgentTeamsAdapterError("DSH_AGENT_TEAMS_TIMEOUT_INVALID")
        if self.timeout_seconds <= 0:
            raise DshAgentTeamsAdapterError("DSH_AGENT_TEAMS_TIMEOUT_INVALID")
        if self.working_directory is not None:
            if not isinstance(self.working_directory, str) or not self.working_directory.strip():
                raise DshAgentTeamsAdapterError("DSH_AGENT_TEAMS_WORKDIR_INVALID")
            object.__setattr__(self, "working_directory", self.working_directory.strip())
        if self.extra_env is not None:
            if not isinstance(self.extra_env, dict):
                raise DshAgentTeamsAdapterError("DSH_AGENT_TEAMS_ENV_INVALID")
            normalized_env = {}
            for key, value in self.extra_env.items():
                if not isinstance(key, str) or not key.strip() or not isinstance(value, str):
                    raise DshAgentTeamsAdapterError("DSH_AGENT_TEAMS_ENV_INVALID")
                normalized_env[key.strip()] = value
            object.__setattr__(self, "extra_env", normalized_env)

    @classmethod
    def for_shell_bridge(
        cls,
        *,
        os_family: str,
        bridge_script: str,
        git_bash_executable: Optional[str] = None,
        timeout_seconds: float = 120.0,
        working_directory: Optional[str] = None,
        extra_env: Optional[Dict[str, str]] = None,
    ) -> "DshAgentTeamsProcessConfig":
        family = (os_family or "").strip().lower()
        bridge = (bridge_script or "").strip()
        if not bridge:
            raise DshAgentTeamsAdapterError("DSH_AGENT_TEAMS_BRIDGE_SCRIPT_REQUIRED")
        if family == "windows":
            bash = (git_bash_executable or "").strip()
            if not bash:
                raise DshAgentTeamsAdapterError("WINDOWS_DSH_NODE_REQUIRES_GIT_BASH")
        elif family == "linux":
            bash = "bash"
        else:
            raise DshAgentTeamsAdapterError("DSH_NODE_OS_UNSUPPORTED")
        return cls(
            command=(bash, bridge),
            timeout_seconds=timeout_seconds,
            working_directory=working_directory,
            extra_env=extra_env,
        )


class LocalProcessDshAgentTeamsGateway(DshAgentTeamsGateway):
    """Synchronous JSON RPC bridge executed locally by a dsh-node.

    Each gateway operation starts the configured bridge process, sends one JSON
    request on stdin and requires one JSON response on stdout.  The final
    non-empty stdout line must be a response object using contract
    ``rc8.dsh-agent-teams.v1``.  Logs may precede that final line.
    """

    CONTRACT_VERSION = "rc8.dsh-agent-teams.v1"

    def __init__(self, config: DshAgentTeamsProcessConfig) -> None:
        if not isinstance(config, DshAgentTeamsProcessConfig):
            raise DshAgentTeamsAdapterError("DSH_AGENT_TEAMS_PROCESS_CONFIG_REQUIRED")
        self.config = config

    def start_team(
        self,
        *,
        profile_id: str,
        member_roles: Sequence[str],
        context: Dict[str, object]
    ) -> str:
        result = self._invoke(
            "start_team",
            {
                "profile_id": self._required(profile_id, "profile_id"),
                "member_roles": list(member_roles),
                "context": dict(context),
            },
        )
        return self._result_id(result, "team_id")

    def dispatch_member(self, *, team_id: str, role: str, context: Dict[str, object]) -> str:
        result = self._invoke(
            "dispatch_member",
            {
                "team_id": self._required(team_id, "team_id"),
                "role": self._required(role, "role"),
                "context": dict(context),
            },
        )
        return self._result_id(result, "agent_id")

    def start_tool(
        self,
        *,
        team_id: str,
        agent_id: str,
        tool_id: str,
        action: str,
        payload: Dict[str, object]
    ) -> str:
        result = self._invoke(
            "start_tool",
            {
                "team_id": self._required(team_id, "team_id"),
                "agent_id": self._required(agent_id, "agent_id"),
                "tool_id": self._required(tool_id, "tool_id"),
                "action": self._required(action, "action"),
                "payload": dict(payload),
            },
        )
        return self._result_id(result, "invocation_id")

    def complete_team(self, *, team_id: str) -> None:
        self._invoke("complete_team", {"team_id": self._required(team_id, "team_id")})

    def abort_team(self, *, team_id: str, reason: str) -> None:
        self._invoke(
            "abort_team",
            {
                "team_id": self._required(team_id, "team_id"),
                "reason": self._required(reason, "reason"),
            },
        )

    @staticmethod
    def _required(value: str, name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise DshAgentTeamsAdapterError("%s_REQUIRED" % name.upper())
        return value.strip()

    @staticmethod
    def _result_id(result: Dict[str, object], name: str) -> str:
        value = result.get(name)
        if not isinstance(value, str) or not value.strip():
            raise DshAgentTeamsAdapterError("DSH_AGENT_TEAMS_RESULT_FIELD_REQUIRED:%s" % name)
        return value.strip()

    def _invoke(self, operation: str, payload: Dict[str, object]) -> Dict[str, object]:
        request_id = str(uuid.uuid4())
        request = {
            "contract": self.CONTRACT_VERSION,
            "request_id": request_id,
            "operation": operation,
            "payload": payload,
        }
        env = os.environ.copy()
        if self.config.extra_env:
            env.update(self.config.extra_env)
        try:
            completed = subprocess.run(
                list(self.config.command),
                input=json.dumps(request, ensure_ascii=False) + "\n",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                cwd=self.config.working_directory,
                env=env,
                timeout=self.config.timeout_seconds,
                shell=False,
            )
        except FileNotFoundError as exc:
            raise DshAgentTeamsAdapterError("DSH_AGENT_TEAMS_COMMAND_NOT_FOUND") from exc
        except subprocess.TimeoutExpired as exc:
            raise DshAgentTeamsAdapterError("DSH_AGENT_TEAMS_TIMEOUT") from exc
        except OSError as exc:
            raise DshAgentTeamsAdapterError("DSH_AGENT_TEAMS_PROCESS_START_FAILED") from exc

        if completed.returncode != 0:
            raise DshAgentTeamsAdapterError(
                "DSH_AGENT_TEAMS_EXIT_NONZERO:%s" % completed.returncode
            )
        lines = [line.strip() for line in (completed.stdout or "").splitlines() if line.strip()]
        if not lines:
            raise DshAgentTeamsAdapterError("DSH_AGENT_TEAMS_EMPTY_RESPONSE")
        try:
            response = json.loads(lines[-1])
        except ValueError as exc:
            raise DshAgentTeamsAdapterError("DSH_AGENT_TEAMS_INVALID_JSON") from exc
        if not isinstance(response, dict):
            raise DshAgentTeamsAdapterError("DSH_AGENT_TEAMS_RESPONSE_OBJECT_REQUIRED")
        if response.get("contract") != self.CONTRACT_VERSION:
            raise DshAgentTeamsAdapterError("DSH_AGENT_TEAMS_CONTRACT_MISMATCH")
        if response.get("request_id") != request_id:
            raise DshAgentTeamsAdapterError("DSH_AGENT_TEAMS_REQUEST_ID_MISMATCH")
        if response.get("ok") is not True:
            error = response.get("error")
            if not isinstance(error, str) or not error.strip():
                error = "UNKNOWN"
            raise DshAgentTeamsAdapterError("DSH_AGENT_TEAMS_REJECTED:%s" % error.strip())
        result = response.get("result", {})
        if not isinstance(result, dict):
            raise DshAgentTeamsAdapterError("DSH_AGENT_TEAMS_RESULT_OBJECT_REQUIRED")
        return result
