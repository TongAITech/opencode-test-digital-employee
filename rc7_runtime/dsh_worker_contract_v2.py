"""RC7.1 production/repair contracts for DSH producer Workers.

The base bridge remains the authority for leases, evidence and candidate
persistence. This additive patch enriches its prompt with deterministic node
contracts and canonical Gap repair context so a Worker knows exactly what a
sufficiency repair must produce without receiving coordinator chat history.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from . import dsh_worker_bridge as _bridge


_REQUIREMENT_CONTRACT = {
    "version": "rc7.1-requirement-sufficiency-v2",
    "required_semantic_dimensions": [
        "business_rules",
        "roles",
        "preconditions",
        "normal_paths",
        "negative_paths",
        "boundaries",
        "states",
        "data_constraints",
        "dependencies",
        "side_effects",
    ],
    "dimension_rule": (
        "Every semantic dimension must be populated with identified evidence-backed facts, or if truly not "
        "applicable (except boundaries, which remain mandatory under the legacy strict gate), include one "
        "dimension_exclusions item with dimension, concrete reason and evidence_ref resolving to returned evidence."
    ),
    "dimension_exclusions_schema": {
        "dimension": "one required semantic dimension",
        "reason": "specific source-based NOT_APPLICABLE rationale",
        "evidence_ref": "exact returned evidence content_ref/source_ref alias",
    },
    "forbidden": [
        "silent empty semantic dimensions",
        "generic not-applicable assertions without evidence",
        "duplicate or unidentified semantic facts",
    ],
}

_CODE_CONTRACT = {
    "version": "rc7.1-code-impact-sufficiency-v2",
    "required_fields": [
        "requirement_ids",
        "source_revisions",
        "changed_files",
        "changed_symbols",
        "symbol_explanations",
        "reverse_requirement_mappings",
        "impact_surfaces",
        "impact_dimension_exclusions",
        "tool_calls",
        "evidence_refs",
        "codegraph_required",
    ],
    "impact_surface_rule": (
        "Use real Git + CodeGraph/source evidence to expand every changed symbol/file into structured impact "
        "surfaces. Do not stop at changed_symbols or at proof that CodeGraph was called."
    ),
    "impact_surface_schema": {
        "id": "stable unique impact id",
        "kind": "CALLER|CALLEE|API|DATABASE|CONFIG|MESSAGE|EXCEPTION|TRANSACTION|SIDE_EFFECT|STATE|SECURITY|PERFORMANCE|FILE",
        "source_symbol_id": "id of one changed_symbols item backed by symbol_explanations",
        "source_file": "optional exact changed_files path",
        "target_ref": "short impacted symbol/API/table/config/event/error/transaction/etc reference",
    },
    "required_impact_dimensions": [
        "CALL_GRAPH",
        "INTERFACE",
        "DATA",
        "CONFIG",
        "EVENT",
        "ERROR",
        "TRANSACTION",
        "SIDE_EFFECT",
        "SECURITY",
        "PERFORMANCE",
    ],
    "impact_dimension_exclusion_schema": {
        "dimension": "one required impact dimension not represented by impact_surfaces",
        "reason": "specific evidence-backed NOT_APPLICABLE rationale",
        "basis_symbol_ids": "non-empty list of changed symbol ids whose normalized evidence proves the exclusion",
    },
    "impact_exclusion_schema": {
        "target_type": "SYMBOL|FILE",
        "target_ref": "changed symbol id or changed file path",
        "reason": "specific evidence-backed rationale",
        "basis_symbol_ids": "required for FILE exclusion; changed symbol ids proving no downstream impact",
    },
    "forbidden": [
        "calling CodeGraph without materializing impact_surfaces",
        "unaccounted changed symbols/files",
        "unexplained empty impact dimensions",
        "invented evidence ids",
    ],
}

_TEST_DESIGN_CONTRACT = {
    "version": "rc7.1-test-design-sufficiency-v2",
    "obligation_rule": (
        "The candidate obligation inventory must represent every parent-derived source fact, including requirement "
        "preconditions/dependencies and code changed files/reverse requirement mappings/impact surfaces. Never choose "
        "a smaller self-authored denominator."
    ),
    "case_rule": (
        "Generate focused executable Cases rather than mega-cases that claim many unrelated obligations. Coverage "
        "must satisfy semantic closure plus RC7.1 density, concentration, kind diversity, critical depth and "
        "risk-relevant interaction gates."
    ),
    "interaction_focus": [
        "BUSINESS_RULE x BOUNDARY",
        "BUSINESS_RULE x DATA_CONDITION",
        "STATE_TRANSITION x ROLE_PERMISSION",
        "NEGATIVE_PATH x SIDE_EFFECT",
        "CODE_IMPACT x REGRESSION",
        "CODE_IMPACT x HIGH_RISK_HYPOTHESIS",
    ],
    "execution_contract": (
        "Every executable Case must carry structured preconditions, deterministic test_data and cleanup, ordered "
        "steps, expected result, oracle_refs/deterministic Oracle, evidence requirements and PYTEST/JUNIT runner."
    ),
    "repair_rule": (
        "For a sufficiency Gap, add/reshape only the missing delta Cases/obligations required by canonical Gap "
        "context; preserve valid prior Cases and source traceability."
    ),
}

_NODE_CONTRACTS = {
    "REQUIREMENT_ANALYSIS": _REQUIREMENT_CONTRACT,
    "CODE_ANALYSIS": _CODE_CONTRACT,
    "TEST_DESIGN": _TEST_DESIGN_CONTRACT,
}


# Improve the compact inline hint even for callers that inspect RETURN_SCHEMA.
_bridge._SEMANTIC_PAYLOAD_HINTS["REQUIREMENT_ANALYSIS"] = (
    "source_assertions, atomic_statements, trace_links, evidence_refs, business_rules, roles, preconditions, "
    "normal_paths, negative_paths, boundaries, states, data_constraints, dependencies, side_effects, and "
    "evidence-backed dimension_exclusions for genuinely non-applicable empty dimensions"
)
_bridge._SEMANTIC_PAYLOAD_HINTS["CODE_ANALYSIS"] = (
    "requirement_ids, source_revisions, changed_files, changed_symbols, symbol_explanations, "
    "reverse_requirement_mappings, impact_surfaces, impact_exclusions, impact_dimension_exclusions, "
    "tool_calls, evidence_refs, codegraph_required"
)
_bridge._SEMANTIC_PAYLOAD_HINTS["TEST_DESIGN"] = (
    "parent-derived obligations plus focused executable test cases with coverage links, risk/action semantics, "
    "structured data/preconditions/cleanup, deterministic oracles, and sufficient density/diversity/interactions"
)


def _canonical_gap_context(bridge: Any, task: Any) -> List[Dict[str, Any]]:
    context: List[Dict[str, Any]] = []
    for gap_id in list(getattr(task, "gap_refs", []) or []):
        if not isinstance(gap_id, str) or not gap_id:
            continue
        rows = bridge.control.truth.query("rc7_gap", gap_id=gap_id)
        if len(rows) != 1:
            context.append({"gap_id": gap_id, "status": "UNRESOLVED"})
            continue
        row = rows[0]
        if str(row.get("mission_id") or "") != str(task.mission_id):
            context.append({"gap_id": gap_id, "status": "MISSION_MISMATCH"})
            continue
        context.append(
            {
                "gap_id": gap_id,
                "status": "RESOLVED",
                "category": row.get("category"),
                "severity": row.get("severity"),
                "source_node": row.get("source_node"),
                "target_node": row.get("target_node"),
                "description": row.get("description"),
                "subject_refs": list(row.get("subject_refs") or []),
                "evidence_refs": list(row.get("evidence_refs") or []),
                "acceptance_criteria": list(row.get("acceptance_criteria") or []),
            }
        )
    return context


def install_rc7_1_worker_output_contracts() -> None:
    current = _bridge.DshTaskWorkerBridge.compile_prompt
    if getattr(current, "_rc71_sufficiency_contracts", False):
        return
    original = current

    def compile_prompt_with_sufficiency_contract(self, task, assignment):
        prompt = original(self, task, assignment)
        node_contract = _NODE_CONTRACTS.get(str(task.node))
        gap_context = _canonical_gap_context(self, task)
        addon: Dict[str, Any] = {
            "schema": "pfc.aitest.rc7.1.worker-sufficiency-contract.v1",
            "node": task.node,
            "task_type": task.task_type,
            "node_contract": node_contract,
            "canonical_gap_context": gap_context,
            "repair_contract": (
                "When task_type=REPAIR, canonical_gap_context is the authoritative delta to repair. Produce a new "
                "candidate only; never self-close a Gap or self-declare PASS. After repair an independent evaluator "
                "must re-evaluate the source node before the Gap can resolve."
            ),
        }
        return prompt + "\nRC7_1_SUFFICIENCY_CONTRACT=" + json.dumps(addon, ensure_ascii=False, sort_keys=True)

    compile_prompt_with_sufficiency_contract._rc71_sufficiency_contracts = True
    _bridge.DshTaskWorkerBridge.compile_prompt = compile_prompt_with_sufficiency_contract
