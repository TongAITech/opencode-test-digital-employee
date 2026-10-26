"""Formal Center wrapper that makes N7 admission non-bypassable at WorkItem start."""
from __future__ import annotations

from typing import Any

from .execution_admission import CenterN7ExecutionAdmissionGate


class N7AdmissionAwareFormalCenterControlPlane:
    """Authorize N7 before the wrapped Center emits governance ATTEMPT_STARTED."""

    def __init__(self, control_plane: object, execution_admission: CenterN7ExecutionAdmissionGate) -> None:
        self._control_plane = control_plane
        self.execution_admission = execution_admission

    def __getattr__(self, name: str) -> Any:
        return getattr(self._control_plane, name)

    def start_work_item(self, work_item_id: str, node_id: str, lease_id: str):
        # RuntimeMutationAwareFormalCenterControlPlane delegates this private
        # authority check to the real FormalCenterControlPlane via __getattr__.
        work = self._control_plane._require_active_lease(work_item_id, node_id, lease_id)
        stage_instance_id = self._control_plane.stage_instance_id_for_work_item(work_item_id)
        self.execution_admission.authorize_start(
            work=work,
            stage_instance_id=stage_instance_id,
        )
        # Only after deterministic admission may the wrapped plane create the
        # Center-owned ATTEMPT_STARTED event and transition the WorkItem RUNNING.
        return self._control_plane.start_work_item(work_item_id, node_id, lease_id)
