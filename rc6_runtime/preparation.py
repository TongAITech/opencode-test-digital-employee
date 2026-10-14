"""RC6 Wave 8 deterministic precondition and test-data runtime.

Preparation is a governed phase before real execution. A frozen Case is parsed
into explicit preconditions and data requirements. Data is searched/reused
before construction, every selected binding is verified, and the final binding
is immutable for one execution attempt.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


class PreparationContractError(RuntimeError):
    pass


PRECONDITION_TYPES = {"ENVIRONMENT", "AUTH", "BUSINESS_STATE", "DATA", "DEPENDENCY"}
STRATEGY_ORDER = (
    "REUSE_EXISTING",
    "DERIVE",
    "API_CREATE",
    "UI_CREATE",
    "DB_CREATE",
    "FIXTURE",
    "MOCK",
)
CLEANUP_MODES = {"NONE", "ROLLBACK", "DELETE", "RESTORE"}
FAILURE_CLASSES = {
    "TRANSIENT", "AUTH", "DATA", "PRECONDITION", "TOOL", "ROUTE",
    "ENVIRONMENT", "DESIGN", "PRODUCT",
}


@dataclass(frozen=True)
class PreparationPlan:
    tc_id: str
    case_version: int
    layer: str
    preconditions: Tuple[Dict[str, Any], ...]
    initial_state_requirements: Tuple[Dict[str, Any], ...]
    input_data_requirements: Tuple[Dict[str, Any], ...]
    cleanup_policy: Dict[str, Any]
    oracle_snapshot: Dict[str, Any]


@dataclass(frozen=True)
class PreparedAttempt:
    status: str
    attempt_id: str
    tc_id: str
    case_version: int
    target_id: str
    precondition_evidence: Tuple[str, ...]
    initial_state_bindings: Dict[str, Any]
    input_data_bindings: Dict[str, Any]
    binding_evidence: Tuple[str, ...]
    cleanup_policy: Dict[str, Any]
    oracle_snapshot: Dict[str, Any]


@dataclass(frozen=True)
class RecoveryDecision:
    action: str
    retry_allowed: bool
    reprepare_allowed: bool
    terminal_product_failure: bool


class PreparationSpecParser:
    @staticmethod
    def _data_requirement(raw: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(raw, dict):
            raise PreparationContractError("INVALID_DATA_REQUIREMENT")
        rid = raw.get("id")
        if not isinstance(rid, str) or not rid.strip():
            raise PreparationContractError("DATA_REQUIREMENT_ID_REQUIRED")
        selectors = raw.get("selectors")
        if not isinstance(selectors, dict) or not selectors:
            raise PreparationContractError("DATA_SELECTORS_REQUIRED")
        allowed = raw.get("allowed_strategies", list(STRATEGY_ORDER))
        if not isinstance(allowed, list) or not allowed:
            raise PreparationContractError("ALLOWED_STRATEGIES_REQUIRED")
        normalized = [str(x).upper() for x in allowed]
        if any(x not in STRATEGY_ORDER for x in normalized):
            raise PreparationContractError("UNKNOWN_DATA_STRATEGY")
        out = deepcopy(raw)
        out["id"] = rid.strip()
        out["allowed_strategies"] = normalized
        return out

    def parse(self, case: Dict[str, Any]) -> PreparationPlan:
        if not isinstance(case, dict):
            raise PreparationContractError("CASE_REQUIRED")
        if str(case.get("status", "")).upper() != "FROZEN":
            raise PreparationContractError("CASE_MUST_BE_FROZEN_BEFORE_PREPARATION")
        tc_id = case.get("tc_id")
        version = case.get("case_version")
        layer = str(case.get("layer", "")).upper()
        if not isinstance(tc_id, str) or not tc_id.strip():
            raise PreparationContractError("TC_ID_REQUIRED")
        if not isinstance(version, int) or version < 1:
            raise PreparationContractError("CASE_VERSION_REQUIRED")
        if layer not in {f"L{i}" for i in range(1, 8)}:
            raise PreparationContractError("VALID_LAYER_REQUIRED")

        preconditions = case.get("preconditions")
        if not isinstance(preconditions, list):
            raise PreparationContractError("PRECONDITIONS_REQUIRED")
        normalized_preconditions = []
        seen_pre = set()
        for raw in preconditions:
            if not isinstance(raw, dict):
                raise PreparationContractError("STRUCTURED_PRECONDITION_REQUIRED")
            pid = raw.get("id")
            ptype = str(raw.get("type", "")).upper()
            requirement = raw.get("requirement")
            if not isinstance(pid, str) or not pid.strip() or pid in seen_pre:
                raise PreparationContractError("INVALID_PRECONDITION_ID")
            if ptype not in PRECONDITION_TYPES:
                raise PreparationContractError("INVALID_PRECONDITION_TYPE")
            if not isinstance(requirement, str) or not requirement.strip():
                raise PreparationContractError("PRECONDITION_REQUIREMENT_REQUIRED")
            seen_pre.add(pid)
            item = deepcopy(raw)
            item["id"] = pid.strip()
            item["type"] = ptype
            normalized_preconditions.append(item)

        test_data = case.get("test_data")
        if not isinstance(test_data, dict):
            raise PreparationContractError("STRUCTURED_TEST_DATA_REQUIRED")
        initial = test_data.get("initial_state", [])
        inputs = test_data.get("input_data", [])
        if not isinstance(initial, list) or not isinstance(inputs, list):
            raise PreparationContractError("INITIAL_AND_INPUT_DATA_LISTS_REQUIRED")
        initial_req = tuple(self._data_requirement(x) for x in initial)
        input_req = tuple(self._data_requirement(x) for x in inputs)
        all_ids = [x["id"] for x in initial_req + input_req]
        if len(all_ids) != len(set(all_ids)):
            raise PreparationContractError("DUPLICATE_DATA_REQUIREMENT_ID")

        cleanup = test_data.get("cleanup_policy", {"mode": "NONE"})
        if not isinstance(cleanup, dict):
            raise PreparationContractError("CLEANUP_POLICY_REQUIRED")
        mode = str(cleanup.get("mode", "")).upper()
        if mode not in CLEANUP_MODES:
            raise PreparationContractError("INVALID_CLEANUP_MODE")
        cleanup = deepcopy(cleanup)
        cleanup["mode"] = mode

        oracle = case.get("oracle")
        if not isinstance(oracle, dict) or not oracle:
            raise PreparationContractError("ORACLE_MUST_EXIST_BEFORE_PREPARATION")

        return PreparationPlan(
            tc_id=tc_id.strip(),
            case_version=version,
            layer=layer,
            preconditions=tuple(normalized_preconditions),
            initial_state_requirements=initial_req,
            input_data_requirements=input_req,
            cleanup_policy=cleanup,
            oracle_snapshot=deepcopy(oracle),
        )


class AttemptBindingStore:
    """Immutable prepared bindings keyed by attempt id."""

    def __init__(self):
        self._bindings: Dict[str, PreparedAttempt] = {}

    def bind(self, prepared: PreparedAttempt) -> PreparedAttempt:
        existing = self._bindings.get(prepared.attempt_id)
        if existing is not None:
            if existing != prepared:
                raise PreparationContractError("ATTEMPT_BINDING_IMMUTABLE")
            return existing
        self._bindings[prepared.attempt_id] = prepared
        return prepared

    def get(self, attempt_id: str) -> Optional[PreparedAttempt]:
        return self._bindings.get(attempt_id)


class PreparationRuntime:
    """Resolve -> search/build -> verify -> immutable bind."""

    def __init__(
        self,
        *,
        precondition_resolvers: Dict[str, Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]],
        data_strategies: Dict[str, Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]],
        data_verifier: Callable[[Dict[str, Any], Dict[str, Any], Dict[str, Any]], Dict[str, Any]],
        binding_store: Optional[AttemptBindingStore] = None,
        human_gate: Optional[Callable[[Dict[str, Any]], Optional[str]]] = None,
    ):
        self.precondition_resolvers = dict(precondition_resolvers)
        self.data_strategies = dict(data_strategies)
        self.data_verifier = data_verifier
        self.binding_store = binding_store or AttemptBindingStore()
        self.human_gate = human_gate

    @staticmethod
    def _validate_step_result(result: Dict[str, Any], *, code: str) -> Dict[str, Any]:
        if not isinstance(result, dict):
            raise PreparationContractError(code)
        success = result.get("success")
        if not isinstance(success, bool):
            raise PreparationContractError(code)
        return result

    def _resolve_preconditions(self, plan: PreparationPlan, context: Dict[str, Any]) -> List[str]:
        evidence = []
        for spec in plan.preconditions:
            resolver = self.precondition_resolvers.get(spec["type"])
            if resolver is None:
                raise PreparationContractError(f"PRECONDITION_RESOLVER_MISSING:{spec['type']}")
            result = self._validate_step_result(resolver(deepcopy(spec), deepcopy(context)), code="INVALID_PRECONDITION_RESULT")
            if not result["success"]:
                raise PreparationContractError(f"PRECONDITION_NOT_SATISFIED:{spec['id']}")
            eref = result.get("evidence_ref")
            if not isinstance(eref, str) or not eref.strip():
                raise PreparationContractError("PRECONDITION_EVIDENCE_REQUIRED")
            evidence.append(eref)
        return evidence

    def _prepare_one(self, requirement: Dict[str, Any], context: Dict[str, Any]) -> Tuple[Any, List[str]]:
        allowed = requirement["allowed_strategies"]
        last_failure = None
        for strategy in STRATEGY_ORDER:
            if strategy not in allowed:
                continue
            provider = self.data_strategies.get(strategy)
            if provider is None:
                continue
            gate_ref = None
            if strategy == "DB_CREATE":
                if self.human_gate is None:
                    raise PreparationContractError(f"HUMAN_GATE_REQUIRED:{requirement['id']}:DB_CREATE")
                gate_ref = self.human_gate({
                    "action": "DB_CREATE",
                    "requirement_id": requirement["id"],
                    "selectors": deepcopy(requirement["selectors"]),
                    "target_id": context.get("target_id"),
                })
                if not isinstance(gate_ref, str) or not gate_ref.strip():
                    raise PreparationContractError(f"HUMAN_GATE_DENIED:{requirement['id']}:DB_CREATE")
            result = self._validate_step_result(provider(deepcopy(requirement), deepcopy(context)), code="INVALID_DATA_STRATEGY_RESULT")
            if not result["success"]:
                last_failure = result.get("reason") or strategy
                continue
            binding = result.get("binding")
            tool_ref = result.get("tool_call_ref")
            evidence_ref = result.get("evidence_ref")
            if binding is None or not isinstance(tool_ref, str) or not tool_ref.strip() or not isinstance(evidence_ref, str) or not evidence_ref.strip():
                raise PreparationContractError("DATA_STRATEGY_EVIDENCE_REQUIRED")
            verification = self._validate_step_result(
                self.data_verifier(deepcopy(requirement), deepcopy(binding), deepcopy(context)),
                code="INVALID_DATA_VERIFICATION_RESULT",
            )
            if not verification["success"]:
                raise PreparationContractError(f"DATA_VERIFICATION_FAILED:{requirement['id']}:{strategy}")
            verify_ref = verification.get("evidence_ref")
            if not isinstance(verify_ref, str) or not verify_ref.strip():
                raise PreparationContractError("DATA_VERIFICATION_EVIDENCE_REQUIRED")
            refs = [tool_ref, evidence_ref, verify_ref]
            if gate_ref:
                refs.append(gate_ref)
            return deepcopy(binding), refs
        raise PreparationContractError(f"DATA_PREPARATION_EXHAUSTED:{requirement['id']}:{last_failure}")

    def prepare(self, *, case: Dict[str, Any], attempt_id: str, target_id: str) -> PreparedAttempt:
        if not isinstance(attempt_id, str) or not attempt_id.strip():
            raise PreparationContractError("ATTEMPT_ID_REQUIRED")
        if not isinstance(target_id, str) or not target_id.strip():
            raise PreparationContractError("TARGET_ID_REQUIRED")
        existing = self.binding_store.get(attempt_id)
        if existing is not None:
            if existing.tc_id != case.get("tc_id") or existing.case_version != case.get("case_version") or existing.target_id != target_id:
                raise PreparationContractError("ATTEMPT_BINDING_IMMUTABLE")
            return existing

        plan = PreparationSpecParser().parse(case)
        context = {
            "attempt_id": attempt_id,
            "target_id": target_id,
            "tc_id": plan.tc_id,
            "case_version": plan.case_version,
            "layer": plan.layer,
        }
        precondition_evidence = self._resolve_preconditions(plan, context)
        initial: Dict[str, Any] = {}
        inputs: Dict[str, Any] = {}
        binding_evidence: List[str] = []
        for requirement in plan.initial_state_requirements:
            binding, refs = self._prepare_one(requirement, context)
            initial[requirement["id"]] = binding
            binding_evidence.extend(refs)
        for requirement in plan.input_data_requirements:
            binding, refs = self._prepare_one(requirement, context)
            inputs[requirement["id"]] = binding
            binding_evidence.extend(refs)

        prepared = PreparedAttempt(
            status="PREPARED",
            attempt_id=attempt_id,
            tc_id=plan.tc_id,
            case_version=plan.case_version,
            target_id=target_id,
            precondition_evidence=tuple(precondition_evidence),
            initial_state_bindings=deepcopy(initial),
            input_data_bindings=deepcopy(inputs),
            binding_evidence=tuple(binding_evidence),
            cleanup_policy=deepcopy(plan.cleanup_policy),
            oracle_snapshot=deepcopy(plan.oracle_snapshot),
        )
        return self.binding_store.bind(prepared)


class PreparationRecoveryEngine:
    """Deterministic recovery semantics; product failures cannot be prepared away."""

    def decide(
        self,
        failure_class: str,
        *,
        preparation_verified: bool,
        real_action_executed: bool,
        assertion_failed: bool,
    ) -> RecoveryDecision:
        failure_class = str(failure_class).upper()
        if failure_class not in FAILURE_CLASSES:
            raise PreparationContractError("UNKNOWN_FAILURE_CLASS")
        if failure_class == "PRODUCT":
            if preparation_verified and real_action_executed and assertion_failed:
                return RecoveryDecision("PRODUCT_DEFECT", False, False, True)
            return RecoveryDecision("BLOCKED_DIAGNOSIS", False, False, False)
        mapping = {
            "TRANSIENT": RecoveryDecision("RETRY_SAME_STEP", True, False, False),
            "AUTH": RecoveryDecision("REAUTH", True, False, False),
            "DATA": RecoveryDecision("RESEARCH_OR_REBUILD_DATA", False, True, False),
            "PRECONDITION": RecoveryDecision("RECONSTRUCT_PRECONDITION", False, True, False),
            "TOOL": RecoveryDecision("REPAIR_TOOL", False, False, False),
            "ROUTE": RecoveryDecision("REPAIR_BINDING", False, False, False),
            "ENVIRONMENT": RecoveryDecision("BLOCKED_ENVIRONMENT", False, False, False),
            "DESIGN": RecoveryDecision("REOPEN_DESIGN", False, False, False),
        }
        return mapping[failure_class]
