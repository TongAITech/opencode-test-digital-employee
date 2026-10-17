"""Read-only Bank-field summary for accepted-Case execution completeness.

This module makes fan-out shrinkage visible without inventing a second truth
store.  Every number is reconstructed from canonical R1 plus immutable
CASE_SCRIPT_READY / CASE_EXECUTION_TERMINAL receipts for the current accepted
Test Design.  It does not mutate Mission state and does not turn engineering
simulation into Bank Final evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Set, Tuple

from rc6_runtime.truth import TruthRuntime

from .case_fanout_conformance import (
    AcceptedCaseInventoryReader,
    check_script_barrier,
    contract_enabled,
)
from .execution_fanout_conformance import (
    check_execution_barrier,
    load_execution_terminal_receipt,
)


class CaseCoverageFieldSummaryError(RuntimeError):
    pass


@dataclass(frozen=True)
class CaseCoverageFieldSummary:
    mission_id: str
    status: str
    enforced: bool
    design_artifact_id: str
    accepted_case_count: int
    script_ready_case_count: int
    execution_terminal_case_count: int
    recovered_case_count: int
    product_defect_case_count: int
    unresolved_product_defect_count: int
    accepted_tc_ids: Tuple[str, ...]
    script_ready_tc_ids: Tuple[str, ...]
    execution_terminal_tc_ids: Tuple[str, ...]
    recovered_tc_ids: Tuple[str, ...]
    product_defect_tc_ids: Tuple[str, ...]
    missing_script_tc_ids: Tuple[str, ...]
    missing_execution_tc_ids: Tuple[str, ...]
    blocked_execution_tc_ids: Tuple[str, ...]
    unresolved_product_defect_gap_ids: Tuple[str, ...]
    script_receipt_ids: Tuple[str, ...]
    execution_receipt_ids: Tuple[str, ...]
    blocking_reasons: Tuple[str, ...]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "status": self.status,
            "enforced": self.enforced,
            "design_artifact_id": self.design_artifact_id,
            "accepted_case_count": self.accepted_case_count,
            "script_ready_case_count": self.script_ready_case_count,
            "execution_terminal_case_count": self.execution_terminal_case_count,
            "recovered_case_count": self.recovered_case_count,
            "product_defect_case_count": self.product_defect_case_count,
            "unresolved_product_defect_count": self.unresolved_product_defect_count,
            "accepted_tc_ids": list(self.accepted_tc_ids),
            "script_ready_tc_ids": list(self.script_ready_tc_ids),
            "execution_terminal_tc_ids": list(self.execution_terminal_tc_ids),
            "recovered_tc_ids": list(self.recovered_tc_ids),
            "product_defect_tc_ids": list(self.product_defect_tc_ids),
            "missing_script_tc_ids": list(self.missing_script_tc_ids),
            "missing_execution_tc_ids": list(self.missing_execution_tc_ids),
            "blocked_execution_tc_ids": list(self.blocked_execution_tc_ids),
            "unresolved_product_defect_gap_ids": list(self.unresolved_product_defect_gap_ids),
            "script_receipt_ids": list(self.script_receipt_ids),
            "execution_receipt_ids": list(self.execution_receipt_ids),
            "blocking_reasons": list(self.blocking_reasons),
        }


class CaseCoverageFieldSummaryBuilder:
    def __init__(self, truth: TruthRuntime) -> None:
        self.truth = truth

    def build(self, mission_id: str) -> CaseCoverageFieldSummary:
        mission_id = str(mission_id or "").strip()
        if not mission_id:
            raise CaseCoverageFieldSummaryError("MISSION_ID_REQUIRED")
        if not contract_enabled(self.truth, mission_id):
            return CaseCoverageFieldSummary(
                mission_id=mission_id,
                status="NOT_ENFORCED",
                enforced=False,
                design_artifact_id="",
                accepted_case_count=0,
                script_ready_case_count=0,
                execution_terminal_case_count=0,
                recovered_case_count=0,
                product_defect_case_count=0,
                unresolved_product_defect_count=0,
                accepted_tc_ids=(),
                script_ready_tc_ids=(),
                execution_terminal_tc_ids=(),
                recovered_tc_ids=(),
                product_defect_tc_ids=(),
                missing_script_tc_ids=(),
                missing_execution_tc_ids=(),
                blocked_execution_tc_ids=(),
                unresolved_product_defect_gap_ids=(),
                script_receipt_ids=(),
                execution_receipt_ids=(),
                blocking_reasons=("CASE_FANOUT_CONTRACT_REQUIRED",),
            )

        try:
            inventory = AcceptedCaseInventoryReader().load(self.truth, mission_id)
        except Exception as exc:
            return self._not_ready(mission_id, "ACCEPTED_CASE_INVENTORY_NOT_READY:%s" % exc)

        try:
            script = check_script_barrier(self.truth, mission_id)
        except Exception as exc:
            return self._not_ready(
                mission_id,
                "SCRIPT_BARRIER_ERROR:%s" % exc,
                design_artifact_id=inventory.design_artifact_id,
                accepted_tc_ids=inventory.tc_ids,
            )
        try:
            execution = check_execution_barrier(self.truth, mission_id)
        except Exception as exc:
            return self._not_ready(
                mission_id,
                "EXECUTION_BARRIER_ERROR:%s" % exc,
                design_artifact_id=inventory.design_artifact_id,
                accepted_tc_ids=inventory.tc_ids,
                script_ready_tc_ids=script.ready_tc_ids,
                missing_script_tc_ids=script.missing_tc_ids,
                script_receipt_ids=script.receipt_ids,
            )

        terminal_tc_ids: List[str] = []
        product_tc_ids: List[str] = []
        terminal_attempt_by_tc: Dict[str, str] = {}
        for receipt_id in execution.receipt_ids:
            payload = load_execution_terminal_receipt(
                self.truth,
                mission_id=mission_id,
                receipt_id=receipt_id,
            )
            tc_id = str(payload.get("tc_id") or "")
            attempt_id = str(payload.get("attempt_id") or "")
            if not tc_id or not attempt_id:
                raise CaseCoverageFieldSummaryError(
                    "CASE_EXECUTION_TERMINAL_IDENTITY_REQUIRED:%s" % receipt_id
                )
            terminal_tc_ids.append(tc_id)
            terminal_attempt_by_tc[tc_id] = attempt_id
            if payload.get("outcome") == "PRODUCT_DEFECT":
                product_tc_ids.append(tc_id)

        recovered = self._recovered_cases(
            mission_id=mission_id,
            accepted_tc_ids=set(inventory.tc_ids),
            terminal_attempt_by_tc=terminal_attempt_by_tc,
        )
        unresolved_gap_ids = tuple(sorted(
            str(row.get("gap_id") or "")
            for row in self.truth.query("rc7_gap", mission_id=mission_id)
            if row.get("category") == "PRODUCT_DEFECT"
            and row.get("state") != "RESOLVED"
            and str(row.get("gap_id") or "")
        ))

        blockers: List[str] = []
        if script.status != "PASS":
            blockers.append("SCRIPT_FANOUT_INCOMPLETE:%s" % ",".join(script.missing_tc_ids))
        if execution.status != "PASS":
            blockers.append("EXECUTION_FANOUT_INCOMPLETE:%s" % ",".join(execution.missing_tc_ids))
        if unresolved_gap_ids:
            blockers.append("PRODUCT_DEFECT_REVIEW_UNRESOLVED:%s" % ",".join(unresolved_gap_ids))

        accepted = tuple(sorted(inventory.tc_ids))
        terminals = tuple(sorted(set(terminal_tc_ids)))
        if execution.status == "PASS" and terminals != accepted:
            blockers.append("EXECUTION_TERMINAL_DENOMINATOR_MISMATCH")

        return CaseCoverageFieldSummary(
            mission_id=mission_id,
            status="PASS" if not blockers else "HOLD",
            enforced=True,
            design_artifact_id=inventory.design_artifact_id,
            accepted_case_count=len(accepted),
            script_ready_case_count=len(script.ready_tc_ids),
            execution_terminal_case_count=len(terminals),
            recovered_case_count=len(recovered),
            product_defect_case_count=len(set(product_tc_ids)),
            unresolved_product_defect_count=len(unresolved_gap_ids),
            accepted_tc_ids=accepted,
            script_ready_tc_ids=tuple(sorted(script.ready_tc_ids)),
            execution_terminal_tc_ids=terminals,
            recovered_tc_ids=tuple(sorted(recovered)),
            product_defect_tc_ids=tuple(sorted(set(product_tc_ids))),
            missing_script_tc_ids=tuple(sorted(script.missing_tc_ids)),
            missing_execution_tc_ids=tuple(sorted(execution.missing_tc_ids)),
            blocked_execution_tc_ids=tuple(sorted(execution.blocked_tc_ids)),
            unresolved_product_defect_gap_ids=unresolved_gap_ids,
            script_receipt_ids=tuple(sorted(script.receipt_ids)),
            execution_receipt_ids=tuple(sorted(execution.receipt_ids)),
            blocking_reasons=tuple(blockers),
        )

    def _recovered_cases(
        self,
        *,
        mission_id: str,
        accepted_tc_ids: Set[str],
        terminal_attempt_by_tc: Mapping[str, str],
    ) -> Set[str]:
        recovered: Set[str] = set()
        for action in self.truth.query("recovery_action"):
            if action.get("release_id") is None or action.get("verified") is not True:
                continue
            prior = str(action.get("prior_attempt_id") or "")
            successor = str(action.get("next_attempt_id") or "")
            if not prior or not successor:
                continue
            prior_rows = self.truth.query("execution_attempt", attempt_id=prior)
            successor_rows = self.truth.query("execution_attempt", attempt_id=successor)
            if len(prior_rows) != 1 or len(successor_rows) != 1:
                continue
            prior_row, successor_row = prior_rows[0], successor_rows[0]
            tc_id = str(successor_row.get("tc_id") or "")
            if (
                tc_id in accepted_tc_ids
                and str(prior_row.get("tc_id") or "") == tc_id
                and str(prior_row.get("status") or "").upper() == "FAIL"
                and str(successor_row.get("status") or "").upper() == "PASS"
                and terminal_attempt_by_tc.get(tc_id) == successor
            ):
                recovered.add(tc_id)
        return recovered

    @staticmethod
    def _not_ready(
        mission_id: str,
        reason: str,
        *,
        design_artifact_id: str = "",
        accepted_tc_ids: Tuple[str, ...] = (),
        script_ready_tc_ids: Tuple[str, ...] = (),
        missing_script_tc_ids: Tuple[str, ...] = (),
        script_receipt_ids: Tuple[str, ...] = (),
    ) -> CaseCoverageFieldSummary:
        accepted = tuple(sorted(accepted_tc_ids))
        return CaseCoverageFieldSummary(
            mission_id=mission_id,
            status="HOLD",
            enforced=True,
            design_artifact_id=design_artifact_id,
            accepted_case_count=len(accepted),
            script_ready_case_count=len(set(script_ready_tc_ids)),
            execution_terminal_case_count=0,
            recovered_case_count=0,
            product_defect_case_count=0,
            unresolved_product_defect_count=0,
            accepted_tc_ids=accepted,
            script_ready_tc_ids=tuple(sorted(set(script_ready_tc_ids))),
            execution_terminal_tc_ids=(),
            recovered_tc_ids=(),
            product_defect_tc_ids=(),
            missing_script_tc_ids=tuple(sorted(set(missing_script_tc_ids))),
            missing_execution_tc_ids=accepted,
            blocked_execution_tc_ids=(),
            unresolved_product_defect_gap_ids=(),
            script_receipt_ids=tuple(sorted(set(script_receipt_ids))),
            execution_receipt_ids=(),
            blocking_reasons=(reason,),
        )
