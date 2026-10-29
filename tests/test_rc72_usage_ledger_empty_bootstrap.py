from pathlib import Path

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_usage_ledger import UsageLedgerService


def test_usage_ledger_bootstraps_empty_source_buckets_after_truth_runtime_start(tmp_path: Path) -> None:
    # Importing UsageLedgerService does not pre-install token/session overlays. This
    # deliberately creates R1 first, then installs the ledger service, matching a
    # long-lived process that enables RC7.2 economy observability additively.
    truth = TruthRuntime(tmp_path / "r1.jsonl")

    ledger = UsageLedgerService(truth, release_id="RC7.2").build(mission_id="M-EMPTY")

    assert ledger["status"] == "EMPTY"
    assert ledger["source_usage_count"] == 0
    assert ledger["resolved_lineage_count"] == 0
    assert ledger["unresolved_lineage_count"] == 0
    assert all(value is None for value in ledger["tokens"].values())
    assert all(value == 0 for value in ledger["counter_observation_counts"].values())
