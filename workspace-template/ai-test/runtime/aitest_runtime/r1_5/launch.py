from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from aitest_runtime.durable_core import RuntimeService, canonical_sha256
from aitest_runtime.execution_resume import execution_resume_extension
from aitest_runtime.opencode_bridge import opencode_bridge_extension
from aitest_runtime.provider_binding import provider_binding_extension
from aitest_runtime.tool_execution import tool_execution_extension
from aitest_runtime.work_graph import work_graph_extension

from .contracts import LaunchReceipt, R15Error, VersionContract, utc_now
from .validate import ValidatedStartup


RuntimeFactory = Callable[[Path], RuntimeService]


def existing_runtime(db_path: Path) -> RuntimeService:
    return RuntimeService(
        db_path,
        extensions=(
            work_graph_extension(),
            execution_resume_extension(),
            provider_binding_extension(),
            opencode_bridge_extension(),
            tool_execution_extension(),
        ),
    )


@dataclass(frozen=True)
class RuntimeLaunch:
    runtime: RuntimeService
    startup: ValidatedStartup
    receipt: LaunchReceipt

    def to_dict(self) -> dict[str, object]:
        return self.receipt.to_dict()


def launch_runtime(startup: ValidatedStartup, *, runtime_factory: RuntimeFactory | None = None) -> RuntimeLaunch:
    startup.require_valid()
    configuration = startup.configuration
    if configuration.identity["artifact_digest"] != startup.artifact.manifest_digest:
        raise R15Error("LAUNCH_PROVENANCE_MISMATCH", "launch artifact is not the validated artifact")
    db_path = Path(str(configuration.runtime["db_path"])).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    runtime = (runtime_factory or existing_runtime)(db_path)
    versions = configuration.versions
    launch_id = canonical_sha256(
        {
            "runtime_id": configuration.runtime["runtime_id"],
            "artifact_digest": startup.artifact.manifest_digest,
            "configuration_digest": configuration.digest,
            "validation_digest": startup.report.digest,
            "versions": versions.to_dict(),
        }
    )
    receipt = LaunchReceipt(
        launch_id=launch_id,
        runtime_id=str(configuration.runtime["runtime_id"]),
        runtime_db_path=str(db_path),
        artifact_digest=startup.artifact.manifest_digest,
        configuration_digest=configuration.digest,
        validation_digest=startup.report.digest,
        launched_at=utc_now(),
        versions=VersionContract.from_mapping(versions.to_dict()),
    )
    return RuntimeLaunch(runtime, startup, receipt)
