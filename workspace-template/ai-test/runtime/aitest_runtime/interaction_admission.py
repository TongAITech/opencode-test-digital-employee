"""F53 proposal validation and effect admission over an actual host user turn.

The model proposes semantics through ``operations``; it never supplies provenance,
an authorization token, or a trusted subject. Deterministic rules below are a
conservative execution boundary, not a general natural-language classifier.
Unsupported/ambiguous instructions require one clarification, never a guessed
Mission or an unrestricted general-work side effect.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any, Mapping, Protocol, Sequence

from .durable_core import RuntimeError as DurableRuntimeError, canonical_sha256
from .r2_2.contracts import normalize_scope


class AdmissionError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class Intent(str, Enum):
    GENERAL_CHAT = "GENERAL_CHAT"
    GENERAL_QUERY = "GENERAL_QUERY"
    GENERAL_WORK = "GENERAL_WORK"
    AITEST_DIAGNOSIS = "AITEST_DIAGNOSIS"
    TEST_MISSION_START = "TEST_MISSION_START"
    MISSION_QUERY = "MISSION_QUERY"
    MISSION_UPDATE = "MISSION_UPDATE"
    MISSION_CONTROL = "MISSION_CONTROL"
    HUMAN_GATE_RESPONSE = "HUMAN_GATE_RESPONSE"


# The action, not a model-supplied 'risk' or 'approved' flag, fixes the effect.
ACTIONS = {
    Intent.GENERAL_CHAT: {"respond": "NONE"},
    Intent.GENERAL_QUERY: {"query": "READ_ONLY"},
    Intent.GENERAL_WORK: {"read": "WORKSPACE_READ", "write": "WORKSPACE_WRITE", "run": "PROCESS"},
    Intent.AITEST_DIAGNOSIS: {"diagnose": "RUNTIME_DIAGNOSIS"},
    Intent.TEST_MISSION_START: {"start": "TEST_DISPATCH"},
    Intent.MISSION_QUERY: {"query": "READ_ONLY"},
    Intent.MISSION_UPDATE: {"update": "MISSION_REVISE"},
    Intent.MISSION_CONTROL: {"continue": "TEST_DISPATCH", "pause": "PAUSE", "stop": "STOP", "detach": "DETACH_UI", "stop_runtime": "STOP_RUNTIME"},
    Intent.HUMAN_GATE_RESPONSE: {"verify": "GATE_VERIFY_ONLY"},
}
SCOPE_FIELDS = frozenset({"mode", "project_id", "version", "requirements"})
_NEGATION = re.compile(r"不要|先不|别(?:再|去|开始|测试|执行)?|无需|不(?:必|用|要|想|能)|禁止|未授权|\b(?:don't|do\s+not|never)\b", re.I)
_EXPLANATION = re.compile(r"为什么|为何|如何|怎么|介绍|解释|举例|方案|\b(?:why|how|explain|example|describe)\b", re.I)
_NON_EXECUTION_CONTEXT = re.compile(r"假设|假如|如果|例如|比如|例句|举个例子|引用|示例|转述|(?:解释|介绍).*[：:]|\b(?:if|suppose|imagine|example|hypothetical)\b", re.I)
_START = re.compile(r"^(?:(?:请|现在|立即)\s*)*(?:(?:开始|执行)\s*)?(?:测试|验证|回归|(?:start\s+)?test|verify|regress)\s*(.+)$", re.I)
_VERSION = re.compile(r"(?<![A-Za-z0-9_.-])([A-Za-z0-9][A-Za-z0-9_.-]*\d[A-Za-z0-9_.-]*)(?![A-Za-z0-9_.-])")
_CONTROL = {
    "continue": re.compile(r"^(?:请)?(?:继续|恢复)(?:这次|当前)?(?:测试|任务)?$|^(?:please\s+)?(?:continue|resume)(?:\s+(?:testing|test|mission))?$", re.I),
    "pause": re.compile(r"^(?:请)?暂停(?:这次|当前)?(?:测试|任务)?$|^(?:please\s+)?pause(?:\s+(?:testing|test|mission))?$", re.I),
    "stop": re.compile(r"^(?:请)?(?:停止|取消)(?:这次|当前)?(?:测试|任务)$|^(?:please\s+)?(?:stop|cancel)\s+(?:testing|test|mission)$", re.I),
    "detach": re.compile(r"^(?:退出|关闭)(?:界面|TUI)$|^(?:detach|close)\s+(?:ui|tui)$", re.I),
    "stop_runtime": re.compile(r"^(?:停止|关闭)\s*(?:Runtime|运行时)$|^stop\s+runtime$", re.I),
}


@dataclass(frozen=True)
class ActualHostUserTurn:
    host_session_id: str
    host_message_id: str
    host_tool_message_id: str
    parent_message_id: str | None
    text: str
    source_digest: str
    created_ms: int
    expires_ms: int

    @property
    def source_ref(self) -> str:
        from urllib.parse import quote
        return "opencode://session/" + quote(self.host_session_id, safe="") + "/message/" + quote(self.host_message_id, safe="")

    def provenance(self) -> dict[str, Any]:
        stamp = lambda value: datetime.fromtimestamp(value / 1000, timezone.utc).isoformat()
        return {"schema_version": 1, "host_session_id": self.host_session_id,
                "host_message_id": self.host_message_id, "host_tool_message_id": self.host_tool_message_id,
                "parent_message_id": self.parent_message_id, "source_ref": self.source_ref,
                "source_digest": self.source_digest, "observed_at": stamp(self.created_ms),
                "valid_until": stamp(self.expires_ms)}


@dataclass(frozen=True)
class SubjectCandidate:
    """Supplied only by a canonical owner read, never a tool argument."""
    subject_kind: str
    subject_id: str
    scope: Mapping[str, Any]
    state: str
    head_seq: int
    contextual: bool = True
    admission_blocker: str | None = None

    def ref(self) -> dict[str, str]:
        return {"subject_kind": self.subject_kind, "subject_id": self.subject_id}


@dataclass(frozen=True)
class ProposedOperation:
    intent: Intent
    action: str
    start: int
    end: int
    scope: Mapping[str, Any] = field(default_factory=dict)
    subject_id: str | None = None
    arguments: Mapping[str, Any] = field(default_factory=dict)


class SemanticProposalProvider(Protocol):
    """A real host model may implement this port; output remains untrusted."""
    def propose(self, user_text: str, clauses: Sequence[Mapping[str, Any]],
                subjects: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]: ...


class InteractionOwnerPort(Protocol):
    """Same-R1 durable adapter. Claims are receipts, never execution grants.

    Claim must compare immutable host content, canonical clause slot and request
    digest transactionally, including across subject kinds and restarts. An
    existing CLAIMED/BOUND receipt is uncertain and may not dispatch again.
    """
    def candidates(self, turn: ActualHostUserTurn) -> Sequence[SubjectCandidate]: ...
    def receipt(self, operation_id: str) -> Mapping[str, Any] | None: ...
    def claim(self, operation: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def bind(self, operation_id: str, subject: Mapping[str, str]) -> None: ...
    def complete(self, operation_id: str, result: Mapping[str, Any]) -> None: ...
    def uncertain(self, operation_id: str, reason: str) -> None: ...


def _quoted_mask(text: str) -> str:
    """Keep offsets while withholding quote/code/blockquote authority."""
    result = list(text)
    patterns = [r"```[\s\S]*?(?:```|$)", r"`[^`\n]*(?:`|$)", r'"[^"\n]*(?:"|$)',
                r"“[^”]*(?:”|$)", r"‘[^’]*(?:’|$)", r"「[^」]*(?:」|$)",
                r"『[^』]*(?:』|$)", r"(?m)^\s*>[^\n]*", r"(?<![A-Za-z])'[^'\n]*'(?![A-Za-z])"]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            result[match.start():match.end()] = " " * (match.end() - match.start())
    return "".join(result)


def clauses(text: str) -> tuple[dict[str, Any], ...]:
    # Only runtime-defined complete clauses are admissible slots; a model cannot
    # slice '测试' out of '不要测试' or manufacture new slots on a replay.
    masked = _quoted_mask(text)
    boundaries = [m.start() for m in re.finditer(r"[，,；;\n。!?！？]|/(?=另外|顺便)", masked)]
    result, start = [], 0
    for end in boundaries + [len(text)]:
        a, b = start, end
        while a < b and text[a].isspace(): a += 1
        while b > a and text[b - 1].isspace(): b -= 1
        if a < b:
            result.append({"start": a, "end": b, "text": text[a:b], "unquoted": masked[a:b]})
        start = end + 1
    return tuple(result)


def parse_proposal(value: Mapping[str, Any], turn: ActualHostUserTurn) -> tuple[ProposedOperation, ...]:
    if not isinstance(value, Mapping) or set(value) != {"operations"}:
        raise AdmissionError("SEMANTIC_PROPOSAL_SCHEMA_INVALID")
    rows = value["operations"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 8:
        raise AdmissionError("SEMANTIC_OPERATION_COUNT_INVALID")
    valid_slots = {(c["start"], c["end"]) for c in clauses(turn.text)}
    seen, result = set(), []
    for row in rows:
        if not isinstance(row, Mapping) or set(row) - {"intent", "action", "start", "end", "scope", "subject_id", "arguments"}:
            raise AdmissionError("SEMANTIC_OPERATION_SCHEMA_INVALID")
        try: intent = Intent(row["intent"])
        except (ValueError, KeyError, TypeError): raise AdmissionError("SEMANTIC_INTENT_INVALID") from None
        if row.get("action") not in ACTIONS[intent]:
            raise AdmissionError("SEMANTIC_ACTION_INVALID")
        slot = (row.get("start"), row.get("end"))
        if any(not isinstance(n, int) or isinstance(n, bool) for n in slot) or slot not in valid_slots or slot in seen:
            raise AdmissionError("HOST_COMPLETE_CLAUSE_REQUIRED")
        scope, args = row.get("scope", {}), row.get("arguments", {})
        if not isinstance(scope, Mapping) or set(scope) - SCOPE_FIELDS:
            raise AdmissionError("HOST_SCOPE_SCHEMA_INVALID")
        # Arguments are proposals for a downstream typed owner, never arbitrary
        # runner commands, raw source envelopes or authorization flags.
        if not isinstance(args, Mapping) or set(args) - {"purpose", "target", "value", "unit", "gate_id"}:
            raise AdmissionError("SEMANTIC_ARGUMENT_SCHEMA_INVALID")
        if any(not isinstance(v, str) or not v.strip() or len(v.encode()) > 1024 for v in args.values()):
            raise AdmissionError("SEMANTIC_ARGUMENT_INVALID")
        subject_id = row.get("subject_id")
        if subject_id is not None and (not isinstance(subject_id, str) or not subject_id or len(subject_id) > 256):
            raise AdmissionError("SEMANTIC_SUBJECT_INVALID")
        result.append(ProposedOperation(intent, row["action"], *slot, dict(scope), subject_id, dict(args)))
        seen.add(slot)
    if seen != valid_slots:
        raise AdmissionError("MIXED_TURN_CLAUSES_MUST_ALL_BE_ACCOUNTED_FOR")
    return tuple(result)


def _literal(value: str, text: str) -> bool:
    return bool(re.search(r"(?<![A-Za-z0-9_.-])" + re.escape(value) + r"(?![A-Za-z0-9_.-])", text))


def explicit_scope(scope: Mapping[str, Any], clause: str, *, infer_version: bool = False) -> dict[str, Any]:
    raw = dict(scope)
    if isinstance(raw.get("version"), str) and raw["version"].endswith("版本"):
        raw["version"] = raw["version"][:-2]
    if infer_version and not any(k != "mode" for k in raw):
        versions = list(dict.fromkeys(_VERSION.findall(clause)))
        if len(versions) == 1: raw["version"] = versions[0]
    raw.setdefault("mode", "EXPLICIT_SET")
    try: normalized = normalize_scope(raw)
    except DurableRuntimeError as exc: raise AdmissionError("HOST_SCOPE_SCHEMA_INVALID") from exc
    if set(normalized) - SCOPE_FIELDS:
        raise AdmissionError("HOST_SCOPE_SCHEMA_INVALID")
    if not any(k != "mode" and v for k, v in normalized.items()):
        raise AdmissionError("EMPTY_SCOPE_FORBIDDEN")
    for key, value in normalized.items():
        if key == "mode": continue
        items = value if isinstance(value, list) else [value]
        if not items or any(not isinstance(v, str) or not _literal(v, clause) for v in items):
            raise AdmissionError("HOST_SCOPE_MUST_BE_LITERAL_IN_OWN_OPERATION")
    return normalized


def resolve_subject(candidates: Sequence[SubjectCandidate], *, scope: Mapping[str, Any] | None,
                    subject_id: str | None = None, kind: str = "MISSION", include_terminal: bool = False) -> tuple[str, SubjectCandidate | None]:
    selected = [c for c in candidates if c.subject_kind == kind and (include_terminal or c.state not in {"COMPLETED", "FAILED", "CANCELLED", "STOPPED"})]
    if scope is None and subject_id is None: selected = [c for c in selected if c.contextual]
    if subject_id is not None: selected = [c for c in selected if c.subject_id == subject_id]
    if scope is not None:
        if not any(k != "mode" and v for k, v in scope.items()):
            raise AdmissionError("EMPTY_SCOPE_FORBIDDEN")
        # Do not merge partial/empty/version-prefix scopes or project aliases.
        digest = canonical_sha256(normalize_scope(scope))
        selected = [c for c in selected if canonical_sha256(normalize_scope(c.scope)) == digest]
    if len(selected) == 0: return "NONE", None
    if len(selected) == 1: return "UNIQUE", selected[0]
    return "AMBIGUOUS", None


def decide(turn: ActualHostUserTurn, operation: ProposedOperation,
           candidates: Sequence[SubjectCandidate], *, now_ms: int) -> dict[str, Any]:
    slot = next((c for c in clauses(turn.text) if (c["start"], c["end"]) == (operation.start, operation.end)), None)
    if slot is None: raise AdmissionError("HOST_COMPLETE_CLAUSE_REQUIRED")
    action, intent = operation.action, operation.intent
    # Action is deliberately absent from operation_id: reclassifying the same
    # immutable clause cannot obtain a fresh replay identity.
    operation_id = "interaction-op-" + canonical_sha256({"session": turn.host_session_id, "message": turn.host_message_id, "start": operation.start, "end": operation.end})
    proposal = {"intent": intent.value, "action": action, "start": operation.start, "end": operation.end,
                "scope": dict(operation.scope), "subject_id": operation.subject_id, "arguments": dict(operation.arguments)}
    result = {"operation_id": operation_id, "intent": intent.value, "action": action,
              "effect": ACTIONS[intent][action], "host_turn_ref": turn.provenance(),
              "request_digest": canonical_sha256({"host_content": turn.source_digest, "proposal": proposal}),
              "proposal": proposal, "status": "ADMITTED", "execution_authorized": False,
              "subject": None, "resolved_scope": None, "expected_subject_seq": None}
    def reject(reason: str, question: str | None = None) -> dict[str, Any]:
        result.update(status="CLARIFICATION_REQUIRED" if question else "DENIED", reason=reason)
        if question: result["question"] = question
        return result
    if now_ms > turn.expires_ms: return reject("HOST_USER_TURN_EXPIRED")
    unquoted = slot["unquoted"].strip()
    if intent in {Intent.GENERAL_CHAT, Intent.GENERAL_QUERY}:
        # This grant permits only an answer/query result. It grants no file,
        # process, DB/network or formal testing effect regardless of wording.
        result["status"] = "NO_MISSION"
        return result
    if not unquoted: return reject("QUOTED_TEXT_IS_NOT_EXECUTION_AUTHORITY")
    if _NEGATION.search(unquoted): return reject("NEGATED_OPERATION_IS_NOT_EXECUTION_AUTHORITY")
    if intent in {Intent.GENERAL_WORK, Intent.AITEST_DIAGNOSIS}:
        if operation.scope:
            try: explicit_scope(operation.scope, unquoted)
            except AdmissionError: return reject("HOST_SCOPE_MUST_BE_LITERAL_IN_OWN_OPERATION")
        # A semantic routing proposal is useful even before capability leases and
        # OS confinement are installed; it does not authorize actual I/O.
        result.update(status="DELEGATION_REQUIRED", reason="TYPED_WORKER_CAPABILITY_ADMISSION_REQUIRED")
        return result
    if intent != Intent.MISSION_QUERY:
        if (_NON_EXECUTION_CONTEXT.search(_quoted_mask(turn.text))
                or turn.text[operation.end:operation.end + 1] in {"?", "？"}):
            return reject("CONDITIONAL_OR_REFERENCED_OPERATION_IS_NOT_EXECUTION_AUTHORITY", "这是一个示例或条件说明，还是现在执行这项操作？")
        if _NEGATION.search(_quoted_mask(turn.text)):
            return reject("MIXED_TEST_AUTHORIZATION_CONFLICT", "请明确本次允许执行测试的范围。")
    scope = None
    if operation.scope and intent != Intent.TEST_MISSION_START:
        try: scope = explicit_scope(operation.scope, unquoted)
        except (ValueError, RuntimeError): return reject("HOST_SCOPE_NOT_EXPLICIT", "请明确这项操作的项目和版本范围。")
    if intent == Intent.TEST_MISSION_START:
        if (_EXPLANATION.search(unquoted) or not _START.fullmatch(unquoted)
                or turn.text[operation.end:operation.end + 1] in {"?", "？"}
                or re.search(r"(?:吗|么|是否|能否|可否)$", unquoted)):
            return reject("EXPLICIT_TEST_EXECUTION_REQUIRED", "这项请求是解释测试方案，还是执行该明确范围的测试？")
        try: scope = explicit_scope(operation.scope, unquoted, infer_version=True)
        except (ValueError, RuntimeError): return reject("EMPTY_OR_UNRESOLVED_TEST_SCOPE", "请给出要测试的项目版本或需求范围。")
    if operation.subject_id and not _literal(operation.subject_id, unquoted) and not any(c.subject_id == operation.subject_id and c.contextual for c in candidates):
        return reject("SUBJECT_NOT_IN_AUTHORIZED_DURABLE_CONTEXT")
    if intent == Intent.MISSION_CONTROL and action in {"detach", "stop_runtime"}:
        if not _CONTROL[action].fullmatch(unquoted): return reject("EXPLICIT_CONTROL_REQUIRED")
        result.update(status="OWNER_ADMISSION_REQUIRED", reason="RUNTIME_LIFECYCLE_OWNER_REQUIRED")
        return result
    if intent == Intent.HUMAN_GATE_RESPONSE:
        # Gate selection is global within authorized Missions, not a premature
        # unique-Mission decision. The owner replays the exact claimed Gate.
        text = unquoted
        targets = [v for k,v in (scope or {}).items() if k != "mode"]
        if operation.subject_id and _literal(operation.subject_id,text): targets.append(operation.subject_id)
        for value in targets:
            for literal in value if isinstance(value,list) else [value]:
                text = re.sub(r"(?<![A-Za-z0-9_.-])"+re.escape(literal)+r"(?![A-Za-z0-9_.-])", "", text)
        from .g4.service_r2_4 import _completion_intent
        if not _completion_intent(text): return reject("EXPLICIT_COMPLETION_REQUEST_REQUIRED")
        result.update(status="OWNER_ADMISSION_REQUIRED", reason="UNIQUE_GATE_AND_FRESH_VERIFICATION_REQUIRED",resolved_scope=scope)
        return result
    resolution, subject = resolve_subject(candidates, scope=scope, subject_id=operation.subject_id, include_terminal=intent == Intent.MISSION_QUERY)
    if resolution == "AMBIGUOUS":
        return reject("MULTIPLE_RELEVANT_SUBJECTS", "这项操作针对哪个现有任务？")
    if intent != Intent.TEST_MISSION_START and resolution == "NONE":
        return reject("NO_RELEVANT_SUBJECT", "这项操作针对哪个现有任务？")
    if operation.subject_id and subject is None:
        return reject("SUBJECT_NOT_IN_AUTHORIZED_DURABLE_CONTEXT")
    if subject and subject.admission_blocker and intent != Intent.MISSION_QUERY:
        result.update(status="BLOCKED", reason=subject.admission_blocker, subject=subject.ref())
        return result
    control_text = unquoted
    if intent == Intent.MISSION_CONTROL and scope:
        # Remove only already verified literal target values; the remaining
        # clause must still be an explicit control verb, not an explanation.
        targets = [v for k,v in scope.items() if k != "mode"]
        for value in targets:
            for literal in value if isinstance(value, list) else [value]:
                control_text = re.sub(r"(?<![A-Za-z0-9_.-])" + re.escape(literal) + r"(?![A-Za-z0-9_.-])", "", control_text)
        control_text = control_text.strip()
    if intent == Intent.MISSION_CONTROL and not _CONTROL[action].fullmatch(control_text):
        return reject("EXPLICIT_CONTROL_REQUIRED", "请明确要继续、暂停还是停止哪个任务。")
    if intent == Intent.MISSION_UPDATE:
        if _EXPLANATION.search(unquoted): return reject("EXPLANATION_IS_NOT_UPDATE_AUTHORITY")
        if "超时" in unquoted or "timeout" in unquoted.lower():
            target, value, unit = (operation.arguments.get(k) for k in ("target", "value", "unit"))
            if not all((target, value, unit)) or not all(_literal(v, unquoted) for v in (target, value, unit)):
                return reject("UPDATE_TARGET_VALUE_UNIT_REQUIRED", "要修改哪个超时设置，数值的单位是什么？")
        result.update(status="OWNER_ADMISSION_REQUIRED", reason="PLAN_REVISION_OWNER_REQUIRED")
    if intent == Intent.HUMAN_GATE_RESPONSE:
        # Never accepts '已登录' as proof. Existing Gate service must independently
        # select zero/one/many gates and verify fresh same-context observations.
        result.update(status="OWNER_ADMISSION_REQUIRED", reason="UNIQUE_GATE_AND_FRESH_VERIFICATION_REQUIRED")
    result.update(subject=subject.ref() if subject else None,
                  resolved_scope=dict(scope or (subject.scope if subject else {})),
                  expected_subject_seq=subject.head_seq if subject else None)
    return result


def literal_start_proposal(turn: ActualHostUserTurn, scope: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Compatibility proposal for the existing narrow start_test convenience API.

    Arbitrary semantic/mixed requests use the real model's operations proposal.
    This convenience does not guess their semantics or confer authorization.
    """
    parts = clauses(turn.text)
    if len(parts) != 1: raise AdmissionError("MIXED_TURN_REQUIRES_SEMANTIC_PROPOSAL")
    return {"operations": [{"intent": Intent.TEST_MISSION_START.value, "action": "start",
                            "start": parts[0]["start"], "end": parts[0]["end"], "scope": dict(scope or {})}]}


def mission_intake(turn: ActualHostUserTurn, admitted: Mapping[str, Any]) -> dict[str, Any]:
    if admitted.get("status") != "ADMITTED" or admitted.get("intent") != Intent.TEST_MISSION_START.value:
        raise AdmissionError("TEST_START_ADMISSION_REQUIRED")
    scope = admitted.get("resolved_scope") or {}
    if not any(k != "mode" and v for k, v in scope.items()): raise AdmissionError("EMPTY_SCOPE_FORBIDDEN")
    proposal = admitted["proposal"]
    own_text = turn.text[proposal["start"]:proposal["end"]]
    return {"intake_id": admitted["operation_id"], "operation": "CREATE", "scope": dict(scope),
            "goal": {"title": own_text, "intent": own_text,
                     "constraints": ["User intent is authorization input, not release, execution or coverage truth."]},
            "source": {"kind": "USER", "source_ref": turn.source_ref, "source_digest": turn.source_digest,
                       "observed_at": turn.provenance()["observed_at"], "valid_until": turn.provenance()["valid_until"], "source_precedence": 1},
            "actor": {"type": "USER", "id": "opencode-user-turn"}}
