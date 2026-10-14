"""R1-backed proof reader for real DSH worker activity.

Semantic worker payloads are proposals, not proof that a tool was executed.
This module reads the inherited R1 Event Stream and exposes only tool calls that
were emitted by the DSH launcher for the exact Mission and Worker identity.
Node evaluators can therefore bind their semantic claims to real runtime calls
without trusting model-authored `tool_calls` arrays.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Tuple

from rc6_runtime.truth import TruthRuntime


class DshProofError(RuntimeError):
    pass


@dataclass(frozen=True)
class DshToolCallProof:
    event_id: str
    worker_instance_id: str
    tool_name: str
    call_ref: str


def _normalized_tool_name(value: str) -> str:
    return value.strip().lower().replace("-", "_")


def code_tool_category(tool_name: str) -> str:
    """Map a real DSH tool name to the deterministic Code gate category."""
    name = _normalized_tool_name(tool_name)
    if "codegraph" in name:
        return "codegraph"
    # GitNexus is a graph/index tool, not proof of a Git revision/diff command.
    # Do not let the substring "git" accidentally satisfy the Git evidence gate.
    if "gitnexus" in name:
        return "gitnexus"
    if name == "git" or name.startswith("git_") or "__git_" in name or "_git_" in name:
        return "git"
    return "other"


class DshR1ProofReader:
    def tool_calls(
        self,
        truth: TruthRuntime,
        *,
        mission_id: str,
        worker_instance_id: str,
    ) -> Tuple[DshToolCallProof, ...]:
        if not mission_id or not worker_instance_id:
            raise DshProofError("DSH_PROOF_IDENTITY_REQUIRED")
        proofs = []
        seen = set()
        for event in truth.store.iter_raw():
            if event.get("event_type") != "WORKER_TOOL_CALLED":
                continue
            payload = event.get("payload")
            if not isinstance(payload, dict):
                continue
            if payload.get("mission_id") != mission_id:
                continue
            if payload.get("worker_instance_id") != worker_instance_id:
                continue
            tool_call = payload.get("tool_call")
            if not isinstance(tool_call, dict):
                raise DshProofError("DSH_TOOL_CALL_EVENT_SHAPE_INVALID")
            tool_name = tool_call.get("tool_name")
            call_ref = tool_call.get("call_ref")
            event_id = event.get("event_id")
            if not isinstance(tool_name, str) or not tool_name.strip():
                raise DshProofError("DSH_TOOL_CALL_NAME_MISSING")
            if not isinstance(call_ref, str) or not call_ref.strip():
                raise DshProofError("DSH_TOOL_CALL_REF_MISSING")
            if not isinstance(event_id, str) or not event_id.strip():
                raise DshProofError("DSH_TOOL_CALL_EVENT_ID_MISSING")
            identity = (event_id, call_ref)
            if identity in seen:
                continue
            seen.add(identity)
            proofs.append(
                DshToolCallProof(
                    event_id=event_id.strip(),
                    worker_instance_id=worker_instance_id,
                    tool_name=tool_name.strip(),
                    call_ref=call_ref.strip(),
                )
            )
        return tuple(proofs)

    def code_tool_calls(
        self,
        truth: TruthRuntime,
        *,
        mission_id: str,
        worker_instance_id: str,
    ) -> Dict[str, Tuple[DshToolCallProof, ...]]:
        grouped = {"git": [], "codegraph": [], "gitnexus": [], "other": []}
        for proof in self.tool_calls(
            truth,
            mission_id=mission_id,
            worker_instance_id=worker_instance_id,
        ):
            grouped[code_tool_category(proof.tool_name)].append(proof)
        return {key: tuple(value) for key, value in grouped.items()}
