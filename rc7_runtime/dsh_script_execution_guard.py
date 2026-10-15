"""Execution-readiness structural guard layered over Script readiness."""

from __future__ import annotations

import ast
from typing import List

from rc6_runtime.automation import ScriptArtifact

from .dsh_script_evaluator import DshScriptReadinessEvaluator


class DshExecutionReadyScriptEvaluator(DshScriptReadinessEvaluator):
    """Reject L3 source that still relies on child-authored execution truth."""

    @staticmethod
    def _source_structure_reasons(script: ScriptArtifact, source_text: str) -> List[str]:
        reasons = list(DshScriptReadinessEvaluator._source_structure_reasons(script, source_text))
        if script.layer.upper() != "L3":
            return reasons
        if "RC7_API_RUNTIME_PROXY_URL" not in source_text:
            reasons.append("L3_CONTROLLED_API_PROXY_BINDING_MISSING")
        try:
            tree = ast.parse(source_text)
        except SyntaxError:
            return list(dict.fromkeys(reasons))
        forbidden = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            else:
                continue
            if name in {"record_tool_call", "record_actual_result"}:
                forbidden.add(name)
        if "record_tool_call" in forbidden:
            reasons.append("L3_CHILD_TOOL_CALL_SELF_ATTESTATION_FORBIDDEN")
        if "record_actual_result" in forbidden:
            reasons.append("L3_CHILD_ACTUAL_RESULT_SELF_ATTESTATION_FORBIDDEN")
        return list(dict.fromkeys(reasons))
