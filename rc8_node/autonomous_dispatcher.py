"""Stage-safe autonomous RC8 Node dispatcher.

The dispatcher never scans WorkItem IDs.  It asks Center for the next READY
item restricted to the exact Stage types for which this process has a worker.
Center still enforces VERIFIED required capabilities before leasing.

Unknown Stage types are therefore filtered before lease acquisition rather than
being claimed and abandoned for recovery.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

from .autonomous_claim_client import AutonomousClaimClient, ClaimedWork


class AutonomousDispatcherError(RuntimeError):
    pass


@dataclass(frozen=True)
class DispatchOutcome:
    status: str
    stage: Optional[str] = None
    work_item_id: Optional[str] = None
    lease_id: Optional[str] = None
    stage_instance_id: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    claim_truth_note: Optional[str] = None


class AutonomousWorkerDispatcher:
    def __init__(
        self,
        *,
        claimant: AutonomousClaimClient,
        workers: Mapping[str, Any],
        ttl_seconds: int = 60,
        idle_sleep_seconds: float = 1.0,
    ) -> None:
        normalized = {
            str(stage or "").strip(): worker
            for stage, worker in dict(workers).items()
            if str(stage or "").strip()
        }
        if not normalized:
            raise AutonomousDispatcherError("AUTONOMOUS_WORKER_MAPPING_REQUIRED")
        if any(worker is None or not callable(getattr(worker, "execute", None)) for worker in normalized.values()):
            raise AutonomousDispatcherError("AUTONOMOUS_WORKER_EXECUTE_REQUIRED")
        if not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
            raise AutonomousDispatcherError("AUTONOMOUS_LEASE_TTL_INVALID")
        if float(idle_sleep_seconds) < 0:
            raise AutonomousDispatcherError("AUTONOMOUS_IDLE_SLEEP_INVALID")
        self.claimant = claimant
        self.workers = normalized
        self.ttl_seconds = ttl_seconds
        self.idle_sleep_seconds = float(idle_sleep_seconds)

    @property
    def supported_stages(self) -> Tuple[str, ...]:
        return tuple(sorted(self.workers))

    def run_once(self, *, test_run_id: Optional[str] = None) -> DispatchOutcome:
        claimed = self.claimant.claim_next(
            ttl_seconds=self.ttl_seconds,
            test_run_id=test_run_id,
            stage_types=self.supported_stages,
        )
        if not claimed.claimed:
            return DispatchOutcome(status="IDLE", claim_truth_note=str(claimed.truth_note or "").strip() or None)
        requested_run_id = str(test_run_id or "").strip()
        if requested_run_id and str(claimed.test_run_id or "").strip() != requested_run_id:
            raise AutonomousDispatcherError("CLAIMED_TEST_RUN_ID_MISMATCH")
        return self._execute_claim(claimed)

    def _execute_claim(self, claimed: ClaimedWork) -> DispatchOutcome:
        stage = str(claimed.stage or "").strip()
        work_item_id = str(claimed.work_item_id or "").strip()
        if not stage or not work_item_id or not claimed.lease_id or not claimed.stage_instance_id:
            raise AutonomousDispatcherError("CLAIMED_WORK_IDENTITY_INCOMPLETE")
        worker = self.workers.get(stage)
        if worker is None:
            raise AutonomousDispatcherError("CLAIMED_STAGE_NOT_IMPLEMENTED:%s" % stage)
        result = worker.execute(claimed)
        if not isinstance(result, dict):
            raise AutonomousDispatcherError("WORKER_RESULT_OBJECT_REQUIRED:%s" % stage)
        return DispatchOutcome(
            status="EXECUTED",
            stage=stage,
            work_item_id=work_item_id,
            lease_id=str(claimed.lease_id),
            stage_instance_id=str(claimed.stage_instance_id),
            result=result,
            claim_truth_note=str(claimed.truth_note or "").strip() or None,
        )

    def run_forever(
        self,
        *,
        test_run_id: Optional[str] = None,
        heartbeat: Optional[Any] = None,
    ) -> None:
        while True:
            outcome = self.run_once(test_run_id=test_run_id)
            if heartbeat is not None:
                heartbeat()
            if outcome.status == "IDLE" and self.idle_sleep_seconds:
                time.sleep(self.idle_sleep_seconds)