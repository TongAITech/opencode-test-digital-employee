from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.durable_core import CommandResult

from .contracts import R15Error, contains_sensitive_value
from .diagnostics import DiagnosticReport, diagnose_failure
from .health import HealthReport, assess_health
from .launch import RuntimeLaunch
from .projections import ProjectionEnvelope, mission_projection


class ControlPlane:
    def __init__(self, launch: RuntimeLaunch) -> None:
        launch.startup.require_valid()
        self._launch = launch

    @property
    def launch(self) -> RuntimeLaunch:
        return self._launch

    def submit_command(self, command: Mapping[str, Any]) -> CommandResult:
        if not isinstance(command, Mapping):
            raise R15Error("COMMAND_SCHEMA_INVALID", "Control Plane command must be an object")
        if contains_sensitive_value(command):
            raise R15Error("COMMAND_SECRET_FORBIDDEN", "secrets may not enter commands or events")
        if command.get("schema_version", 1) != self._launch.startup.configuration.versions.command_schema:
            raise R15Error("COMMAND_SCHEMA_INCOMPATIBLE", "command schema version is unsupported")
        return self._launch.runtime.execute(dict(command))

    coordinate = submit_command

    def health(self, mission_id: str | None = None) -> HealthReport:
        return assess_health(self._launch.runtime, self._launch.startup.report, mission_id=mission_id)

    def projection(self, mission_id: str) -> ProjectionEnvelope:
        return mission_projection(self._launch.runtime, mission_id)

    def diagnostics(
        self,
        error: Exception,
        *,
        correlation_id: str,
        evidence: Mapping[str, Any] | None = None,
    ) -> DiagnosticReport:
        return diagnose_failure(error, correlation_id=correlation_id, evidence=evidence)
