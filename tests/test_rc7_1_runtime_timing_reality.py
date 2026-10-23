from __future__ import annotations

import hashlib
import json
from pathlib import Path

from rc6_runtime.truth import TruthRuntime
from tests.test_rc7_1_layer_execution_production_service import _run


def test_runtime_owned_timing_overwrites_script_clock_and_persists_to_r1(tmp_path: Path) -> None:
    truth, _control, result = _run(tmp_path, "L5")

    actual = result.execution_record.actual_result
    assert isinstance(actual, dict)
    timing = actual.get("runtime_timing")
    layer_evidence = actual.get("layer_evidence")
    assert isinstance(timing, dict)
    assert isinstance(layer_evidence, dict)

    assert timing["source"] == "RC7_RUNTIME"
    assert timing["tc_id"] == result.execution_record.tc_id
    assert timing["case_version"] == result.execution_record.case_version
    assert timing["layer"] == result.execution_record.layer
    assert timing["started_at"]
    assert timing["finished_at"]
    assert timing["finished_at"] >= timing["started_at"]
    assert int(timing["duration_ms"]) >= 0

    # These fields are authored by Runtime after the subprocess returns.  The
    # script cannot choose a different authoritative execution clock.
    assert layer_evidence["started_at"] == timing["started_at"]
    assert layer_evidence["finished_at"] == timing["finished_at"]
    assert layer_evidence["runtime_timing_ref"] == timing["evidence_ref"]

    timing_ref = str(timing["evidence_ref"])
    assert timing_ref.startswith("file://")
    timing_path = Path(timing_ref[len("file://"):])
    assert timing_path.is_file()
    timing_bytes = timing_path.read_bytes()
    assert hashlib.sha256(timing_bytes).hexdigest() == timing["sha256"]
    persisted_timing = json.loads(timing_bytes.decode("utf-8"))
    for field in (
        "tc_id",
        "case_version",
        "layer",
        "script_id",
        "runner_type",
        "test_symbol",
        "started_at",
        "finished_at",
        "duration_ms",
        "exit_code",
    ):
        assert persisted_timing[field] == timing[field]

    rows = [
        row
        for row in truth.query("rc7_evidence", mission_id="MISSION-RC7-1-LAYER-L5")
        if row.get("kind") == "RUNTIME_EXECUTION_EVIDENCE"
        and row.get("content_ref") == timing_ref
    ]
    assert len(rows) == 1
    assert rows[0]["content_hash"] == "sha256:" + timing["sha256"]

    # Re-open canonical R1 from disk.  The timing receipt must remain
    # reconstructable after process restart, not only in Python memory.
    recovered = TruthRuntime(tmp_path / "runtime-state" / "r1" / "event-stream.jsonl")
    recovered_rows = [
        row
        for row in recovered.query("rc7_evidence", mission_id="MISSION-RC7-1-LAYER-L5")
        if row.get("kind") == "RUNTIME_EXECUTION_EVIDENCE"
        and row.get("content_ref") == timing_ref
    ]
    assert len(recovered_rows) == 1
    assert recovered_rows[0]["content_hash"] == rows[0]["content_hash"]

    record_rows = recovered.query("rc7_evidence", evidence_id=result.record_evidence_id)
    assert len(record_rows) == 1
    record_path = Path(str(record_rows[0]["content_ref"])[len("file://"):])
    record_payload = json.loads(record_path.read_text(encoding="utf-8"))
    recovered_actual = record_payload["record"]["actual_result"]
    assert recovered_actual["runtime_timing"] == timing
    assert recovered_actual["layer_evidence"]["started_at"] == timing["started_at"]
    assert recovered_actual["layer_evidence"]["finished_at"] == timing["finished_at"]
