from pathlib import Path


def test_zero_denominator_cannot_be_reported_as_full_coverage():
    """Frozen sufficiency must fail closed when the denominator is empty.

    0/0 is UNKNOWN, never 100%.  Keep this as a source-level contract so a
    future refactor cannot silently restore the historical fake-green branch.
    """
    source = Path("rc8_runtime/governance.py").read_text(encoding="utf-8")
    forbidden = "if self.total == 0:\n            return 1.0"
    assert forbidden not in source, "ZERO_DENOMINATOR_MUST_NOT_EQUAL_FULL_COVERAGE"
