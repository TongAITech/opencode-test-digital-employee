"""RC7.2 N3 aggregate R1 replay correction.

`DshR1ProofReader` deliberately binds canonical tool Evidence to the immutable
outer R1 `event_id`, not to the projected agent-runtime payload `id`.  The first
N3 aggregate implementation attempted to resolve that outer id through the
payload projection and therefore rejected valid real Git/CodeGraph proof.

Keep the distinction explicit here: Evidence -> r1-event://<outer event_id> is
verified by replaying the raw R1 stream and then validating the embedded
WORKER_TOOL_CALLED payload.  No semantic candidate field can satisfy this gate.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from .dsh_proof import code_tool_category
from .rc72_n3_completion import N3DeliveryGateService


_INSTALLED = False


def _real_analyzer_tool_proof_from_raw_r1(
    self: N3DeliveryGateService,
    *,
    mission_id: str,
    analyzer_id: str,
    task_id: str,
    artifact_id: str,
    target_id: str,
    evidence_rows: Sequence[Mapping[str, Any]],
    category: str,
) -> bool:
    expected_kind = "DSH_%s_TOOL_CALL_PROOF" % category.upper()
    proofs = [row for row in evidence_rows if row.get("kind") == expected_kind]
    if not proofs:
        return False

    raw_events = {}
    for event in self.truth.store.iter_raw():
        event_id = event.get("event_id")
        if isinstance(event_id, str) and event_id:
            raw_events[event_id] = event

    for proof in proofs:
        subjects = list(proof.get("subject_refs") or [])
        if not all(value in subjects for value in (task_id, artifact_id, target_id)):
            continue
        source_ref = str(proof.get("source_ref") or "")
        if not source_ref.startswith("r1-event://"):
            continue
        outer_event_id = source_ref[len("r1-event://"):]
        raw = raw_events.get(outer_event_id)
        if not isinstance(raw, Mapping):
            continue
        if raw.get("event_type") != "WORKER_TOOL_CALLED":
            continue
        payload = raw.get("payload")
        if not isinstance(payload, Mapping):
            continue
        if (
            payload.get("mission_id") != mission_id
            or payload.get("event_name") != "WORKER_TOOL_CALLED"
            or payload.get("worker_instance_id") != analyzer_id
        ):
            continue
        tool_call = payload.get("tool_call")
        if not isinstance(tool_call, Mapping):
            continue
        if code_tool_category(str(tool_call.get("tool_name") or "")) == category:
            return True
    return False


def install_rc72_n3_completion_r1_replay() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    N3DeliveryGateService._real_analyzer_tool_proof = _real_analyzer_tool_proof_from_raw_r1
    _INSTALLED = True


__all__ = ["install_rc72_n3_completion_r1_replay"]
