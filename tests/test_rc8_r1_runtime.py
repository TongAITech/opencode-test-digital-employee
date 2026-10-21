from __future__ import annotations

import json
from pathlib import Path

import pytest

from rc8_runtime import RuntimeProducerKind
from rc8_runtime.r1_runtime import CentralR1RuntimeLedger, R1ConflictError, R1TruthError, runtime_event


def _event(*, event_id="EV-1", sequence=1, event_type="TOOL_EXECUTED"):
    return runtime_event(
        event_id=event_id,
        test_run_id="RUN-1",
        work_item_id="WI-1",
        node_id="NODE-1",
        producer_kind=RuntimeProducerKind.TOOL,
        producer_ref="junit-runner",
        event_type=event_type,
        sequence=sequence,
        case_id="TC-1",
        attempt_id="ATT-1",
        step_id="STEP-1",
        data={"status": "PASS"},
    )


def test_r1_accepts_runtime_event_and_replays_deterministically(tmp_path: Path) -> None:
    path = tmp_path / "runtime-state" / "r1" / "event-stream.jsonl"
    ledger = CentralR1RuntimeLedger(str(path))
    receipt = ledger.append_runtime(_event())
    assert receipt == {"status": "PERSISTENCE_VERIFIED", "event_id": "EV-1", "seq": 1}

    replayed = CentralR1RuntimeLedger(str(path))
    events = replayed.runtime_events(test_run_id="RUN-1")
    assert len(events) == 1
    assert events[0]["event_type"] == "TOOL_EXECUTED"
    assert events[0]["producer_kind"] == "TOOL"
    assert events[0]["plane"] == "RUNTIME"


def test_r1_rejects_plan_event_at_runtime_truth_boundary(tmp_path: Path) -> None:
    ledger = CentralR1RuntimeLedger(str(tmp_path / "r1.jsonl"))
    with pytest.raises(R1TruthError, match="PLAN_EVENT_FORBIDDEN_IN_R1_RUNTIME"):
        ledger.append_plan({"event_type": "FUTURE_PLAN"})
    assert ledger.runtime_events() == []


def test_r1_duplicate_event_id_is_idempotent_when_payload_matches(tmp_path: Path) -> None:
    ledger = CentralR1RuntimeLedger(str(tmp_path / "r1.jsonl"))
    ledger.append_runtime(_event())
    duplicate = ledger.append_runtime(_event())
    assert duplicate == {"status": "IDEMPOTENT_REPLAY", "event_id": "EV-1", "seq": 1}
    assert len(ledger.runtime_events()) == 1


def test_r1_duplicate_event_id_conflict_fails_closed(tmp_path: Path) -> None:
    ledger = CentralR1RuntimeLedger(str(tmp_path / "r1.jsonl"))
    ledger.append_runtime(_event())
    with pytest.raises(R1ConflictError, match="R1_EVENT_ID_CONFLICT:EV-1"):
        ledger.append_runtime(_event(event_type="DIFFERENT_FACT"))


def test_r1_node_sequence_can_detect_stale_new_event(tmp_path: Path) -> None:
    ledger = CentralR1RuntimeLedger(str(tmp_path / "r1.jsonl"))
    ledger.append_runtime(_event(event_id="EV-2", sequence=2))
    stale = _event(event_id="EV-NEW", sequence=1)
    with pytest.raises(R1TruthError, match="NODE_EVENT_SEQUENCE_STALE"):
        ledger.assert_next_node_sequence(stale)


def test_r1_fails_replay_if_non_runtime_fact_is_injected(tmp_path: Path) -> None:
    path = tmp_path / "r1.jsonl"
    injected = {
        "seq": 1,
        "event": {
            "event_id": "EV-PLAN",
            "plane": "PLAN",
            "test_run_id": "RUN-1",
        },
    }
    path.write_text(json.dumps(injected) + "\n", encoding="utf-8")
    with pytest.raises(R1TruthError, match="R1_CONTAINS_NON_RUNTIME_EVENT"):
        CentralR1RuntimeLedger(str(path))
