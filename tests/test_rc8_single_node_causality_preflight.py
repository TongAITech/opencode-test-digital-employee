from __future__ import annotations

import pytest

from rc8_center.single_node_truth_reader import (
    ProductionCenterR1TruthReader,
    ProductionTruthReaderError,
)


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _Session:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, statement):
        return _Result(self.value)


class _Store:
    def __init__(self, value):
        self.value = value

    def session(self):
        return _Session(self.value)


def _reader(existing_attempt_id=None):
    # Exercise the production preflight in isolation without weakening the
    # constructor's real Postgres/R1 type checks used by production wiring.
    reader = object.__new__(ProductionCenterR1TruthReader)
    reader.store = _Store(existing_attempt_id)
    return reader


def test_pristine_test_run_allows_production_causality_preflight():
    _reader().assert_no_attempts_for_test_run("run-1")


def test_preseeded_attempt_fails_closed_before_production_claim():
    with pytest.raises(
        ProductionTruthReaderError,
        match="PRODUCTION_CAUSALITY_PREFLIGHT_ATTEMPT_ALREADY_EXISTS:attempt-old",
    ):
        _reader("attempt-old").assert_no_attempts_for_test_run("run-1")


def test_missing_test_run_id_fails_closed():
    with pytest.raises(ProductionTruthReaderError, match="TEST_RUN_ID_REQUIRED"):
        _reader().assert_no_attempts_for_test_run(" ")
