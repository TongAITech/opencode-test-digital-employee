"""Strict evidence projection for parent-owned RC7 API execution."""

from __future__ import annotations

from rc6_runtime.automation import RunnerExecutionResult

from .controlled_api_execution import ControlledApiRunnerAdapter


class StrictControlledApiRunnerAdapter(ControlledApiRunnerAdapter):
    """Keep process proof plus parent-authoritative tool evidence only.

    ``ControlledApiRunnerAdapter`` already discards child-authored api-runtime
    tool objects and actual results. This final facade also removes stale call
    and evidence URIs that the generic RunnerAdapter copied from the child's
    legacy manifest before the authoritative replacement happened.
    """

    def execute(self, **kwargs) -> RunnerExecutionResult:
        result = super().execute(**kwargs)
        valid_call_refs = {call["call_ref"] for call in result.tool_calls}
        call_refs = tuple(
            ref for ref in result.tool_call_refs
            if ref.startswith("process-call://") or ref in valid_call_refs
        )
        valid_evidence_refs = {result.stdout_ref, result.stderr_ref}
        valid_evidence_refs.update(call["evidence_ref"] for call in result.tool_calls)
        evidence_refs = tuple(
            ref for ref in result.evidence_refs if ref in valid_evidence_refs
        )
        return RunnerExecutionResult(
            runner_type=result.runner_type,
            test_symbol=result.test_symbol,
            exit_code=result.exit_code,
            status=result.status,
            actual_result=result.actual_result,
            stdout_ref=result.stdout_ref,
            stderr_ref=result.stderr_ref,
            tool_calls=result.tool_calls,
            tool_call_refs=call_refs,
            evidence_refs=evidence_refs,
            duration_ms=result.duration_ms,
        )
