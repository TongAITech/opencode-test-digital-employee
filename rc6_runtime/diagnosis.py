"""RC6 Wave 10 + Execution Closure evidence-backed failure diagnosis.

A failed execution is never retried merely because a model suggests retrying and
an assertion failure is never automatically declared PRODUCT.  Failure
ownership is evidence-backed across Case/Oracle, ExecutableSpec, Script, Data,
Auth, Route, Tool, Environment and dependency state.  Attempt history remains
append-only and CAT correlation remains bounded.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from hashlib import sha256
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
    "SCRIPT",
    "SPEC",
    "ORACLE",
    "DATA",
    "PRECONDITION",
    "AUTH",
    "ROUTE",
    "TOOL",
    "ENVIRONMENT",
    "DEPENDENCY",
    "FLAKY",
    "PRODUCT",
    "TRANSIENT",
    "UNKNOWN",
    # Legacy compatibility. New execution-closure routing normalizes DESIGN to SPEC.
    "DESIGN",
}

RECOVERY_ACTIONS = {
    "REPAIR_SCRIPT",
    "REOPEN_EXECUTABLE_SPEC",
    "ORACLE_CHANGE_REQUEST",
    "RESEARCH_OR_REBUILD_DATA",
    "RECONSTRUCT_PRECONDITION",
    "REAUTH",
    "REPAIR_TOOL_BINDING",
    "RECONCILE_ROUTE_BINDING",
    "REQUALIFY_TARGET",
    "REPAIR_DEPENDENCY_BINDING",
    "CONTROLLED_REPEAT",
    "RETRY_SAME_STEP",
    "REOPEN_DESIGN",
    "PRODUCT_DEFECT",
    "BLOCKED_DIAGNOSIS",
    "MANUAL_REQUIRED",
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
    case_oracle_verified: bool = False
    executable_spec_verified: bool = False
    script_validated: bool = False
    data_verified: bool = False
    auth_verified: bool = False
    route_verified: bool = False
    tool_verified: bool = False
    environment_verified: bool = False
    dependency_verified: bool = False
    exception_type: Optional[str] = None
    root_stack_frame: Optional[str] = None
    http_status: Optional[int] = None
    business_error_code: Optional[str] = None
    route: Optional[str] = None
    assertion_identity: Optional[str] = None
    runner_log_refs: Tuple[str, ...] = ()

    def product_ownership_proven(self) -> bool:
        return all((
            self.preparation_verified,
            self.real_action_executed,
            self.assertion_failed,
            self.case_oracle_verified,
            self.executable_spec_verified,
            self.script_validated,
            self.data_verified,
            self.auth_verified,
            self.route_verified,
            self.tool_verified,
            self.environment_verified,
            self.dependency_verified,
        ))


@dataclass(frozen=True)
class FailureSignature:
    signature_id: str
    exception_type: Optional[str]
    root_stack_frame: Optional[str]
    http_status: Optional[int]
    business_error_code: Optional[str]
    route: Optional[str]
    assertion_identity: Optional[str]

    @classmethod
    def from_context(cls, context: FailureContext) -> "FailureSignature":
        stable = {
            "exception_type": context.exception_type,
            "root_stack_frame": context.root_stack_frame,
            "http_status": context.http_status,
            "business_error_code": context.business_error_code,
            "route": context.route,
            "assertion_identity": context.assertion_identity,
        }
        encoded = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        return cls(
            signature_id="FSIG-" + sha256(encoded.encode("utf-8")).hexdigest()[:24],
            **stable
        )


@dataclass(frozen=True)
class RootCauseCandidate:
    candidate_id: str
    symbol: str
    call_path: Tuple[str, ...]
    git_change_refs: Tuple[str, ...]
    requirement_refs: Tuple[str, ...]
    evidence_refs: Tuple[str, ...]
    confidence: float


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
    failure_signature: Optional[FailureSignature] = None
    root_cause_candidate: Optional[RootCauseCandidate] = None


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
    failure_signature_id: Optional[str] = None


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

    def signature_count(self, signature_id: str) -> int:
        return sum(1 for item in self.entries() if item.failure_signature_id == signature_id)

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
        rca_resolver: Optional[Callable[[FailureContext, Dict[str, Any], str], Dict[str, Any]]] = None,
    ):
        self.authority = authority
        self.tool_broker = tool_broker
        self.classifier = classifier
        self.evidence_collectors = dict(evidence_collectors or {})
        self.cat_query = cat_query
        self.cat_policy = cat_policy or CATPolicy()
        self.rca_resolver = rca_resolver

    def _authorize(self, worker_id: str, lease_id: str, attempt_id: str, cat_required: bool) -> None:
        try:
            identity = self.authority._require_identity(worker_id)
            lease = self.authority._require_lease(lease_id)
            if identity.role != "FAILURE_DIAGNOSTIC":
                raise DiagnosisContractError("FAILURE_DIAGNOSTIC_ROLE_REQUIRED")
            if str(identity.phase).upper() != "DIAGNOSIS":
                raise DiagnosisContractError("DIAGNOSIS_PHASE_REQUIRED")
            if lease.scope_ref != "attempt:%s" % attempt_id:
                raise DiagnosisContractError("DIAGNOSIS_LEASE_SCOPE_MISMATCH")
            for artifact in self.REQUIRED_ARTIFACTS:
                self.authority.authorize_artifact(worker_id, lease_id, artifact)
            if cat_required:
                self.authority.authorize_tool(worker_id, lease_id, "cat")
        except AuthorityError as exc:
            raise DiagnosisContractError(str(exc))

    @staticmethod
    def _root_cause(raw: Dict[str, Any]) -> RootCauseCandidate:
        symbol = raw.get("symbol")
        call_path = raw.get("call_path")
        git_refs = raw.get("git_change_refs")
        req_refs = raw.get("requirement_refs")
        evidence_refs = raw.get("evidence_refs")
        confidence = raw.get("confidence")
        if not isinstance(symbol, str) or not symbol:
            raise DiagnosisContractError("RCA_SYMBOL_REQUIRED")
        if not isinstance(call_path, list) or not call_path or not all(isinstance(x, str) and x for x in call_path):
            raise DiagnosisContractError("RCA_CALL_PATH_REQUIRED")
        for values, code in ((git_refs, "RCA_GIT_CHANGE_REFS_REQUIRED"), (req_refs, "RCA_REQUIREMENT_REFS_REQUIRED"), (evidence_refs, "RCA_EVIDENCE_REFS_REQUIRED")):
            if not isinstance(values, list) or not values or not all(isinstance(x, str) and x for x in values):
                raise DiagnosisContractError(code)
        if not isinstance(confidence, (int, float)) or float(confidence) < 0 or float(confidence) > 1:
            raise DiagnosisContractError("RCA_CONFIDENCE_INVALID")
        identity = json.dumps({"symbol": symbol, "call_path": call_path, "git": git_refs, "req": req_refs}, sort_keys=True)
        return RootCauseCandidate(
            candidate_id="RCA-" + sha256(identity.encode("utf-8")).hexdigest()[:24],
            symbol=symbol,
            call_path=tuple(call_path),
            git_change_refs=tuple(git_refs),
            requirement_refs=tuple(req_refs),
            evidence_refs=tuple(evidence_refs),
            confidence=float(confidence),
        )

    def diagnose(self, *, context: FailureContext, worker_id: str, lease_id: str) -> DiagnosisResult:
        if context.execution_status.upper() == "PASS":
            raise DiagnosisContractError("PASS_DOES_NOT_REQUIRE_FAILURE_DIAGNOSIS")
        if not context.execution_evidence_refs:
            raise DiagnosisContractError("EXECUTION_FAILURE_EVIDENCE_REQUIRED")
        cat_required = self.cat_policy.required(context)
        self._authorize(worker_id, lease_id, context.attempt_id, cat_required)

        evidence_refs: List[str] = list(context.execution_evidence_refs) + list(context.runner_log_refs)
        signals: Dict[str, Any] = {
            "execution_status": context.execution_status,
            "failure_signature": asdict(FailureSignature.from_context(context)),
            "ownership": {
                "case_oracle_verified": context.case_oracle_verified,
                "executable_spec_verified": context.executable_spec_verified,
                "script_validated": context.script_validated,
                "data_verified": context.data_verified,
                "auth_verified": context.auth_verified,
                "route_verified": context.route_verified,
                "tool_verified": context.tool_verified,
                "environment_verified": context.environment_verified,
                "dependency_verified": context.dependency_verified,
            },
            "sources": {},
        }
        for name, collector in sorted(self.evidence_collectors.items()):
            result = collector(context)
            if not isinstance(result, dict):
                raise DiagnosisContractError("EVIDENCE_COLLECTOR_RESULT_INVALID:%s" % name)
            ref = result.get("evidence_ref")
            if not isinstance(ref, str) or not ref:
                raise DiagnosisContractError("EVIDENCE_COLLECTOR_REF_REQUIRED:%s" % name)
            evidence_refs.append(ref)
            signals["sources"][name] = deepcopy(result.get("signals") or {})

        cat_queried = False
        if cat_required:
            self.cat_policy.validate_scope(context.correlation)
            if self.cat_query is None:
                raise DiagnosisContractError("CAT_QUERY_ADAPTER_REQUIRED")
            admission = self.tool_broker.admit(worker_id, ["cat"], context.target_id)
            if not admission.ready:
                raise DiagnosisContractError("CAT_TOOL_NOT_READY:%s" % admission.blocked.get("cat"))
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

        # PRODUCT is legal only after competing ownership classes have evidence-backed
        # exclusion. Assertion failure alone is not ownership proof.
        if failure_class == "PRODUCT" and not context.product_ownership_proven():
            raise DiagnosisContractError("PRODUCT_OWNERSHIP_EVIDENCE_INCOMPLETE")

        root_cause = None
        if self.rca_resolver is not None:
            raw_rca = self.rca_resolver(context, deepcopy(signals), failure_class)
            if not isinstance(raw_rca, dict):
                raise DiagnosisContractError("RCA_RESULT_REQUIRED")
            root_cause = self._root_cause(raw_rca)
            evidence_refs.extend(root_cause.evidence_refs)

        return DiagnosisResult(
            diagnosis_id="diag-" + uuid.uuid4().hex,
            attempt_id=context.attempt_id,
            failure_class="SPEC" if failure_class == "DESIGN" else failure_class,
            evidence_refs=tuple(dict.fromkeys(evidence_refs)),
            cat_required=cat_required,
            cat_queried=cat_queried,
            rationale=rationale,
            classifier_ref=classifier_ref,
            failure_signature=FailureSignature.from_context(context),
            root_cause_candidate=root_cause,
        )


class RecoveryEngine:
    """Decision only. Execution Closure adds RecoveryActionExecutor for side effects."""

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
        if cls == "PRODUCT":
            if not context.product_ownership_proven():
                raise DiagnosisContractError("PRODUCT_OWNERSHIP_EVIDENCE_INCOMPLETE")
            return RecoveryDecision(diagnosis.diagnosis_id, context.attempt_id, "PRODUCT_DEFECT", False, False, True, None, "EVIDENCE_BACKED_PRODUCT_FAILURE_TERMINAL")
        if cls == "ORACLE":
            return RecoveryDecision(diagnosis.diagnosis_id, context.attempt_id, "ORACLE_CHANGE_REQUEST", False, False, True, None, "ORACLE_CHANGE_REQUIRES_DESIGN_REVIEW")
        if cls == "UNKNOWN":
            return RecoveryDecision(diagnosis.diagnosis_id, context.attempt_id, "MANUAL_REQUIRED", False, False, True, None, "UNKNOWN_ROOT_CAUSE_FAIL_CLOSED")
        if cls == "TRANSIENT":
            retries = self.history.retry_count(context.attempt_id)
            if retries >= self.max_transient_retries:
                return RecoveryDecision(diagnosis.diagnosis_id, context.attempt_id, "RETRY_BUDGET_EXHAUSTED", False, False, True, None, "TRANSIENT_RETRY_LIMIT_REACHED")
            return RecoveryDecision(diagnosis.diagnosis_id, context.attempt_id, "RETRY_SAME_STEP", True, False, False, self.history.successor_id(context.attempt_id), "TRANSIENT_FAILURE")

        mapping = {
            "SCRIPT": ("REPAIR_SCRIPT", True, False),
            "SPEC": ("REOPEN_EXECUTABLE_SPEC", True, False),
            "DATA": ("RESEARCH_OR_REBUILD_DATA", True, True),
            "PRECONDITION": ("RECONSTRUCT_PRECONDITION", True, True),
            "AUTH": ("REAUTH", True, True),
            "TOOL": ("REPAIR_TOOL_BINDING", True, False),
            "ROUTE": ("RECONCILE_ROUTE_BINDING", True, False),
            "ENVIRONMENT": ("REQUALIFY_TARGET", True, False),
            "DEPENDENCY": ("REPAIR_DEPENDENCY_BINDING", True, False),
            "FLAKY": ("CONTROLLED_REPEAT", True, False),
        }
        if cls not in mapping:
            raise DiagnosisContractError("NO_RECOVERY_MAPPING_FOR_FAILURE_CLASS")
        action, retry, reprepare = mapping[cls]
        return RecoveryDecision(
            diagnosis.diagnosis_id,
            context.attempt_id,
            action,
            retry,
            reprepare,
            False,
            self.history.successor_id(context.attempt_id),
            "FAILURE_CLASS:%s" % cls,
        )

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
