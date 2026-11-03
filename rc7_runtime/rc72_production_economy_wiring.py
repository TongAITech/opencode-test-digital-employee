"""C10: bind model-economy accounting to the real DSH process boundary.

The RC7.2 Mission Factory requires *native launcher instances*, not proxies.
This opt-in, instance-local adapter preserves those types (including native N1
launchers) and meters the final "--json" prompt actually handed to DSH, after
any native input-read/auth prefix has been applied.

Call once per role launcher, before dispatching its first assignment. A group's
product composer must explicitly install this adapter on every model role.
"""
from __future__ import annotations

import contextvars
from typing import Any, Callable, Dict, Mapping, Optional

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher

from .rc72_model_economy import (
    DshTokenUsage,
    MissionCriticality,
    ModelCallClass,
    SemanticCostClass,
    TokenEconomyError,
    TokenEconomyService,
    extract_dsh_token_usage,
)
from .rc72_model_usage import TokenUsageAuditService
from .rc72_model_usage_worker_bridge import Rc72TokenUsageLauncherProxy


class ProductionEconomyBindingError(RuntimeError):
    pass


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProductionEconomyBindingError("RC72_ECONOMY_%s_REQUIRED" % name.upper())
    return value.strip()


def bind_production_model_economy(
    launcher: DshHeadlessWorkerLauncher,
    *,
    economy: TokenEconomyService,
    usage_audit: TokenUsageAuditService,
    metadata_resolver: Callable[[Any], Mapping[str, Any]],
) -> DshHeadlessWorkerLauncher:
    """Instrument the concrete launcher without replacing its identity/type.

    One assignment owns one ContextVar slot. This keeps concurrent assignments
    from sharing lineage even when the same launcher is used by two threads.
    The command runner is the authoritative model-call boundary: no pre-native
    prompt approximation is billed or fingerprinted. No guessed tokens are used.
    """
    if not isinstance(launcher, DshHeadlessWorkerLauncher):
        raise ProductionEconomyBindingError("RC72_ECONOMY_NATIVE_DSH_LAUNCHER_REQUIRED")
    if not isinstance(economy, TokenEconomyService) or not isinstance(usage_audit, TokenUsageAuditService):
        raise ProductionEconomyBindingError("RC72_ECONOMY_CANONICAL_AUDITS_REQUIRED")
    if not callable(metadata_resolver):
        raise ProductionEconomyBindingError("RC72_ECONOMY_METADATA_RESOLVER_REQUIRED")
    if (
        economy.truth is not launcher.truth
        or usage_audit.truth is not launcher.truth
        or economy.release_id != launcher.release_id
        or usage_audit.release_id != launcher.release_id
    ):
        raise ProductionEconomyBindingError("RC72_ECONOMY_LEDGER_OR_RELEASE_MISMATCH")
    if getattr(launcher, "_rc72_production_economy_bound", False):
        raise ProductionEconomyBindingError("RC72_ECONOMY_DUPLICATE_BINDING_FORBIDDEN")
    if not callable(launcher.command_runner) or not callable(launcher.execute):
        raise ProductionEconomyBindingError("RC72_ECONOMY_DSH_RUNTIME_HOOK_MISSING")

    current_assignment = contextvars.ContextVar("rc72_economy_assignment_%s" % id(launcher), default=None)
    original_execute = launcher.execute
    original_runner = launcher.command_runner
    original_persist = launcher._persist_raw_worker_output

    def execute(assignment: Any, prompt: str) -> Any:
        if getattr(assignment, "mission_id", None) is None:
            raise ProductionEconomyBindingError("RC72_ECONOMY_CANONICAL_ASSIGNMENT_REQUIRED")
        token = current_assignment.set(assignment)
        try:
            return original_execute(assignment, prompt)
        finally:
            current_assignment.reset(token)

    def runner(command: Any, **kwargs: Any) -> Any:
        assignment = current_assignment.get()
        if assignment is None:
            raise ProductionEconomyBindingError("RC72_ECONOMY_UNBOUND_DSH_PROCESS_FORBIDDEN")
        if (
            not isinstance(command, (tuple, list))
            or "--json" not in command
            or not command
            or not isinstance(command[-1], str)
        ):
            raise ProductionEconomyBindingError("RC72_ECONOMY_FINAL_DSH_PROMPT_REQUIRED")

        metadata = metadata_resolver(assignment)
        if not isinstance(metadata, Mapping):
            raise ProductionEconomyBindingError("RC72_ECONOMY_METADATA_INVALID")
        metadata = dict(metadata)
        mission_id = _required(getattr(assignment, "mission_id", None), "mission_id")
        attempt_id = _required(getattr(assignment, "attempt_id", None), "attempt_id")
        agent_id = _required(getattr(assignment, "agent_id", None), "agent_id")
        for name, actual in (("mission_id", mission_id), ("attempt_id", attempt_id), ("agent_id", agent_id)):
            if name in metadata and metadata[name] != actual:
                raise ProductionEconomyBindingError("RC72_ECONOMY_%s_LINEAGE_MISMATCH" % name.upper())
        node = _required(metadata.get("node"), "node")
        stage = _required(metadata.get("stage"), "stage")
        workitem_id = _required(metadata.get("workitem_id"), "workitem_id")
        retry = metadata.get("retry", False)
        if not isinstance(retry, bool):
            raise ProductionEconomyBindingError("RC72_ECONOMY_RETRY_FLAG_INVALID")
        raw_class = metadata.get("call_class", ModelCallClass.LLM_REQUIRED)
        raw_criticality = metadata.get("mission_criticality", MissionCriticality.UNKNOWN)
        raw_cost = metadata.get("semantic_cost_class", SemanticCostClass.UNKNOWN)
        call_class = raw_class if isinstance(raw_class, ModelCallClass) else ModelCallClass(str(raw_class).upper())
        criticality = raw_criticality if isinstance(raw_criticality, MissionCriticality) else MissionCriticality(str(raw_criticality).upper())
        cost = raw_cost if isinstance(raw_cost, SemanticCostClass) else SemanticCostClass(str(raw_cost).upper())

        admission = economy.admit_call(
            mission_id=mission_id,
            node=node,
            stage=stage,
            workitem_id=workitem_id,
            attempt_id=attempt_id,
            agent_id=agent_id,
            call_class=call_class,
            retry=retry,
            prompt=command[-1],
            mission_criticality=criticality,
            semantic_cost_class=cost,
        )
        if not admission.admitted:
            raise TokenEconomyError("TOKEN_CALL_BLOCKED:%s:%s" % (admission.call_id, admission.reason))
        try:
            proc = original_runner(command, **kwargs)
        except Exception:
            # A process exception cannot establish actual provider usage.
            economy.complete_call(
                admission.call_id, DshTokenUsage.unknown("DSH_PROCESS_EXCEPTION_USAGE_UNKNOWN"),
                process_outcome="RAISED",
            )
            raise
        stdout = getattr(proc, "stdout", None)
        usage = (
            extract_dsh_token_usage(stdout)
            if isinstance(stdout, str)
            else DshTokenUsage.unknown("DSH_PROCESS_STDOUT_NOT_AVAILABLE")
        )
        economy.complete_call(admission.call_id, usage, process_outcome="RETURNED")
        return proc

    def persist(assignment: Any, stdout: str, stderr: str) -> str:
        raw_ref = original_persist(assignment, stdout, stderr)
        events = Rc72TokenUsageLauncherProxy._read_events(raw_ref)
        if Rc72TokenUsageLauncherProxy._has_model_call_signal(events):
            # The native launcher may not have parsed the session yet. Unknown
            # session remains null, never a fabricated session identifier.
            session = None
            for event in events:
                if event.get("type") in {"session", "session.created"}:
                    candidate = event.get("session_id") or event.get("id")
                    if isinstance(candidate, str) and candidate.strip():
                        session = candidate.strip()
            usage_audit.observe(
                mission_id=_required(getattr(assignment, "mission_id", None), "mission_id"),
                attempt_id=_required(getattr(assignment, "attempt_id", None), "attempt_id"),
                assignment_id=_required(getattr(assignment, "assignment_id", None), "assignment_id"),
                raw_output_ref=raw_ref,
                events=events,
                dsh_session_id=session,
            )
        return raw_ref

    launcher.execute = execute
    launcher.command_runner = runner
    launcher._persist_raw_worker_output = persist
    launcher._rc72_production_economy_bound = True
    return launcher
