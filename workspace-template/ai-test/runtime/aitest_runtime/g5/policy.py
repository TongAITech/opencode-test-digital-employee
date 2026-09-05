"""Non-durable G5 confirmation and canonical-correlation policy."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


_HIGHEST_SEVERITIES = frozenset({"S0", "S1", "CRITICAL", "BLOCKER", "HIGHEST"})
_UNAVAILABLE = frozenset({"UNAVAILABLE", "NOT_CONFIGURED", "BLOCKED", "INVALID", "REDACTED"})


@dataclass(frozen=True)
class ConfirmationPolicyDecision:
    """Ephemeral policy classification; canonical truth remains in R2.6/R3.6."""

    mandatory_human_gate: bool
    triggers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mandatory_human_gate": self.mandatory_human_gate,
            "triggers": list(self.triggers),
            "durable": False,
        }


def classify_confirmation_policy(
    context: Mapping[str, Any],
    *,
    duplicate_decision: str | None = None,
) -> ConfirmationPolicyDecision:
    """Classify every frozen mandatory-review trigger without writing state."""

    if not isinstance(context, Mapping):
        raise ValueError("policy_context must be an object")
    severity = str(context.get("severity") or "").strip().upper()
    project_highest = str(context.get("project_highest_severity") or "").strip().upper()
    triggers: list[str] = []
    if (
        severity in _HIGHEST_SEVERITIES
        or context.get("highest_severity") is True
        or context.get("is_highest_severity") is True
        or bool(project_highest and severity == project_highest)
    ):
        triggers.append("HIGHEST_SEVERITY")
    for field, label in (
        ("security_sensitive", "SECURITY_SENSITIVE"),
        ("performance_sensitive", "PERFORMANCE_SENSITIVE"),
        ("regulatory_sensitive", "REGULATORY_SENSITIVE"),
    ):
        if context.get(field) is True:
            triggers.append(label)

    plausible_count = context.get("plausible_candidate_count")
    multiple = context.get("multiple_plausible_candidates") is True or (
        isinstance(plausible_count, int)
        and not isinstance(plausible_count, bool)
        and plausible_count > 1
    )
    critical_contradictions = context.get("critical_contradiction_refs")
    unresolved_critical = context.get("unresolved_critical_contradiction") is True or bool(
        isinstance(critical_contradictions, (list, tuple)) and critical_contradictions
    )
    if multiple and unresolved_critical:
        triggers.append("MULTIPLE_CANDIDATES_WITH_CRITICAL_CONTRADICTION")

    decision = str(duplicate_decision or context.get("duplicate_correlation_decision") or "").upper()
    if decision == "AMBIGUOUS_REVIEW_REQUIRED" or context.get("ambiguous_canonical_merge") is True:
        triggers.append("AMBIGUOUS_CANONICAL_MERGE")

    source_status = str(context.get("confirmation_source_status") or "").strip().upper()
    source_unavailable = (
        context.get("required_confirmation_source_unavailable") is True
        or context.get("required_confirmation_source_available") is False
        or (
            context.get("confirmation_source_required") is True
            and source_status in _UNAVAILABLE
        )
    )
    if source_unavailable:
        triggers.append("REQUIRED_CONFIRMATION_SOURCE_UNAVAILABLE")

    if (
        context.get("destructive_reproduction_required") is True
        or context.get("high_risk_reproduction_required") is True
        or context.get("destructive_reproduction") is True
        or context.get("high_risk_reproduction") is True
        or str(context.get("reproduction_risk") or "").upper() in {"HIGH", "DESTRUCTIVE"}
    ):
        triggers.append("HIGH_RISK_OR_DESTRUCTIVE_REPRODUCTION")
    if (
        context.get("project_confirmation_policy_required") is True
        or context.get("explicit_project_confirmation_policy") is True
        or context.get("explicit_project_policy") is True
    ):
        triggers.append("EXPLICIT_PROJECT_CONFIRMATION_POLICY")

    unique = tuple(dict.fromkeys(triggers))
    return ConfirmationPolicyDecision(bool(unique), unique)


__all__ = ["ConfirmationPolicyDecision", "classify_confirmation_policy"]
