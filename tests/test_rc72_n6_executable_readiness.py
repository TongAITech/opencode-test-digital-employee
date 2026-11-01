from copy import deepcopy
from datetime import datetime, timezone

import pytest

from rc7_runtime.rc72_n6_executable_readiness import (
    ExecutableReadinessError,
    N6ExecutableReadinessCompiler,
    N6_SCHEMA_VERSION,
)


NOW = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)


def _case():
    return {
        "release_batch_id": "BLOAN-PF1.2.1",
        "mission_id": "mission-121",
        "requirement_id": "STBB19-322",
        "sst_id": "STB913-14130",
        "obligation_id": "obl-negative-limit",
        "case_id": "case-limit-001",
        "case_ref": "r1://artifact/n4/case-limit-001",
        "status": "PASS",
        "preconditions": ["customer exists", "limit rule is deployed"],
        "inputs": {"customer_id": "${data.customer_id}", "amount": 100001},
        "steps": ["submit draw request", "observe response"],
        "expected": "request is rejected by configured limit rule",
        "oracles": ["API response code", "DB state unchanged", "CAT business error"],
        "evidence_requirements": ["request/response", "DB query", "CAT trace"],
        "authoritative_sources": [
            "r1://artifact/n4/design/case-limit-001",
            "codegraph://STB913-14130/limit-rule",
        ],
    }


def _data_ref(**updates):
    value = {
        "schema_version": "rc7.2-n5-resolved-ref-v1",
        "resolved_ref_status": "VERIFIED",
        "release_batch_id": "BLOAN-PF1.2.1",
        "mission_id": "mission-121",
        "requirement_id": "STBB19-322",
        "case_id": "case-limit-001",
        "candidate_id": "candidate-01",
        "data_ref": "tdsql://fat1/customer/900001",
        "expires_at": "2026-11-02T12:00:00Z",
        "authoritative_sources": ["tdsql://fat1/customer/900001"],
    }
    value.update(updates)
    return value


def _binding():
    return {
        "verified": True,
        "environment": {
            "name": "FAT1",
            "status": "READY",
            "source_ref": "deployment://BLOAN-PF1.2.1/FAT1",
        },
        "endpoint": {
            "url": "http://cfg-scd:20353/api/limit/check",
            "verified": True,
            "source_ref": "api-route://cfg-scd/limit-check",
        },
        "tool_route": {
            "tool": "api-http-worker",
            "verified": True,
            "source_ref": "capability://api-http-worker",
        },
        "request": {
            "method": "POST",
            "schema_ref": "openapi://cfg-scd/limit-check",
            "source_ref": "openapi://cfg-scd/limit-check",
        },
        "cleanup": {
            "action": "release verified data reservation after attempt",
            "source_ref": "data-policy://verified-ref-release",
        },
        "capabilities": [
            {
                "name": "API_HTTP",
                "status": "READY",
                "source_ref": "capability://api-http-worker",
            },
            {
                "name": "CAT_QUERY",
                "status": "READY",
                "source_ref": "capability://cat-query",
            },
        ],
        "resources": [
            {
                "name": "cfg-scd:FAT1",
                "status": "READY",
                "source_ref": "deployment://cfg-scd/FAT1",
            }
        ],
        "authoritative_sources": [
            "r1://n1/reality/FAT1",
            "deployment://BLOAN-PF1.2.1/FAT1",
        ],
    }


def _codes(error):
    return {item.code for item in error.value.violations}


def _targets(error):
    return {item.target_node for item in error.value.violations}


def test_compile_verified_executable_contract():
    contract = N6ExecutableReadinessCompiler().compile(
        _case(), [_data_ref()], _binding(), now=NOW
    )
    payload = contract.to_payload()

    assert payload["schema_version"] == N6_SCHEMA_VERSION
    assert payload["case_ref"] == "r1://artifact/n4/case-limit-001"
    assert payload["endpoint"]["url"].endswith("/api/limit/check")
    assert payload["tool_route"]["tool"] == "api-http-worker"
    assert payload["data_refs"][0]["resolved_ref_status"] == "VERIFIED"
    assert payload["assertions"][0]["source"] == "N4.expected"
    assert payload["required_capabilities"] == payload["capabilities"]
    assert payload["required_resources"] == payload["resources"]
    assert payload["contract_sha256"]
    assert "data_lease" not in payload


def test_digest_is_semantically_deterministic():
    compiler = N6ExecutableReadinessCompiler()
    first = compiler.compile(_case(), [_data_ref()], _binding(), now=NOW)
    later = compiler.compile(
        _case(),
        [_data_ref()],
        _binding(),
        now=datetime(2026, 11, 1, 13, 0, 0, tzinfo=timezone.utc),
    )

    assert first.contract_sha256 == later.contract_sha256
    assert first.compiled_at != later.compiled_at


@pytest.mark.parametrize(
    "mutation,expected_code",
    [
        (lambda case: case.update({"status": "STALE"}), "N6_N4_CASE_STALE"),
        (lambda case: case.update({"steps": ["guess during execution"]}), "N6_CASE_STEP_UNRESOLVED"),
        (lambda case: case.update({"oracles": []}), "N6_CASE_EXECUTION_FIELD_UNRESOLVED"),
        (lambda case: case.update({"evidence_requirements": []}), "N6_CASE_EXECUTION_FIELD_UNRESOLVED"),
    ],
)
def test_n4_case_gaps_fail_closed_to_n4(mutation, expected_code):
    case = _case()
    mutation(case)
    with pytest.raises(ExecutableReadinessError) as error:
        N6ExecutableReadinessCompiler().compile(case, [_data_ref()], _binding(), now=NOW)

    assert expected_code in _codes(error)
    assert "N4" in _targets(error)


def test_unverified_or_expired_data_ref_fails_closed_to_n5():
    ref = _data_ref(
        resolved_ref_status="CANDIDATE",
        expires_at="2026-10-31T12:00:00Z",
    )
    with pytest.raises(ExecutableReadinessError) as error:
        N6ExecutableReadinessCompiler().compile(_case(), [ref], _binding(), now=NOW)

    assert {"N6_DATA_REF_UNVERIFIED", "N6_DATA_REF_EXPIRED"} <= _codes(error)
    assert "N5" in _targets(error)


def test_data_ref_lineage_mismatch_fails_closed_to_n5():
    ref = _data_ref(requirement_id="STBB19-999")
    with pytest.raises(ExecutableReadinessError) as error:
        N6ExecutableReadinessCompiler().compile(_case(), [ref], _binding(), now=NOW)

    assert "N6_DATA_REF_LINEAGE_MISMATCH" in _codes(error)
    assert "N5" in _targets(error)


@pytest.mark.parametrize(
    "mutate,expected_code",
    [
        (
            lambda binding: binding["endpoint"].update(
                {"url": "UNKNOWN", "verified": False, "source_ref": ""}
            ),
            "N6_BINDING_UNVERIFIED",
        ),
        (
            lambda binding: binding["tool_route"].update(
                {"tool": "GUESS", "verified": False}
            ),
            "N6_BINDING_UNVERIFIED",
        ),
        (
            lambda binding: binding.update(
                {"request": {"method": "POST", "schema_ref": "TBD", "source_ref": ""}}
            ),
            "N6_REQUEST_SCHEMA_UNRESOLVED",
        ),
        (
            lambda binding: binding["capabilities"][0].update({"status": "UNKNOWN"}),
            "N6_RUNTIME_RESOURCE_NOT_READY",
        ),
        (
            lambda binding: binding["resources"][0].update({"status": "BLOCKED"}),
            "N6_RUNTIME_RESOURCE_NOT_READY",
        ),
    ],
)
def test_runtime_truth_gaps_fail_closed_to_n1(mutate, expected_code):
    binding = _binding()
    mutate(binding)
    with pytest.raises(ExecutableReadinessError) as error:
        N6ExecutableReadinessCompiler().compile(
            _case(), [_data_ref()], binding, now=NOW
        )

    assert expected_code in _codes(error)
    assert "N1" in _targets(error)


def test_missing_data_ref_cannot_be_replaced_by_local_guess():
    with pytest.raises(ExecutableReadinessError) as error:
        N6ExecutableReadinessCompiler().compile(_case(), [], _binding(), now=NOW)

    assert "N6_DATA_REF_MISSING" in _codes(error)
    assert "N5" in _targets(error)


def test_runtime_binding_must_be_explicitly_verified():
    binding = deepcopy(_binding())
    binding["verified"] = False
    with pytest.raises(ExecutableReadinessError) as error:
        N6ExecutableReadinessCompiler().compile(
            _case(), [_data_ref()], binding, now=NOW
        )

    assert "N6_RUNTIME_BINDING_UNVERIFIED" in _codes(error)
    assert "N1" in _targets(error)
