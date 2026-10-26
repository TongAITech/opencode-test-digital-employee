"""Formal Center wrapper that makes N7 execution authority non-bypassable.

N7 is authorized before Center starts the WorkItem and again before every
runtime write. A runtime mutation may enter while the current authority is
still valid and can then invalidate N5/N6 through canonical R1. Any later write
from the stale N7 execution is rejected before it can claim completion or PASS.
"""
from __future__ import annotations

from typing import Any

from .execution_admission import CenterN7ExecutionAdmissionGate


class N7AdmissionAwareFormalCenterControlPlane:
    """Re-authorize N7 at start and at every runtime write boundary."""

    def __init__(self, control_plane: object, execution_admission: CenterN7ExecutionAdmissionGate) -> None:
        self._control_plane = control_plane
        self.execution_admission = execution_admission

    def __getattr__(self, name: str) -> Any:
        return getattr(self._control_plane, name)

    def _authorize_current_execution(self, work_item_id: str, node_id: str, lease_id: str):
        # RuntimeMutationAwareFormalCenterControlPlane delegates this private
        # authority check to the real FormalCenterControlPlane via __getattr__.
        work = self._control_plane._require_active_lease(work_item_id, node_id, lease_id)
        stage_instance_id = self._control_plane.stage_instance_id_for_work_item(work_item_id)
        self.execution_admission.authorize_start(
            work=work,
            stage_instance_id=stage_instance_id,
        )
        return work

    def start_work_item(self, work_item_id: str, node_id: str, lease_id: str):
        self._authorize_current_execution(work_item_id, node_id, lease_id)
        # Only after deterministic admission may the wrapped plane create the
        # Center-owned ATTEMPT_STARTED event and transition the WorkItem RUNNING.
        return self._control_plane.start_work_item(work_item_id, node_id, lease_id)

    def append_runtime_event(self, event: object, *, lease_id: str):
        # Admission at start is insufficient: auth/data/environment/route/
        # reality/case revision may change while N7 is already RUNNING. Recheck
        # before every runtime write so an invalidated execution cannot emit
        # stale steps, evidence or a terminal ATTEMPT_COMPLETED claim.
        self._authorize_current_execution(
            str(getattr(event, "work_item_id", "")),
            str(getattr(event, "node_id", "")),
            lease_id,
        )
        return self._control_plane.append_runtime_event(event, lease_id=lease_id)
