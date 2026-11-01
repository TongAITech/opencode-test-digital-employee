from __future__ import annotations

from contextlib import contextmanager

import pytest

from rc8_center.single_node_truth_reader import (
    ProductionCenterR1TruthReader,
    ProductionTruthReaderError,
)


class _ScalarResult:
    def __init__(self, values):
        self._values = list(values)

    def scalars(self):
        return self

    def all(self):
        return list(self._values)


class _Session:
    def __init__(self, values):
        self._values = values

    def execute(self, _statement):
        return _ScalarResult(self._values)


class _Store:
    def __init__(self, values):
        self._values = values

    @contextmanager
    def session(self):
        yield _Session(self._values)


class _Ledger:
    def __init__(self, events):
        self._events = tuple(events)

    def runtime_events(self, *, test_run_id, **_kwargs):
        return tuple(event for event in self._events if event.get("test_run_id") == test_run_id)


def _reader(values, events=()):
    reader = object.__new__(ProductionCenterR1TruthReader)
    reader.store = _Store(values)
    reader.r1_ledger = _Ledger(events)
    return reader


def _lifecycle(event_type, attempt_id):
    return {"event_type": event_type, "attempt_id": attempt_id, "test_run_id": "run-1"}


def test_attempt_ids_for_test_run_returns_complete_sorted_durable_identity_set():
    reader = _reader(("attempt-a", "attempt-b", "attempt-c"))
    assert reader.attempt_ids_for_test_run("run-1") == (
        "attempt-a", "attempt-b", "attempt-c"
    )


def test_attempt_ids_for_test_run_rejects_blank_test_run_identity():
    reader = _reader(())
    with pytest.raises(ProductionTruthReaderError, match="TEST_RUN_ID_REQUIRED"):
        reader.attempt_ids_for_test_run("   ")


def test_attempt_ids_for_test_run_rejects_duplicate_durable_identity():
    reader = _reader(("attempt-a", "attempt-a"))
    with pytest.raises(
        ProductionTruthReaderError,
        match="DURABLE_ATTEMPT_ID_NOT_UNIQUE:run-1",
    ):
        reader.attempt_ids_for_test_run("run-1")


def test_observed_center_leases_must_exactly_match_complete_durable_attempt_set():
    reader = _reader(("lease-a", "lease-b", "lease-c"))
    reader.assert_attempt_ids_match_observed_leases(
        test_run_id="run-1",
        observed_lease_ids=("lease-c", "lease-a", "lease-b"),
    )


def test_observed_center_leases_reject_missing_or_unexpected_durable_attempts():
    reader = _reader(("lease-a", "stale-attempt"))
    with pytest.raises(
        ProductionTruthReaderError,
        match="PRODUCTION_CAUSALITY_ATTEMPT_LEASE_SET_MISMATCH:run-1",
    ):
        reader.assert_attempt_ids_match_observed_leases(
            test_run_id="run-1",
            observed_lease_ids=("lease-a", "lease-b"),
        )


def test_observed_center_leases_reject_duplicate_identity_before_set_comparison():
    reader = _reader(("lease-a",))
    with pytest.raises(
        ProductionTruthReaderError,
        match="OBSERVED_LEASE_ID_NOT_UNIQUE:run-1",
    ):
        reader.assert_attempt_ids_match_observed_leases(
            test_run_id="run-1",
            observed_lease_ids=("lease-a", "lease-a"),
        )


def test_r1_lifecycle_sets_must_exactly_match_observed_center_leases():
    reader = _reader(("lease-a", "lease-b"), events=(
        _lifecycle("ATTEMPT_STARTED", "lease-a"),
        _lifecycle("ATTEMPT_STARTED", "lease-b"),
        _lifecycle("ATTEMPT_COMPLETED", "lease-a"),
        _lifecycle("ATTEMPT_COMPLETED", "lease-b"),
    ))
    reader.assert_r1_attempt_lifecycle_matches_observed_leases(
        test_run_id="run-1", observed_lease_ids=("lease-b", "lease-a")
    )


def test_r1_lifecycle_set_rejects_unexpected_attempt_identity():
    reader = _reader(("lease-a",), events=(
        _lifecycle("ATTEMPT_STARTED", "lease-a"),
        _lifecycle("ATTEMPT_STARTED", "stale-attempt"),
        _lifecycle("ATTEMPT_COMPLETED", "lease-a"),
    ))
    with pytest.raises(
        ProductionTruthReaderError,
        match="PRODUCTION_CAUSALITY_R1_STARTED_LEASE_SET_MISMATCH:run-1",
    ):
        reader.assert_r1_attempt_lifecycle_matches_observed_leases(
            test_run_id="run-1", observed_lease_ids=("lease-a",)
        )


def test_r1_lifecycle_set_rejects_missing_completion():
    reader = _reader(("lease-a", "lease-b"), events=(
        _lifecycle("ATTEMPT_STARTED", "lease-a"),
        _lifecycle("ATTEMPT_STARTED", "lease-b"),
        _lifecycle("ATTEMPT_COMPLETED", "lease-a"),
    ))
    with pytest.raises(
        ProductionTruthReaderError,
        match="PRODUCTION_CAUSALITY_R1_COMPLETED_LEASE_SET_MISMATCH:run-1",
    ):
        reader.assert_r1_attempt_lifecycle_matches_observed_leases(
            test_run_id="run-1", observed_lease_ids=("lease-a", "lease-b")
        )


def test_r1_lifecycle_set_rejects_duplicate_started_identity():
    reader = _reader(("lease-a",), events=(
        _lifecycle("ATTEMPT_STARTED", "lease-a"),
        _lifecycle("ATTEMPT_STARTED", "lease-a"),
        _lifecycle("ATTEMPT_COMPLETED", "lease-a"),
    ))
    with pytest.raises(
        ProductionTruthReaderError,
        match="R1_ATTEMPT_STARTED_ID_NOT_UNIQUE:run-1",
    ):
        reader.assert_r1_attempt_lifecycle_matches_observed_leases(
            test_run_id="run-1", observed_lease_ids=("lease-a",)
        )
