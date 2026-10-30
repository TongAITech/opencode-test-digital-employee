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


def _reader(values):
    reader = object.__new__(ProductionCenterR1TruthReader)
    reader.store = _Store(values)
    return reader


def test_attempt_ids_for_test_run_returns_complete_sorted_durable_identity_set():
    reader = _reader(("attempt-a", "attempt-b", "attempt-c"))

    assert reader.attempt_ids_for_test_run("run-1") == (
        "attempt-a",
        "attempt-b",
        "attempt-c",
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
