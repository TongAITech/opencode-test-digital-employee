"""RC7 additive worker authority roles.

RC6 AuthorityRuntime remains frozen and unchanged. RC7 extends it through a
subclass with explicit candidate-output roles for the control-plane nodes. No
professional role receives acceptance authority; Evaluations remain separate R1
truth owned by independent evaluators.

RC7.1 execution sessions are Runtime truth. L1-L7 execution identities receive a
session id derived from the Runtime-issued worker id, so execution evidence can
prove its session binding instead of accepting a script-authored arbitrary
string.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Dict, Optional, Set

from rc6_runtime.authority import AuthorityRuntime, WorkerIdentity

from .runtime_timing_reality import install_rc7_1_runtime_timing


# Install before any RC7 formal execution starts. The overlay itself is guarded
# so only RunnerAdapter instances backed by RC7's evidence harness are changed;
# ordinary RC6 runner behavior remains untouched.
install_rc7_1_runtime_timing()


_EXECUTION_ROLES = frozenset("L%d_EXECUTE" % index for index in range(1, 8))


def execution_session_id(worker_id: str) -> str:
    worker = str(worker_id or "").strip()
    if not worker:
        raise ValueError("worker_id is required")
    return "runtime-session:" + worker


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

    def issue_identity(
        self,
        role: str,
        phase: str,
        layer: Optional[str],
        generation: int,
        session_id: str,
    ) -> WorkerIdentity:
        identity = super().issue_identity(role, phase, layer, generation, session_id)
        if role in _EXECUTION_ROLES and str(phase).upper() == "EXECUTION":
            bound = replace(identity, session_id=execution_session_id(identity.worker_id))
            self._identities[identity.worker_id] = bound
            return bound
        return identity
