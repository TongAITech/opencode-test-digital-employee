"""RC8 N10 Center-owned convergence authority boundary.

The convergence policy in :mod:`rc8_center.mission_convergence` is deliberately
pure: it evaluates a complete ``MissionConvergenceTruth`` snapshot.  Production
callers must not be allowed to author that aggregate truth themselves, because
that would let a caller manufacture N1-N9 PASS, complete coverage, or an empty
blocking-gap set.

This module establishes the formal N10 entry boundary: callers provide only a
``test_run_id`` and ``decision_id``.  Center acquires the truth snapshot through
an injected Center-controlled truth source, validates its identity, and only
then invokes the deterministic convergence policy.

The concrete PostgreSQL/R1 truth source is intentionally a separate construction
slice.  Until that source is wired, production must remain fail-closed rather
than substituting caller-provided or model-provided truth.
"""
from __future__ import annotations

from typing import Protocol

from rc8_center.mission_convergence import (
    CenterMissionConvergenceService,
    MissionConvergenceDecision,
    MissionConvergenceError,
    MissionConvergenceTruth,
    ReportReleaseAuthorization,
)


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MissionConvergenceError("%s_REQUIRED" % name.upper())
    return value.strip()


class MissionConvergenceTruthSource(Protocol):
    """Center-controlled source of one complete, durable N10 truth snapshot."""

    def capture(self, test_run_id: str) -> MissionConvergenceTruth:
        ...


class CenterMissionConvergenceAuthority:
    """Formal N10 decision authority; aggregate truth is never a caller input."""

    def __init__(
        self,
        service: CenterMissionConvergenceService,
        truth_source: MissionConvergenceTruthSource,
    ) -> None:
        if not isinstance(service, CenterMissionConvergenceService):
            raise MissionConvergenceError("CENTER_CONVERGENCE_SERVICE_REQUIRED")
        if truth_source is None or not callable(getattr(truth_source, "capture", None)):
            raise MissionConvergenceError("CENTER_CONVERGENCE_TRUTH_SOURCE_REQUIRED")
        self.service = service
        self.truth_source = truth_source

    def evaluate_test_run(
        self,
        *,
        decision_id: str,
        test_run_id: str,
    ) -> MissionConvergenceDecision:
        """Capture Center truth for ``test_run_id`` and evaluate it deterministically."""

        decision_id = _required(decision_id, "decision_id")
        test_run_id = _required(test_run_id, "test_run_id")
        truth = self.truth_source.capture(test_run_id)
        if not isinstance(truth, MissionConvergenceTruth):
            raise MissionConvergenceError("CENTER_CONVERGENCE_TRUTH_SOURCE_INVALID")
        if truth.test_run_id != test_run_id:
            raise MissionConvergenceError("CENTER_CONVERGENCE_TRUTH_TEST_RUN_MISMATCH")
        return self.service.evaluate(decision_id=decision_id, truth=truth)

    def authorize_report_release(
        self,
        *,
        authorization_id: str,
        decision_id: str,
        report_id: str,
    ) -> ReportReleaseAuthorization:
        """Delegate report authorization only to an already persisted Center decision."""

        return self.service.authorize_report_release(
            authorization_id=_required(authorization_id, "authorization_id"),
            decision_id=_required(decision_id, "decision_id"),
            report_id=_required(report_id, "report_id"),
        )
