"""Fail-closed N3 CODE_SUFFICIENCY policy primitive.

This module intentionally contains no Center-authority write path.  The node
may evaluate a frozen CODE_ANALYSIS artifact, but Center remains the sole
verification/sufficiency authority.  Dispatcher/lease integration is a
separate adoption slice so a policy helper cannot be mistaken for autonomous
readiness.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Sequence


_REQUIRED_ANALYSIS_KEYS = ("changed_files", "graph_evidence", "sufficiency")


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


class CodeSufficiencyPolicy:
    """Deterministically reject incomplete CODE_ANALYSIS evidence."""

    version = "rc8.code-sufficiency.v1"

    @staticmethod
    def evaluate(artifact_id: str, analysis: Mapping[str, Any]) -> CodeSufficiencyObservation:
        if not artifact_id.strip():
            raise ValueError("CODE_ANALYSIS_ARTIFACT_ID_REQUIRED")
        if not isinstance(analysis, Mapping):
            raise ValueError("CODE_ANALYSIS_ARTIFACT_OBJECT_REQUIRED")

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
            if sufficiency.get("unresolved"):
                missing.append("sufficiency:unresolved-empty")

        deduped = tuple(dict.fromkeys(missing))
        return CodeSufficiencyObservation(
            sufficient=not deduped,
            missing=deduped,
            source_artifact_id=artifact_id,
        )
