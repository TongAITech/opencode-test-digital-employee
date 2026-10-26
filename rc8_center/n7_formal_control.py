"""Formal Center wrapper that makes N7 execution authority non-bypassable.

N7 is authorized before Center starts the WorkItem and again before every
runtime write. A runtime mutation may enter while the current authority is
still valid and can then invalidate N5/N6 through canonical R1. Any later write
from the stale N7 execution is rejected before it can claim completion or PASS.

Worker runtime payloads are observations, not authority. For N7, case identity
and both Attempt identities are derived by Center admission and then enforced at
every write boundary. A worker holding case A's lease cannot write or invalidate
case B by forging case_id/attempt_id in a runtime event.
"""
from __future__ import annotations

from typing import Any

from .execution_admission import (
    CenterN7ExecutionAdmissionGate,
    N7ExecutionAdmission,
    N7ExecutionAdmissionError,
)


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
        admission = self.execution_admission.authorize_start(
            work=work,
            stage_instance_id=stage_instance_id,
        )
        return work, admission

    @staticmethod
    def _validate_runtime_event_identity(
        event: object,
        admission: N7ExecutionAdmission,
        *,
        lease_id: str,
    ) -> None:
        if str(getattr(event, "test_run_id", "") or "") != admission.test_run_id:
            raise N7ExecutionAdmissionError("N7_RUNTIME_EVENT_TEST_RUN_AUTHORITY_MISMATCH")
        if str(getattr(event, "work_item_id", "") or "") != admission.work_item_id:
            raise N7ExecutionAdmissionError("N7_RUNTIME_EVENT_WORK_ITEM_AUTHORITY_MISMATCH")
        if str(getattr(event, "case_id", "") or "") != admission.case_id:
            raise N7ExecutionAdmissionError("N7_RUNTIME_EVENT_CASE_AUTHORITY_MISMATCH")

        event_type = str(getattr(event, "event_type", "") or "").strip().upper()
        supplied_attempt_id = str(getattr(event, "attempt_id", "") or "").strip()
        # Governance ATTEMPT_* events belong to the Center-started N7 lease
        # Attempt. Domain execution/tool events belong to the N5/N6 case
        # execution Attempt. The worker may report facts for the appropriate
        # identity but may not choose a different identity.
        expected_attempt_id = str(lease_id) if event_type.startswith("ATTEMPT_") else admission.case_execution_attempt_id
        if supplied_attempt_id != expected_attempt_id:
            raise N7ExecutionAdmissionError("N7_RUNTIME_EVENT_ATTEMPT_AUTHORITY_MISMATCH")

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
        _, admission = self._authorize_current_execution(
            str(getattr(event, "work_item_id", "")),
            str(getattr(event, "node_id", "")),
            lease_id,
        )
        if admission is not None:
            self._validate_runtime_event_identity(event, admission, lease_id=lease_id)
        return self._control_plane.append_runtime_event(event, lease_id=lease_id)
