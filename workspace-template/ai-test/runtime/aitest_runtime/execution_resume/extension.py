from __future__ import annotations

from aitest_runtime.durable_core import ExtensionManifest, canonical_sha256

from .contracts import EXTENSION_ID, EXTENSION_VERSION, ExecutionResumeState
from .handlers import COMMAND_TYPES, EVENT_TYPES, ExecutionResumeCommandContribution
from .projections import ExecutionResumeMigrationContribution, ExecutionResumeProjectionContribution
from .reducer import ExecutionResumeReducerContribution


class ExecutionResumeStateContribution:
    def initial_state(self, mission_id: str) -> ExecutionResumeState:
        return ExecutionResumeState(mission_id=mission_id)

    def encode(self, state: ExecutionResumeState) -> dict:
        return state.to_dict()

    def decode(self, value: dict) -> ExecutionResumeState:
        return ExecutionResumeState.from_dict(value)

    def hash(self, state: ExecutionResumeState) -> str:
        return canonical_sha256(self.encode(state))


def execution_resume_extension() -> ExtensionManifest:
    return ExtensionManifest(
        extension_id=EXTENSION_ID,
        extension_version=EXTENSION_VERSION,
        command_types=COMMAND_TYPES,
        event_types=EVENT_TYPES,
        state_contribution=ExecutionResumeStateContribution(),
        command_contribution=ExecutionResumeCommandContribution(),
        reducer_contribution=ExecutionResumeReducerContribution(),
        projection_contribution=ExecutionResumeProjectionContribution(),
        migration_contribution=ExecutionResumeMigrationContribution(),
    )
