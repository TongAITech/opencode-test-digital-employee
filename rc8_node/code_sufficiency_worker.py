"""Fail-closed N3 CODE_SUFFICIENCY worker.

The node evaluates an already produced CODE_ANALYSIS artifact.  It does not
promote the result to Center verification/sufficiency truth; it only emits a
node observation bound to the leased Attempt.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence

from .worker_protocol import NodeWorkerContext, NodeWorkerResult


_REQUIRED_ANALYSIS_KEYS = (
    "changed_files",
    "graph_evidence",
    "sufficiency",
)


@dataclass(frozen=True)
class CodeSufficiencyObservation:
    sufficient: bool
    missing: Sequence[str]
    source_artifact_id: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "authority": "NODE_OBSERVATION_ONLY",
            "sufficient": self.sufficient,
            "missing": list(self.missing),
            "source_artifact_id": self.source_artifact_id,
        }


class CodeSufficiencyWorker:
    """Deterministically checks the frozen N3 analysis artifact.

    The Center remains the sole authority that may accept this observation as
    verified/sufficient.  Missing or malformed evidence fails closed.
    """

    stage = "CODE_SUFFICIENCY"

    def __init__(self, center_client: Any) -> None:
        self._center = center_client

    def _analysis_artifact_id(self, context: NodeWorkerContext) -> str:
        matches = []
        for ref in context.work_item.scope_refs:
            if ref.startswith("code-analysis-artifact:"):
                value = ref.split(":", 1)[1].strip()
                if value:
                    matches.append(value)
        if len(matches) != 1:
            raise ValueError("CODE_SUFFICIENCY requires exactly one code-analysis-artifact scope ref")
        return matches[0]

    def _load_analysis(self, artifact_id: str) -> Mapping[str, Any]:
        payload = self._center.download_artifact(artifact_id)
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, Mapping):
            raise ValueError("code analysis artifact must be a JSON object")
        return payload

    @staticmethod
    def evaluate(artifact_id: str, analysis: Mapping[str, Any]) -> CodeSufficiencyObservation:
        missing = [key for key in _REQUIRED_ANALYSIS_KEYS if key not in analysis]
        changed_files = analysis.get("changed_files")
        graph_evidence = analysis.get("graph_evidence")
        sufficiency = analysis.get("sufficiency")
        if not isinstance(changed_files, list) or not changed_files:
            missing.append("changed_files:non-empty")
        if not isinstance(graph_evidence, list) or not graph_evidence:
            missing.append("graph_evidence:non-empty")
        if not isinstance(sufficiency, Mapping):
            missing.append("sufficiency:object")
        else:
            if sufficiency.get("sufficient") is not True:
                missing.append("sufficiency:sufficient=true")
            unresolved = sufficiency.get("unresolved")
            if unresolved:
                missing.append("sufficiency:unresolved-empty")
        deduped = tuple(dict.fromkeys(missing))
        return CodeSufficiencyObservation(
            sufficient=not deduped,
            missing=deduped,
            source_artifact_id=artifact_id,
        )

    def run(self, context: NodeWorkerContext) -> NodeWorkerResult:
        artifact_id = self._analysis_artifact_id(context)
        analysis = self._load_analysis(artifact_id)
        observation = self.evaluate(artifact_id, analysis)
        payload = json.dumps(observation.as_dict(), sort_keys=True).encode("utf-8")
        evidence = self._center.upload_artifact(
            context=context,
            kind="code-sufficiency-observation",
            content=payload,
            media_type="application/json",
        )
        return NodeWorkerResult(
            status="COMPLETED" if observation.sufficient else "BLOCKED",
            evidence_refs=(evidence.artifact_id,),
            summary="N3 code sufficiency observation; Center authority required",
            metadata=observation.as_dict(),
        )
