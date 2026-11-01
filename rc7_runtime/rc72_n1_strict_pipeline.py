"""Strict RC7.2 N1 DSH pipeline.

This is the governed N1 entry point that makes the REALITY_RECON worker capable
of satisfying the strict runtime-binding admission gate.  It keeps concerns in
order:

DSH fresh worker session -> raw evidence anchor -> strict runtime binding
admission -> inherited independent NodeGate -> canonical N1 runtime bindings.

N1 owns runtime reality only.  Request/schema and cleanup semantics remain N3/N4
responsibilities and are explicitly forbidden from the worker binding payload.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Mapping, Sequence

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.truth import TruthRuntime

from .rc72_domain import AutonomousMissionNode, MissionNodeState
from .rc72_mission_node_handoff import N1DshHandoffService
from .rc72_n1_completion import N1EvidenceAnchorService
from .rc72_n1_strict_reality_gate import N1StrictRealityGateService


_NODE = AutonomousMissionNode.N1_REALITY
_PROMPT_CONTRACT_VERSION = "rc7.2-n1-runtime-binding-v2"


class N1StrictDshHandoffService(N1DshHandoffService):
    """N1 handoff with an explicit, fail-closed executable-runtime output contract."""

    def _prompt(self, assignment: Mapping[str, Any]) -> str:
        body = {
            "contract_version": _PROMPT_CONTRACT_VERSION,
            "release_id": assignment["release_id"],
            "mission_id": assignment["mission_id"],
            "release_batch_id": assignment["release_batch_id"],
            "source_commit": self.source_commit,
            "mission_node_id": assignment["mission_node_id"],
            "workitem_id": assignment["workitem_id"],
            "input_refs": list(assignment.get("input_refs") or []),
            "authorized_tools": list(self.allowed_tools),
        }
        return (
            "You are the dsh-agent-teams REALITY_RECON_WORKER for canonical N1 Reality Recon. "
            "Use only authorized tools and inspect real deployment, environment, API route, tool route, "
            "capability and resource reality. Never guess or infer a route from naming conventions. "
            "facts.executable_bindings MUST be a non-empty list of runtime-owned bindings proven by tool evidence. "
            "Each binding MUST contain verified=true, a concrete unique binding_key, release_id, mission_id, "
            "release_batch_id, source_commit, environment{name,status=READY,source_ref}, "
            "endpoint{verified=true,url-or-endpoint-or-path,source_ref}, "
            "tool_route{verified=true,tool-or-name-or-route,source_ref}, "
            "capabilities[{name,status=READY,source_ref}], resources[{name,status=READY,source_ref}], "
            "and authoritative_sources. If any runtime fact is unknown, put it in unknowns/gaps and do not invent it. "
            "N1 MUST NOT emit request, request_schema, schema, schema_ref, contract_ref or cleanup inside a binding; "
            "those belong to N3/N4. Do not claim NodeGate PASS, Q7 PASS, field_verified or BANK_FINAL. "
            "Return strict JSON only with status='CANDIDATE', facts, unknowns and gaps. Context="
            + json.dumps(body, ensure_ascii=False, sort_keys=True)
        )


class N1StrictPipelineService:
    """Execute and close N1 through the strict runtime-binding path."""

    def __init__(
        self,
        truth: TruthRuntime,
        *,
        source_commit: str,
        launcher: DshHeadlessWorkerLauncher,
        allowed_tools: Sequence[str],
    ) -> None:
        self.truth = truth
        self.source_commit = source_commit
        self.handoff_service = N1StrictDshHandoffService(
            truth,
            source_commit=source_commit,
            launcher=launcher,
            allowed_tools=allowed_tools,
        )
        self.anchor_service = N1EvidenceAnchorService(
            truth, source_commit=source_commit
        )
        self.gate_service = N1StrictRealityGateService(
            truth, source_commit=source_commit
        )

    def _n1_state(self, release_batch_id: str) -> str:
        batches = self.truth.query(
            "rc72_release_batch", release_batch_id=release_batch_id
        )
        if len(batches) != 1:
            return ""
        mission_id = batches[0].get("mission_id")
        nodes = self.truth.query(
            "rc72_mission_node",
            mission_id=mission_id,
            node_type=_NODE.value,
        )
        if len(nodes) != 1:
            return ""
        return str(nodes[0].get("state") or "")

    def complete(self, *, release_batch_id: str) -> Dict[str, Any]:
        # A completed N1 can be replayed from canonical truth without launching a
        # second DSH session.  First execution, however, must always use the
        # strict prompt and immediately anchor the raw bytes.
        handoff: Dict[str, Any] = {"status": "RESUMED_FROM_CANONICAL_N1"}
        if self._n1_state(release_batch_id) != MissionNodeState.PASS.value:
            handoff = self.handoff_service.handoff(
                release_batch_id=release_batch_id
            )
            anchor = self.anchor_service.anchor(
                release_batch_id=release_batch_id
            )
            handoff = dict(handoff)
            handoff["evidence_anchor_id"] = anchor["anchor_id"]
            handoff["raw_output_sha256"] = anchor["raw_output_sha256"]

        completion = self.gate_service.complete(
            release_batch_id=release_batch_id
        )
        return {
            "handoff": handoff,
            "completion": completion,
            "field_verified": False,
            "bank_final": False,
        }


__all__ = [
    "N1StrictDshHandoffService",
    "N1StrictPipelineService",
]
