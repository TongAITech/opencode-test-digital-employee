from __future__ import annotations

import pytest

from rc8_node.executable_spec_worker import ExecutableSpecWorker, ExecutableSpecWorkerError


def _candidate():
    return {
        "prepared_attempt_id": "prepared-1",
        "frozen_case_ref": "case:CASE-1@v3",
        "driver_ref": "driver:pytest",
        "script_artifact_ref": "artifact:script-1",
        "fixture_binding_refs": ["fixture:customer-C001"],
        "assertion_refs": ["assertion:balance-updated"],
        "evidence_collector_refs": ["collector:http", "collector:db"],
        "build_evidence_refs": ["artifact:compile-1"],
    }


def test_candidate_binds_exact_prepared_attempt_and_executable_contract():
    value = ExecutableSpecWorker.validate_candidate(_candidate())
    assert value["prepared_attempt_id"] == "prepared-1"
    assert value["assertion_refs"] == ["assertion:balance-updated"]


@pytest.mark.parametrize("field", ["prepared_attempt_id", "frozen_case_ref", "driver_ref", "script_artifact_ref"])
def test_candidate_fails_closed_when_identity_binding_missing(field):
    value = _candidate()
    value[field] = ""
    with pytest.raises(ExecutableSpecWorkerError, match=field.upper() + "_REQUIRED"):
        ExecutableSpecWorker.validate_candidate(value)


@pytest.mark.parametrize("field", ["fixture_binding_refs", "assertion_refs", "evidence_collector_refs", "build_evidence_refs"])
def test_candidate_requires_nonempty_execution_and_evidence_denominators(field):
    value = _candidate()
    value[field] = []
    with pytest.raises(ExecutableSpecWorkerError, match=field.upper() + "_NONEMPTY_REQUIRED"):
        ExecutableSpecWorker.validate_candidate(value)


def test_candidate_rejects_duplicate_refs_in_denominator():
    value = _candidate()
    value["assertion_refs"] = ["assertion:a", "assertion:a"]
    with pytest.raises(ExecutableSpecWorkerError, match="ASSERTION_REFS_UNIQUE_REQUIRED"):
        ExecutableSpecWorker.validate_candidate(value)


def test_worker_contract_keeps_executable_readiness_authority_at_center():
    assert ExecutableSpecWorker.producer_ref == "RC8_EXECUTABLE_SPEC_WORKER"
