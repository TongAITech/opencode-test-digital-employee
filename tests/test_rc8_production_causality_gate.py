from rc8_node.production_causality_gate import ProductionCausalityGate
from rc8_node.single_node_full_loop_proof import FROZEN_N1_N10_STAGES


def _identities(prefix):
    return tuple(f"{prefix}-{index}" for index, _ in enumerate(FROZEN_N1_N10_STAGES, start=1))


def _evaluate(gate, **overrides):
    leases = _identities("attempt")
    kwargs = {
        "bootstrap_materialized": True,
        "observed_stages": FROZEN_N1_N10_STAGES,
        "work_item_ids": _identities("wi"),
        "lease_ids": leases,
        "attempt_ids": leases,
        "evidence_refs": tuple(f"artifact:art-{index}" for index, _ in enumerate(FROZEN_N1_N10_STAGES, start=1)),
        "durable_truth_verified": True,
        "terminal_center_idle": True,
    }
    kwargs.update(overrides)
    return gate.evaluate(**kwargs)


def test_boundary_double_authority_cannot_promote_full_denominator():
    promotion = _evaluate(ProductionCausalityGate(production_constructor_verified=False))
    assert promotion.verified is False
    assert promotion.status == "PRODUCTION_CONSTRUCTOR_AUTHORITY_MISSING"


def test_constructor_authorized_gate_requires_exact_frozen_stage_denominator():
    gate = ProductionCausalityGate(production_constructor_verified=True)
    promotion = _evaluate(gate, observed_stages=FROZEN_N1_N10_STAGES[:-1])
    assert promotion.verified is False
    assert promotion.status == "PRODUCTION_STAGE_DENOMINATOR_MISMATCH"


def test_constructor_authorized_gate_requires_lease_attempt_identity_equality():
    gate = ProductionCausalityGate(production_constructor_verified=True)
    promotion = _evaluate(gate, attempt_ids=_identities("different-attempt"))
    assert promotion.verified is False
    assert promotion.status == "PRODUCTION_LEASE_ATTEMPT_IDENTITY_MISMATCH"


def test_constructor_authorized_gate_requires_terminal_center_idle():
    gate = ProductionCausalityGate(production_constructor_verified=True)
    promotion = _evaluate(gate, terminal_center_idle=False)
    assert promotion.verified is False
    assert promotion.status == "PRODUCTION_TERMINAL_CENTER_IDLE_NOT_VERIFIED"


def test_constructor_authorized_complete_production_denominator_can_promote():
    promotion = _evaluate(ProductionCausalityGate(production_constructor_verified=True))
    assert promotion.verified is True
    assert promotion.status == "PRODUCTION_CAUSALITY_VERIFIED"
