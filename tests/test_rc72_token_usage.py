from __future__ import annotations

from types import SimpleNamespace

import pytest

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_model_usage import DshTokenUsageParser, TokenUsageAuditService


class _MemoryTruth:
    def __init__(self):
        self.projection = SimpleNamespace(_versions={})
        self.events = []

    def query(self, artifact_type, **filters):
        bucket_name = _truth.BUCKETS.get(artifact_type)
        bucket = getattr(self.projection, bucket_name, {}) if bucket_name else {}
        return [
            dict(row)
            for row in bucket.values()
            if all(row.get(name) == value for name, value in filters.items())
        ]

    def append_atomic(self, event_type, payload):
        artifact_type, identity = _truth.EVENT_TYPES[event_type]
        row = _contracts.VALIDATORS[artifact_type](dict(payload))
        bucket_name = _truth.BUCKETS[artifact_type]
        if not hasattr(self.projection, bucket_name):
            setattr(self.projection, bucket_name, {})
        bucket = getattr(self.projection, bucket_name)
        current = bucket.get(row[identity])
        if current is not None:
            assert row["artifact_version"] == current["artifact_version"] + 1
        bucket[row[identity]] = dict(row)
        self.events.append((event_type, dict(row)))
        return row


def _service():
    truth = _MemoryTruth()
    return truth, TokenUsageAuditService(truth, release_id="REL-1")


def _observe(service, events, **overrides):
    kwargs = {
        "mission_id": "MISSION-1",
        "attempt_id": "ATT-1",
        "assignment_id": "ASN-1",
        "raw_output_ref": "file:///state/worker-evidence/MISSION-1/ASN-1.jsonl",
        "events": events,
        "dsh_session_id": "session-worker-1",
    }
    kwargs.update(overrides)
    return service.observe(**kwargs)


def test_parser_observes_nested_direct_dsh_usage_without_inventing_fields():
    parsed = DshTokenUsageParser.parse(
        [
            {"type": "session", "session_id": "session-worker-1"},
            {
                "type": "final",
                "provider": "bank-provider",
                "model": "bank-model",
                "usage": {"input_tokens": 1200, "output_tokens": 180, "total_tokens": 1380},
            },
        ]
    )
    assert parsed.observation_status == "OBSERVED"
    assert parsed.input_tokens == 1200
    assert parsed.output_tokens == 180
    assert parsed.total_tokens == 1380
    assert parsed.provider == "bank-provider"
    assert parsed.model == "bank-model"
    assert parsed.cache_read_tokens is None
    assert parsed.observation_sha256


def test_parser_normalizes_openai_style_prompt_completion_and_cache_aliases():
    parsed = DshTokenUsageParser.parse(
        [
            {
                "type": "response",
                "response": {
                    "model": "model-x",
                    "usage": {
                        "prompt_tokens": 900,
                        "completion_tokens": 100,
                        "cache_read_input_tokens": 700,
                        "cache_creation_input_tokens": 25,
                    },
                },
            }
        ]
    )
    assert parsed.observation_status == "OBSERVED"
    assert parsed.input_tokens == 900
    assert parsed.output_tokens == 100
    assert parsed.cache_read_tokens == 700
    assert parsed.cache_write_tokens == 25
    assert parsed.total_tokens is None


def test_missing_usage_is_unknown_and_never_fabricates_zero():
    parsed = DshTokenUsageParser.parse(
        [
            {"type": "session", "session_id": "session-worker-1"},
            {"type": "tool_call", "tool_name": "codegraph"},
            {"type": "final", "text": "done"},
        ]
    )
    assert parsed.observation_status == "UNKNOWN"
    assert parsed.unknown_reason == "TOKEN_USAGE_NOT_EXPOSED_BY_DSH_JSONL"
    for value in parsed.counters().values():
        assert value is None


def test_real_observed_zero_is_preserved_as_zero_not_unknown():
    parsed = DshTokenUsageParser.parse([{"type": "usage", "usage": {"input_tokens": 0, "output_tokens": 0}}])
    assert parsed.observation_status == "OBSERVED"
    assert parsed.input_tokens == 0
    assert parsed.output_tokens == 0


def test_duplicate_identical_snapshots_are_not_summed_or_double_counted():
    events = [
        {"type": "usage", "usage": {"input_tokens": 100, "output_tokens": 20}},
        {"type": "final", "usage": {"input_tokens": 100, "output_tokens": 20}},
    ]
    parsed = DshTokenUsageParser.parse(events)
    assert parsed.observation_status == "OBSERVED"
    assert parsed.input_tokens == 100
    assert parsed.output_tokens == 20
    assert parsed.usage_candidate_count == 2


def test_conflicting_snapshots_are_unknown_until_real_dsh_semantics_are_bound():
    events = [
        {"type": "usage", "usage": {"input_tokens": 100, "output_tokens": 20}},
        {"type": "final", "usage": {"input_tokens": 130, "output_tokens": 30}},
    ]
    parsed = DshTokenUsageParser.parse(events)
    assert parsed.observation_status == "UNKNOWN"
    assert parsed.unknown_reason == "MULTIPLE_CONFLICTING_USAGE_SNAPSHOTS"
    assert parsed.input_tokens is None
    assert parsed.output_tokens is None


def test_conflicting_aliases_inside_one_usage_object_are_unknown_not_guessed():
    parsed = DshTokenUsageParser.parse(
        [{"usage": {"input_tokens": 100, "prompt_tokens": 101, "output_tokens": 20}}]
    )
    assert parsed.observation_status == "UNKNOWN"
    assert parsed.unknown_reason == "CONFLICTING_TOKEN_ALIASES"
    assert parsed.input_tokens is None


def test_r1_unknown_receipt_keeps_counters_null_and_raw_jsonl_evidence():
    truth, service = _service()
    row = _observe(service, [{"type": "final", "text": "done"}])
    assert row["observation_status"] == "UNKNOWN"
    assert row["input_tokens"] is None
    assert row["output_tokens"] is None
    assert row["raw_output_ref"].endswith("ASN-1.jsonl")
    assert row["artifact_version"] == 1
    assert [name for name, _ in truth.events] == ["RC72_TOKEN_USAGE_OBSERVED"]


def test_r1_unknown_can_upgrade_to_observed_for_same_assignment():
    truth, service = _service()
    first = _observe(service, [{"type": "final", "text": "done"}])
    second = _observe(
        service,
        [{"type": "usage", "usage": {"input_tokens": 1000, "output_tokens": 200}}],
    )
    assert first["artifact_version"] == 1
    assert first["observation_status"] == "UNKNOWN"
    assert second["artifact_version"] == 2
    assert second["observation_status"] == "OBSERVED"
    assert second["input_tokens"] == 1000
    assert second["output_tokens"] == 200
    assert len(truth.events) == 2


def test_observed_receipt_is_idempotent_and_conflicting_observation_is_immutable():
    truth, service = _service()
    events = [{"type": "usage", "usage": {"input_tokens": 1000, "output_tokens": 200}}]
    first = _observe(service, events)
    replay = _observe(service, events)
    assert replay == first
    assert len(truth.events) == 1

    with pytest.raises(ContractError, match="TOKEN_USAGE_OBSERVATION_IMMUTABLE"):
        _observe(
            service,
            [{"type": "usage", "usage": {"input_tokens": 1001, "output_tokens": 200}}],
        )


def test_usage_receipt_identity_is_per_assignment_not_global_mission_counter():
    truth, service = _service()
    first = _observe(
        service,
        [{"usage": {"input_tokens": 10, "output_tokens": 2}}],
        assignment_id="ASN-1",
        attempt_id="ATT-1",
    )
    second = _observe(
        service,
        [{"usage": {"input_tokens": 20, "output_tokens": 4}}],
        assignment_id="ASN-2",
        attempt_id="ATT-2",
        raw_output_ref="file:///state/worker-evidence/MISSION-1/ASN-2.jsonl",
        dsh_session_id="session-worker-2",
    )
    assert first["token_usage_id"] != second["token_usage_id"]
    assert len(truth.events) == 2
