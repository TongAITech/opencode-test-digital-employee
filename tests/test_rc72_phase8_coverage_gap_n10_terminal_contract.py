from rc7_runtime.rc72_release_convergence import ReleaseConvergenceAggregator


def test_n10_accepts_only_verified_coverage_gap_terminal_states():
    assert ReleaseConvergenceAggregator._COVERAGE_GAP_TERMINAL == {
        "RESOLVED",
        "EXCLUDED_APPROVED",
    }
    assert "CLASSIFIED" not in ReleaseConvergenceAggregator._COVERAGE_GAP_TERMINAL
    assert "EXCLUSION_REVIEW_REQUIRED" not in ReleaseConvergenceAggregator._COVERAGE_GAP_TERMINAL
    assert "MAPPED" not in ReleaseConvergenceAggregator._COVERAGE_GAP_TERMINAL
