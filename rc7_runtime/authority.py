"""RC7 additive worker authority roles.

RC6 AuthorityRuntime remains frozen and unchanged. RC7 extends it through a
subclass with explicit candidate-output roles for the control-plane nodes. No
professional role receives acceptance authority; Evaluations remain separate
R1 truth owned by independent evaluators.

RC7.2 additionally adds fail-closed revocation/readback for runtime-issued
TaskLease objects.  This keeps dynamic capability escalation on the existing
HMAC-signed lease path instead of inventing a second authorization mechanism.
"""

from __future__ import annotations

from typing import Dict, Set

from rc6_runtime.authority import AuthorityError, AuthorityRuntime, TaskLease, WorkerIdentity


class RC7AuthorityRuntime(AuthorityRuntime):
    """Fail-closed authority with RC7 professional worker roles."""

    _ROLE_ARTIFACTS: Dict[str, Set[str]] = {
        **{role: set(values) for role, values in AuthorityRuntime._ROLE_ARTIFACTS.items()},
        "RC7_REALITY_WORKER": {"rc7_reality_candidate"},
        "RC7_REQUIREMENT_WORKER": {"rc7_requirement_candidate"},
        "RC7_CODE_WORKER": {"rc7_code_candidate"},
        "RC7_TEST_DESIGN_WORKER": {"rc7_test_design_candidate"},
        "RC7_TEST_DESIGN_REVIEWER": {"rc7_test_design_review", "analysis_gap"},
        "RC7_SCRIPT_WORKER": {"rc7_script_candidate"},
        "RC7_PREPARATION_WORKER": {"rc7_preparation_candidate"},
        "RC7_EXECUTION_WORKER": {"rc7_execution_candidate"},
        "RC7_REPORT_WORKER": {"rc7_report_candidate"},
        "RC7_DEFECT_WORKER": {"rc7_defect_candidate"},
        "RC7_RUNTIME_RECOVERY_WORKER": {"rc7_runtime_candidate"},
    }

    def __init__(self, signing_key: bytes):
        super().__init__(signing_key)
        self._revoked_lease_ids: Set[str] = set()

    def get_lease(self, lease_id: str) -> TaskLease:
        """Return runtime-issued lease metadata without exposing the signing key."""
        return self._require_lease(lease_id)

    def get_identity(self, worker_id: str) -> WorkerIdentity:
        return self._require_identity(worker_id)

    def revoke_lease(self, lease_id: str) -> None:
        self._require_lease(lease_id)
        self._revoked_lease_ids.add(lease_id)

    def is_lease_revoked(self, lease_id: str) -> bool:
        return lease_id in self._revoked_lease_ids

    def _validate_lease(self, identity: WorkerIdentity, lease: TaskLease, now):
        super()._validate_lease(identity, lease, now)
        if lease.lease_id in self._revoked_lease_ids:
            raise AuthorityError("LEASE_REVOKED")
