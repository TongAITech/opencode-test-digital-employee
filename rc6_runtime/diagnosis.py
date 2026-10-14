"""RC6 Wave 10 CAT-backed failure diagnosis and bounded recovery.

A failed execution is never retried merely because a model suggests retrying.
The runtime preserves every attempt, collects evidence, requires bounded CAT
correlation where policy says CAT applies, classifies the failure, and maps the
classification to a small deterministic recovery vocabulary.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, asdict
import json
import time
import uuid
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

from .authority import AuthorityError, AuthorityRuntime
from .capability import ToolCapabilityBroker, ToolCapabilityError
from .execution import ExecutionRecord


class DiagnosisContractError(RuntimeError):
    pass


FAILURE_CLASSES = {
    "TRANSIENT",
    "DATA",
    "PRECONDITION",
    "AUTH",
    "TOOL",
    "ROUTE",
    "ENVIRONMENT",
    "DESIGN",
    "PRODUCT",
    "UNKNOWN",
}

RECOVERY_ACTIONS = {
    "RETRY_SAME_STEP",
    "RESEARCH_OR_REBUILD_DATA",
    "RECONSTRUCT_PRECONDITION",
    "REAUTH",
    "REPAIR_TOOL_BINDING",
    "RECONCILE_ROUTE_BINDING",
    "REQUALIFY_TARGET",
    "REOPEN_DESIGN",
    "PRODUCT_DEFECT",
    "BLOCKED_DIAGNOSIS",
    "RETRY_BUDGET_EXHAUSTED",
}


@dataclass(frozen=True)
class CorrelationScope:
    applications: Tuple[str, ...]
    window_start: int
    window_end: int
    request_id: Optional[str] = None
    trace_id: Optional[str] = None
    business_id: Optional[str] = None

    def identifiers(self) -> Dict[str, str]:
        return {
            k: v for k, v in {
                "request_id": self.request_id,
                "trace_id": self.trace_id,
                "business_id": self.business_id,
            }.items() if v
        }


@dataclass(frozen=True)
class FailureContext:
    attempt_id: str
    tc_id: str
    case_version: int
    target_id: str
    layer: str
    execution_status: str
    preparation_verified: bool
    real_action_executed: bool
    assertion_failed: bool
    execution_evidence_refs: Tuple[str, ...]
    correlation: Optional[CorrelationScope] = None
    remote_integration: bool = False


@dataclass(frozen=True)
class CATCorrelationResult:
    queried: bool
    tool_call_ref: Optional[str]
    evidence_ref: Optional[str]
    signals: Dict[str, Any]


@dataclass(frozen=True)
class DiagnosisResult:
    diagnosis_id: str
    attempt_id: str
    failure_class: str
    evidence_refs: Tuple[str, ...]
    cat_required: bool
    cat_queried: bool
    rationale: str
    classifier_ref: str


@dataclass(frozen=True)
class RecoveryDecision:
    diagnosis_id: str
    attempt_id: str
    action: str
    retry_allowed: bool
    reprepare_allowed: bool
    terminal: bool
    next_attempt_id: Optional[str]
    reason: str


@dataclass(frozen=True)
class AttemptHistoryEntry:
    attempt_id: str
    parent_attempt_id: Optional[str]
    tc_id: str
    case_version: int
    target_id: str
    layer: str
    status: str
    evidence_refs: Tuple[str, ...]
    recorded_at: int


class AttemptHistory:
    """Append-only attempt ledger; an attempt can never be overwritten."""

    def __init__(self):
        self._entries: Dict[str, AttemptHistoryEntry] = {}
        self._order: List[str] = []

    def append(self, entry: AttemptHistoryEntry) -> None:
        if entry.attempt_id in self._entries:
            if self._entries[entry.attempt_id] == entry:
                return
            raise DiagnosisContractError("ATTEMPT_HISTORY_IMMUTABLE")
        if entry.parent_attempt_id and entry.parent_attempt_id not in self._entries:
            raise DiagnosisContractError("PARENT_ATTEMPT_NOT_RECORDED")
        self._entries[entry.attempt_id] = entry
        self._order.append(entry.attempt_id)

    def get(self, attempt_id: str) -> Optional[AttemptHistoryEntry]:
        return self._entries.get(attempt_id)

    def entries(self) -> Tuple[AttemptHistoryEntry, ...]:
        return tuple(self._entries[x] for x in self._order)

    def retry_count(self, attempt_id: str) -> int:
        current = self._entries.get(attempt_id)
        if current is None:
            raise DiagnosisContractError("ATTEMPT_NOT_RECORDED")
        count = 0
        while current.parent_attempt_id:
            count += 1
            current = self._entries[current.parent_attempt_id]
        return count

    def successor_id(self, attempt_id: str) -> str:
        if attempt_id not in self._entries:
            raise DiagnosisContractError("ATTEMPT_NOT_RECORDED")
        return "ATT-" + uuid.uuid4().hex


class CATPolicy:
    """CAT is core for L3/L5; L1 only when it made a remote integration call."""

    def __init__(self, max_window_seconds: int = 900):
        if max_window_seconds <= 0:
            raise ValueError("max_window_seconds must be positive")
        self.max_window_seconds = int(max_window_seconds)

    def required(self, context: FailureContext) -> bool:
        layer = context.layer.upper()
        return layer in {"L3", "L5"} or (layer == "L1" and context.remote_integration)

    def validate_scope(self, scope: Optional[CorrelationScope]) -> None:
        if scope is None:
            raise DiagnosisContractError("CAT_CORRELATION_SCOPE_REQUIRED")
        if not scope.applications or any(not x for x in scope.applications):
            raise DiagnosisContractError("CAT_APPLICATION_SCOPE_REQUIRED")
        if scope.window_end < scope.window_start:
            raise DiagnosisContractError("CAT_TIME_WINDOW_INVALID")
        if scope.window_end - scope.window_start > self.max_window_seconds:
            raise DiagnosisContractError("CAT_TIME_WINDOW_TOO_WIDE")
        if not scope.identifiers():
            raise DiagnosisContractError("CAT_CORRELATION_IDENTIFIER_REQUIRED")
        serialized = json.dumps(asdict(scope), ensure_ascii=False).lower()
        for forbidden in ("password", "passwd", "secret", "token", "credential"):
            if forbidden in serialized:
                raise DiagnosisContractError("CAT_SECRET_MUST_NOT_ENTER_QUERY_SCOPE")


class DiagnosisRuntime:
    """Evidence-first diagnosis. The classifier consumes refs/signals, not secrets."""

    REQUIRED_ARTIFACTS = ("failure_diagnosis", "recovery_decision", "evidence")

    def __init__(
        self,
        *,
        authority: AuthorityRuntime,
        tool_broker: ToolCapabilityBroker,
        classifier: Callable[[FailureContext, Dict[str, Any]], Dict[str, Any]],
        evidence_collectors: Optional[Mapping[str, Callable[[FailureContext], Dict[str, Any]]]] = None,
        cat_query: Optional[Callable[[CorrelationScope, FailureContext], Dict[str, Any]]] = None,
        cat_policy: Optional[CATPolicy] = None,
    ):
        self.authority = authority
        self.tool_broker = tool_broker
        self.classifier = classifier
        self.evidence_collectors = dict(evidence_collectors or {})
        self.cat_query = cat_query
        self.cat_policy = cat_policy or CATPolicy()

    def _authorize(self, worker_id: str, lease_id: str, attempt_id: str, cat_required: bool) -> None:
        try:
            identity = self.authority._require_identity(worker_id)
            lease = self.authority._require_lease(lease_id)
            if identity.role != "FAILURE_DIAGNOSTIC":
                raise DiagnosisContractError("FAILURE_DIAGNOSTIC_ROLE_REQUIRED")
            if str(identity.phase).upper() != "DIAGNOSIS":
                raise DiagnosisContractError("DIAGNOSIS_PHASE_REQUIRED")
            if lease.scope_ref != f"attempt:{attempt_id}":
                raise DiagnosisContractError("DIAGNOSIS_LEASE_SCOPE_MISMATCH")
            for artifact in self.REQUIRED_ARTIFACTS:
                self.authority.authorize_artifact(worker_id, lease_id, artifact)
            if cat_required:
                self.authority.authorize_tool(worker_id, lease_id, "cat")
        except AuthorityError as exc:
            raise DiagnosisContractError(str(exc))

    def diagnose(self, *, context: FailureContext, worker_id: str, lease_id: str) -> DiagnosisResult:
        if context.execution_status.upper() == "PASS":
            raise DiagnosisContractError("PASS_DOES_NOT_REQUIRE_FAILURE_DIAGNOSIS")
        if not context.execution_evidence_refs:
            raise DiagnosisContractError("EXECUTION_FAILURE_EVIDENCE_REQUIRED")
        cat_required = self.cat_policy.required(context)
        self._authorize(worker_id, lease_id, context.attempt_id, cat_required)

        evidence_refs: List[str] = list(context.execution_evidence_refs)
        signals: Dict[str, Any] = {"execution_status": context.execution_status, "sources": {}}
        for name, collector in sorted(self.evidence_collectors.items()):
            result = collector(context)
            if not isinstance(result, dict):
                raise DiagnosisContractError(f"EVIDENCE_COLLECTOR_RESULT_INVALID:{name}")
            ref = result.get("evidence_ref")
            if not isinstance(ref, str) or not ref:
                raise DiagnosisContractError(f"EVIDENCE_COLLECTOR_REF_REQUIRED:{name}")
            evidence_refs.append(ref)
            signals["sources"][name] = deepcopy(result.get("signals") or {})

        cat_queried = False
        if cat_required:
            self.cat_policy.validate_scope(context.correlation)
            if self.cat_query is None:
                raise DiagnosisContractError("CAT_QUERY_ADAPTER_REQUIRED")
            admission = self.tool_broker.admit(worker_id, ["cat"], context.target_id)
            if not admission.ready:
                raise DiagnosisContractError(f"CAT_TOOL_NOT_READY:{admission.blocked.get('cat')}")
            raw = self.cat_query(context.correlation, context)
            if not isinstance(raw, dict):
                raise DiagnosisContractError("CAT_QUERY_RESULT_REQUIRED")
            call_ref = raw.get("tool_call_ref")
            evidence_ref = raw.get("evidence_ref")
            if not isinstance(call_ref, str) or not call_ref or not isinstance(evidence_ref, str) or not evidence_ref:
                raise DiagnosisContractError("CAT_QUERY_EVIDENCE_REQUIRED")
            try:
                self.tool_broker.record_tool_call(
                    "cat", worker_id=worker_id, target_id=context.target_id,
                    call_ref=call_ref, evidence_ref=evidence_ref,
                )
            except ToolCapabilityError as exc:
                raise DiagnosisContractError(str(exc))
            cat_queried = True
            evidence_refs.append(evidence_ref)
            signals["cat"] = deepcopy(raw.get("signals") or {})
            # Never persist credentials returned accidentally by an adapter.
            lowered = json.dumps(signals["cat"], ensure_ascii=False).lower()
            if any(k in lowered for k in ("password", "passwd", "secret", "token", "credential")):
                raise DiagnosisContractError("CAT_SECRET_DETECTED_IN_DIAGNOSIS_SIGNAL")

        classified = self.classifier(context, deepcopy(signals))
        if not isinstance(classified, dict):
            raise DiagnosisContractError("CLASSIFIER_RESULT_REQUIRED")
        failure_class = str(classified.get("failure_class", "")).upper()
        if failure_class not in FAILURE_CLASSES:
            raise DiagnosisContractError("INVALID_FAILURE_CLASS")
        classifier_ref = classified.get("classifier_ref")
        rationale = classified.get("rationale")
        class_evidence = classified.get("evidence_refs", [])
        if not isinstance(classifier_ref, str) or not classifier_ref:
            raise DiagnosisContractError("CLASSIFIER_REF_REQUIRED")
        if not isinstance(rationale, str) or not rationale:
            raise DiagnosisContractError("CLASSIFIER_RATIONALE_REQUIRED")
        if not isinstance(class_evidence, list):
            raise DiagnosisContractError("CLASSIFIER_EVIDENCE_SHAPE_INVALID")
        evidence_refs.extend(str(x) for x in class_evidence if isinstance(x, str) and x)

        # A verified real product assertion failure is not allowed to be relabeled
        # as transient/data/etc. to manufacture a future PASS.
        if context.preparation_verified and context.real_action_executed and context.assertion_failed:
            if failure_class != "PRODUCT":
                raise DiagnosisContractError("VALID_PRODUCT_ASSERTION_FAILURE_MUST_BE_PRODUCT")

        return DiagnosisResult(
            diagnosis_id="diag-" + uuid.uuid4().hex,
            attempt_id=context.attempt_id,
            failure_class=failure_class,
            evidence_refs=tuple(dict.fromkeys(evidence_refs)),
            cat_required=cat_required,
            cat_queried=cat_queried,
            rationale=rationale,
            classifier_ref=classifier_ref,
        )


class RecoveryEngine:
    def __init__(self, history: AttemptHistory, max_transient_retries: int = 2):
        if max_transient_retries < 0:
            raise ValueError("max_transient_retries must be >= 0")
        self.history = history
        self.max_transient_retries = max_transient_retries

    def decide(self, context: FailureContext, diagnosis: DiagnosisResult) -> RecoveryDecision:
        if diagnosis.attempt_id != context.attempt_id:
            raise DiagnosisContractError("DIAGNOSIS_ATTEMPT_MISMATCH")
        if self.history.get(context.attempt_id) is None:
            raise DiagnosisContractError("ATTEMPT_NOT_RECORDED")
        if diagnosis.cat_required and not diagnosis.cat_queried:
            return RecoveryDecision(diagnosis.diagnosis_id, context.attempt_id, "BLOCKED_DIAGNOSIS", False, False, False, None, "CAT_REQUIRED_BEFORE_RECOVERY")

        cls = diagnosis.failure_class
        if context.preparation_verified and context.real_action_executed and context.assertion_failed:
            if cls != "PRODUCT":
                raise DiagnosisContractError("PRODUCT_FAILURE_CLASSIFICATION_REQUIRED")
            return RecoveryDecision(diagnosis.diagnosis_id, context.attempt_id, "PRODUCT_DEFECT", False, False, True, None, "VALID_PRODUCT_FAILURE_TERMINAL")

        if cls == "TRANSIENT":
            retries = self.history.retry_count(context.attempt_id)
            if retries >= self.max_transient_retries:
                return RecoveryDecision(diagnosis.diagnosis_id, context.attempt_id, "RETRY_BUDGET_EXHAUSTED", False, False, False, None, "TRANSIENT_RETRY_LIMIT_REACHED")
            return RecoveryDecision(diagnosis.diagnosis_id, context.attempt_id, "RETRY_SAME_STEP", True, False, False, self.history.successor_id(context.attempt_id), "TRANSIENT_FAILURE")
        mapping = {
            "DATA": ("RESEARCH_OR_REBUILD_DATA", False, True),
            "PRECONDITION": ("RECONSTRUCT_PRECONDITION", False, True),
            "AUTH": ("REAUTH", False, True),
            "TOOL": ("REPAIR_TOOL_BINDING", False, False),
            "ROUTE": ("RECONCILE_ROUTE_BINDING", False, False),
            "ENVIRONMENT": ("REQUALIFY_TARGET", False, False),
            "DESIGN": ("REOPEN_DESIGN", False, False),
            "PRODUCT": ("PRODUCT_DEFECT", False, False),
            "UNKNOWN": ("BLOCKED_DIAGNOSIS", False, False),
        }
        action, retry, reprepare = mapping[cls]
        terminal = cls == "PRODUCT"
        next_attempt = self.history.successor_id(context.attempt_id) if reprepare else None
        return RecoveryDecision(diagnosis.diagnosis_id, context.attempt_id, action, retry, reprepare, terminal, next_attempt, f"FAILURE_CLASS:{cls}")

    def record_successor(self, decision: RecoveryDecision, prior: AttemptHistoryEntry, *, status: str = "PLANNED") -> AttemptHistoryEntry:
        if not decision.next_attempt_id:
            raise DiagnosisContractError("RECOVERY_HAS_NO_SUCCESSOR_ATTEMPT")
        entry = AttemptHistoryEntry(
            attempt_id=decision.next_attempt_id,
            parent_attempt_id=prior.attempt_id,
            tc_id=prior.tc_id,
            case_version=prior.case_version,
            target_id=prior.target_id,
            layer=prior.layer,
            status=status,
            evidence_refs=(),
            recorded_at=int(time.time()),
        )
        self.history.append(entry)
        return entry


def history_entry_from_execution(record: ExecutionRecord, recorded_at: Optional[int] = None) -> AttemptHistoryEntry:
    return AttemptHistoryEntry(
        attempt_id=record.attempt_id,
        parent_attempt_id=None,
        tc_id=record.tc_id,
        case_version=record.case_version,
        target_id=record.target_id,
        layer=record.layer,
        status=record.status,
        evidence_refs=record.evidence_refs,
        recorded_at=int(time.time()) if recorded_at is None else int(recorded_at),
    )
