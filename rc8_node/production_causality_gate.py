"""Fail-closed promotion authority for RC8 SINGLE_NODE production causality.

This primitive deliberately owns no release or bank-reality authority.  It exists to
separate constructor-established production authority from mutable proof flags before
SingleNodeDurableIntegrationProofRunner is allowed to promote a completed 15-stage
production traversal.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .single_node_full_loop_proof import FROZEN_N1_N10_STAGES


_CONSTRUCTOR_AUTHORITY = object()


@dataclass(frozen=True)
class ProductionCausalityPromotion:
    verified: bool
    status: str


class ProductionCausalityGate:
    """Immutable constructor-issued authority plus exact-denominator promotion gate."""

    def __init__(self, *, production_constructor_verified: bool) -> None:
        self._authority = _CONSTRUCTOR_AUTHORITY if production_constructor_verified else None

    @property
    def constructor_authorized(self) -> bool:
        return self._authority is _CONSTRUCTOR_AUTHORITY

    def evaluate(
        self,
        *,
        bootstrap_materialized: bool,
        observed_stages: Sequence[str],
        work_item_ids: Sequence[str],
        lease_ids: Sequence[str],
        attempt_ids: Sequence[str],
        evidence_refs: Sequence[str],
        durable_truth_verified: bool,
        terminal_center_idle: bool,
    ) -> ProductionCausalityPromotion:
        if not self.constructor_authorized:
            return ProductionCausalityPromotion(False, "PRODUCTION_CONSTRUCTOR_AUTHORITY_MISSING")
        if not bootstrap_materialized:
            return ProductionCausalityPromotion(False, "PRODUCTION_BOOTSTRAP_NOT_MATERIALIZED")

        stages = tuple(str(stage).strip() for stage in observed_stages)
        if stages != tuple(FROZEN_N1_N10_STAGES):
            return ProductionCausalityPromotion(False, "PRODUCTION_STAGE_DENOMINATOR_MISMATCH")

        denominator = len(FROZEN_N1_N10_STAGES)
        identities = (
            tuple(work_item_ids),
            tuple(lease_ids),
            tuple(attempt_ids),
            tuple(evidence_refs),
        )
        if any(len(values) != denominator for values in identities):
            return ProductionCausalityPromotion(False, "PRODUCTION_IDENTITY_DENOMINATOR_MISMATCH")
        if any(len(set(values)) != denominator for values in identities):
            return ProductionCausalityPromotion(False, "PRODUCTION_IDENTITY_REUSE_DETECTED")
        if tuple(lease_ids) != tuple(attempt_ids):
            return ProductionCausalityPromotion(False, "PRODUCTION_LEASE_ATTEMPT_IDENTITY_MISMATCH")
        if not all(str(ref).startswith("artifact:") for ref in evidence_refs):
            return ProductionCausalityPromotion(False, "PRODUCTION_CANONICAL_EVIDENCE_REQUIRED")
        if not durable_truth_verified:
            return ProductionCausalityPromotion(False, "PRODUCTION_DURABLE_TRUTH_NOT_VERIFIED")
        if not terminal_center_idle:
            return ProductionCausalityPromotion(False, "PRODUCTION_TERMINAL_CENTER_IDLE_NOT_VERIFIED")

        return ProductionCausalityPromotion(True, "PRODUCTION_CAUSALITY_VERIFIED")
