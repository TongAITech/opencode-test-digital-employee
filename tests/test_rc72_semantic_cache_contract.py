from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_semantic_cache import SemanticCacheService, SemanticCacheSpec


RELEASE = "RC7.2"


def _service(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    return truth, SemanticCacheService(truth, release_id=RELEASE)


def _spec(**changes):
    values = {
        "namespace": "requirement-semantic-derivation",
        "semantic_inputs": {
            "requirement_sha256": "a" * 64,
            "sst_sha256": "b" * 64,
            "business_scope": {"application_id": "cfg-center", "environment": "FAT1"},
        },
        "producer_contract": {
            "contract_version": "req-analysis-v7",
            "model_profile": "bank-semantic",
            "allowed_tools": ["read_text"],
            "output_schema": "requirement-analysis-v3",
        },
        "requires_fresh_runtime_proof": False,
    }
    values.update(changes)
    return SemanticCacheSpec(**values)


def _store(service: SemanticCacheService, spec=None, result=None, status="VALIDATED"):
    return service.store_validated(
        spec or _spec(),
        result_payload=result or {"business_rules": ["BR-1"], "negative_paths": ["NP-1"]},
        validation_status=status,
        validation_evidence_refs=["EVD-VALIDATION-1"],
        source_mission_id="M-SOURCE",
        source_workitem_id="WI-SOURCE",
        source_attempt_id="ATT-SOURCE",
        source_assignment_id="ASSIGN-SOURCE",
        source_ref="artifact://REQ-ANALYSIS-1",
    )


def test_semantic_digest_is_stable_for_mapping_order_but_changes_with_semantics(tmp_path: Path):
    _, service = _service(tmp_path)
    first = _spec()
    reordered = SemanticCacheSpec(
        namespace=first.namespace,
        semantic_inputs={
            "business_scope": {"environment": "FAT1", "application_id": "cfg-center"},
            "sst_sha256": "b" * 64,
            "requirement_sha256": "a" * 64,
        },
        producer_contract={
            "output_schema": "requirement-analysis-v3",
            "allowed_tools": ["read_text"],
            "model_profile": "bank-semantic",
            "contract_version": "req-analysis-v7",
        },
    )
    changed_input = _spec(
        semantic_inputs={
            "requirement_sha256": "c" * 64,
            "sst_sha256": "b" * 64,
            "business_scope": {"application_id": "cfg-center", "environment": "FAT1"},
        }
    )
    changed_contract = _spec(
        producer_contract={
            "contract_version": "req-analysis-v8",
            "model_profile": "bank-semantic",
            "allowed_tools": ["read_text"],
            "output_schema": "requirement-analysis-v3",
        }
    )

    assert service.semantic_digest(first) == service.semantic_digest(reordered)
    assert service.semantic_digest(first) != service.semantic_digest(changed_input)
    assert service.semantic_digest(first) != service.semantic_digest(changed_contract)


def test_validated_cache_hit_has_explicit_source_provenance_and_is_not_fresh_execution(tmp_path: Path):
    truth, service = _service(tmp_path)
    spec = _spec()
    entry = _store(service, spec)

    decision = service.lookup(
        spec,
        target_mission_id="M-TARGET",
        target_workitem_id="WI-TARGET",
        target_attempt_id="ATT-TARGET",
    )

    assert decision.hit is True
    assert decision.decision == "HIT"
    assert decision.fresh_execution is False
    assert decision.cache_entry_id == entry["cache_entry_id"]
    assert decision.result_payload == {"business_rules": ["BR-1"], "negative_paths": ["NP-1"]}
    assert decision.source_mission_id == "M-SOURCE"
    assert decision.source_workitem_id == "WI-SOURCE"
    assert decision.source_attempt_id == "ATT-SOURCE"
    assert decision.source_assignment_id == "ASSIGN-SOURCE"
    uses = truth.query("rc72_semantic_cache_use", cache_use_id=decision.cache_use_id)
    assert len(uses) == 1
    assert uses[0]["target_mission_id"] == "M-TARGET"
    assert uses[0]["fresh_execution"] is False
    assert uses[0]["validation_evidence_refs"] == ["EVD-VALIDATION-1"]


def test_fresh_runtime_proof_work_bypasses_cache_and_cannot_be_stored(tmp_path: Path):
    truth, service = _service(tmp_path)
    spec = _spec(requires_fresh_runtime_proof=True)

    decision = service.lookup(
        spec,
        target_mission_id="M-REVIEW",
        target_workitem_id="WI-REVIEW",
        target_attempt_id="ATT-REVIEW",
    )

    assert decision.decision == "BYPASS"
    assert decision.reason == "FRESH_RUNTIME_PROOF_REQUIRED"
    assert decision.hit is False
    assert truth.query("rc72_semantic_cache_use") == []
    with pytest.raises(ContractError, match="FRESH_RUNTIME_PROOF_REQUIRED"):
        _store(service, spec)


def test_unknown_failed_or_incomplete_semantic_results_are_never_cacheable(tmp_path: Path):
    _, service = _service(tmp_path)
    for status in ("UNKNOWN", "FAILED", "INCOMPLETE"):
        with pytest.raises(ContractError, match="ONLY_VALIDATED_RESULTS_CACHEABLE"):
            _store(service, status=status)


def test_validation_evidence_is_mandatory_for_cacheability(tmp_path: Path):
    _, service = _service(tmp_path)
    with pytest.raises(ContractError, match="VALIDATION_EVIDENCE_REQUIRED"):
        service.store_validated(
            _spec(),
            result_payload={"business_rules": ["BR-1"]},
            validation_status="VALIDATED",
            validation_evidence_refs=[],
            source_mission_id="M-1",
            source_workitem_id="WI-1",
            source_attempt_id="ATT-1",
            source_assignment_id="ASSIGN-1",
            source_ref="artifact://A-1",
        )


def test_same_semantic_digest_cannot_be_overwritten_with_different_validated_result(tmp_path: Path):
    _, service = _service(tmp_path)
    spec = _spec()
    first = _store(service, spec, result={"business_rules": ["BR-1"]})
    idempotent = _store(service, spec, result={"business_rules": ["BR-1"]})
    assert idempotent["cache_entry_id"] == first["cache_entry_id"]

    with pytest.raises(ContractError, match="NONDETERMINISTIC_RESULT"):
        _store(service, spec, result={"business_rules": ["BR-2"]})


def test_invalidated_entry_never_returns_hit(tmp_path: Path):
    truth, service = _service(tmp_path)
    spec = _spec()
    entry = _store(service, spec)
    invalidated = service.invalidate(entry["cache_entry_id"], reason="source evidence superseded")
    assert invalidated["state"] == "INVALIDATED"

    decision = service.lookup(
        spec,
        target_mission_id="M-2",
        target_workitem_id="WI-2",
        target_attempt_id="ATT-2",
    )
    assert decision.decision == "MISS"
    assert decision.reason == "SEMANTIC_CACHE_ENTRY_INVALIDATED"
    assert truth.query("rc72_semantic_cache_use") == []


def test_same_validated_semantics_can_reuse_across_workitems_with_explicit_receipt(tmp_path: Path):
    truth, service = _service(tmp_path)
    spec = _spec()
    _store(service, spec)

    one = service.lookup(
        spec,
        target_mission_id="M-TARGET",
        target_workitem_id="WI-A",
        target_attempt_id="ATT-A",
    )
    two = service.lookup(
        spec,
        target_mission_id="M-TARGET",
        target_workitem_id="WI-B",
        target_attempt_id="ATT-B",
    )

    assert one.hit and two.hit
    assert one.cache_entry_id == two.cache_entry_id
    assert one.cache_use_id != two.cache_use_id
    uses = truth.query("rc72_semantic_cache_use", cache_entry_id=one.cache_entry_id)
    assert {row["target_workitem_id"] for row in uses} == {"WI-A", "WI-B"}
    assert all(row["source_assignment_id"] == "ASSIGN-SOURCE" for row in uses)


def test_noncanonical_json_inputs_fail_before_digest_or_storage(tmp_path: Path):
    _, service = _service(tmp_path)
    with pytest.raises(ContractError, match="NOT_CANONICAL_JSON"):
        SemanticCacheSpec(
            namespace="bad",
            semantic_inputs={"opaque": object()},
            producer_contract={"version": "v1"},
        )

    with pytest.raises(ContractError, match="NOT_CANONICAL_JSON"):
        SemanticCacheSpec(
            namespace="bad-float",
            semantic_inputs={"score": float("nan")},
            producer_contract={"version": "v1"},
        )
