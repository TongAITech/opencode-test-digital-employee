from copy import deepcopy

import pytest

from rc7_runtime.rc72_n1_completion import N1DeliveryGateService
from rc7_runtime.rc72_n1_executable_binding import (
    N1ExecutableBindingError,
    N1ExecutableBindingService,
)

from test_rc72_n1_completion import (
    BATCH,
    COMMIT,
    MISSION,
    RELEASE,
    _good_candidate,
    _handoff,
    _seed,
    _truth,
)


BINDING_KEY = "api://APP-CONFIG/FAT1/config-query"


def _binding():
    return {
        "verified": True,
        "binding_key": BINDING_KEY,
        "release_id": RELEASE,
        "mission_id": MISSION,
        "release_batch_id": BATCH,
        "source_commit": COMMIT,
        "environment": {
            "name": "FAT1",
            "status": "READY",
            "source_ref": "deployment://DEP-527",
        },
        "endpoint": {
            "verified": True,
            "url": "http://127.0.0.1:20354/config/query",
            "source_ref": "route://cfg-center/config-query",
        },
        "tool_route": {
            "verified": True,
            "tool": "api_http",
            "route": "cfg-center",
            "source_ref": "skill://api-routing/v1",
        },
        "capabilities": [
            {
                "name": "api_http",
                "status": "READY",
                "source_ref": "capability://api_http",
            }
        ],
        "resources": [
            {
                "name": "cfg-center-fat1",
                "status": "READY",
                "source_ref": "deployment://DEP-527",
            }
        ],
        "authoritative_sources": [
            "deployment://DEP-527",
            "route://cfg-center/config-query",
            "skill://api-routing/v1",
        ],
    }


def _candidate_with_binding(binding=None):
    candidate = deepcopy(_good_candidate())
    candidate["facts"]["executable_bindings"] = [
        deepcopy(_binding() if binding is None else binding)
    ]
    return candidate


def _complete_n1(tmp_path, candidate):
    truth = _truth(tmp_path)
    _seed(truth)
    _handoff(tmp_path, truth, candidate)
    result = N1DeliveryGateService(
        truth, source_commit=COMMIT
    ).complete(release_batch_id=BATCH)
    assert result["gate"]["decision"] == "PASS"
    assert result["gate"]["n1_state"] == "PASS"
    return truth, result


def test_n1_executable_binding_promotes_only_n1_owned_runtime_truth(tmp_path):
    truth, n1 = _complete_n1(
        tmp_path, _candidate_with_binding()
    )

    row = N1ExecutableBindingService(
        truth, source_commit=COMMIT
    ).canonicalize(
        release_batch_id=BATCH,
        binding_key=BINDING_KEY,
    )

    assert row["verified"] is True
    assert row["binding_key"] == BINDING_KEY
    assert row["schema_version"] == (
        "rc7.2-n1-executable-binding-v2"
    )
    assert row["environment"]["name"] == "FAT1"
    assert row["environment"]["status"] == "READY"
    assert row["endpoint"]["verified"] is True
    assert row["tool_route"]["verified"] is True
    assert row["source_n1_delivery_id"] == (
        n1["delivery"]["delivery_id"]
    )
    assert row["source_n1_gate_id"] == n1["gate"]["gate_id"]
    assert row["source_raw_sha256"].startswith("sha256:")
    assert len(row["binding_sha256"]) == 64
    for forbidden in (
        "request",
        "request_schema",
        "schema",
        "cleanup",
        "data_ref",
        "field_verified",
        "bank_final",
    ):
        assert forbidden not in row


def test_n1_executable_binding_replay_is_idempotent(tmp_path):
    truth, _n1 = _complete_n1(
        tmp_path, _candidate_with_binding()
    )
    service = N1ExecutableBindingService(
        truth, source_commit=COMMIT
    )

    first = service.canonicalize(
        release_batch_id=BATCH,
        binding_key=BINDING_KEY,
    )
    second = service.canonicalize(
        release_batch_id=BATCH,
        binding_key=BINDING_KEY,
    )

    assert first["binding_id"] == second["binding_id"]
    rows = truth.query(
        "rc72_n1_executable_binding",
        binding_id=first["binding_id"],
    )
    assert len(rows) == 1


def test_n1_executable_binding_missing_from_passed_reality_fails_closed(
    tmp_path,
):
    truth, _n1 = _complete_n1(
        tmp_path, deepcopy(_good_candidate())
    )

    with pytest.raises(
        N1ExecutableBindingError,
        match="BINDINGS_REQUIRED",
    ):
        N1ExecutableBindingService(
            truth, source_commit=COMMIT
        ).canonicalize(
            release_batch_id=BATCH,
            binding_key=BINDING_KEY,
        )

    assert truth.query("rc72_n1_executable_binding") == []


def test_n1_executable_binding_rejects_unverified_endpoint(tmp_path):
    binding = _binding()
    binding["endpoint"]["verified"] = False
    truth, _n1 = _complete_n1(
        tmp_path, _candidate_with_binding(binding)
    )

    with pytest.raises(
        N1ExecutableBindingError,
        match="ENDPOINT_NOT_VERIFIED",
    ):
        N1ExecutableBindingService(
            truth, source_commit=COMMIT
        ).canonicalize(
            release_batch_id=BATCH,
            binding_key=BINDING_KEY,
        )

    assert truth.query("rc72_n1_executable_binding") == []


def test_n1_executable_binding_rejects_lineage_mismatch(tmp_path):
    binding = _binding()
    binding["mission_id"] = "MISSION-WRONG"
    truth, _n1 = _complete_n1(
        tmp_path, _candidate_with_binding(binding)
    )

    with pytest.raises(
        N1ExecutableBindingError,
        match="MISSION_ID_MISMATCH",
    ):
        N1ExecutableBindingService(
            truth, source_commit=COMMIT
        ).canonicalize(
            release_batch_id=BATCH,
            binding_key=BINDING_KEY,
        )

    assert truth.query("rc72_n1_executable_binding") == []


def test_n1_executable_binding_requires_exact_binding_key_not_fuzzy_match(
    tmp_path,
):
    truth, _n1 = _complete_n1(
        tmp_path, _candidate_with_binding()
    )

    with pytest.raises(
        N1ExecutableBindingError,
        match="EXACT_BINDING_REQUIRED:0",
    ):
        N1ExecutableBindingService(
            truth, source_commit=COMMIT
        ).canonicalize(
            release_batch_id=BATCH,
            binding_key="api://APP-CONFIG/FAT1/config",
        )

    assert truth.query("rc72_n1_executable_binding") == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (
            "request",
            {
                "method": "POST",
                "schema_ref": "schema://cfg-center/config-query/v1",
                "source_ref": "codegraph://cfg-center/config-query",
            },
        ),
        (
            "request_schema",
            "schema://cfg-center/config-query/v1",
        ),
        (
            "schema",
            "schema://cfg-center/config-query/v1",
        ),
        (
            "cleanup",
            {
                "action": "release",
                "source_ref": "case://cleanup",
            },
        ),
    ],
)
def test_n1_executable_binding_rejects_n3_n4_owned_fields(
    tmp_path,
    field,
    value,
):
    binding = _binding()
    binding[field] = value
    truth, _n1 = _complete_n1(
        tmp_path, _candidate_with_binding(binding)
    )

    with pytest.raises(
        N1ExecutableBindingError,
        match="CROSS_NODE_FIELD_FORBIDDEN:%s" % field,
    ):
        N1ExecutableBindingService(
            truth, source_commit=COMMIT
        ).canonicalize(
            release_batch_id=BATCH,
            binding_key=BINDING_KEY,
        )

    assert truth.query("rc72_n1_executable_binding") == []


def test_n1_executable_binding_rejects_unknown_or_guessed_route_value(
    tmp_path,
):
    binding = _binding()
    binding["endpoint"]["url"] = "UNKNOWN"
    truth, _n1 = _complete_n1(
        tmp_path, _candidate_with_binding(binding)
    )

    with pytest.raises(
        N1ExecutableBindingError,
        match="ENDPOINT_VALUE_UNRESOLVED",
    ):
        N1ExecutableBindingService(
            truth, source_commit=COMMIT
        ).canonicalize(
            release_batch_id=BATCH,
            binding_key=BINDING_KEY,
        )

    assert truth.query("rc72_n1_executable_binding") == []
