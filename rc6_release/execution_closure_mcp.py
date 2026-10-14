"""DSH-callable MCP surfaces for the RC6 Execution Closure Overlay.

This module is deliberately a thin adapter. Authority, immutable contracts,
R1 persistence, deterministic script validation, real process runners,
failure ownership and recovery/convergence remain runtime-owned.
"""

from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from rc6_runtime import (
    AIScriptBuilder,
    AttemptHistory,
    AttemptHistoryEntry,
    AutomationAsset,
    AutomationResolution,
    AutomationReuseResolver,
    CorrelationScope,
    DiagnosisResult,
    DiagnosisRuntime,
    ExecutableSpecBuilder,
    ExecutableTestSpec,
    ExecutionBudgets,
    ExecutionConvergenceController,
    ExecutionRuntime,
    FailureContext,
    FailureSignature,
    JUnitRunnerAdapter,
    ProcessStepResult,
    PytestRunnerAdapter,
    RecoveryActionExecutor,
    RecoveryDecision as PreparationRecoveryDecision,
    ScriptArtifact,
    ScriptValidation,
    ScriptValidator,
)
from rc6_runtime.diagnosis import RecoveryDecision as DiagnosisRecoveryDecision, RecoveryEngine, RootCauseCandidate
from rc6_runtime.preparation import PreparedAttempt


class ExecutionClosureMcpError(RuntimeError):
    pass


def _schema(properties: Dict[str, Any], required: Sequence[str] = ()) -> Dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


def execution_closure_tool_schemas() -> List[Dict[str, Any]]:
    s = {"type": "string"}
    b = {"type": "boolean"}
    a = {"type": "array", "items": s}
    o = {"type": "object", "additionalProperties": True}
    return [
        {"name": "executable_spec_build", "description": "AUTOMATION_ENGINEER builds immutable ExecutableSpec from a frozen canonical TestCase and records it in R1.", "inputSchema": _schema({"worker_id": s, "lease_id": s, "case": o, "target_requirements": a, "test_data_refs": a, "oracle_refs": a, "cleanup_policy": o, "runner_type": s, "automation_mapping": o}, ["worker_id", "lease_id", "case", "target_requirements", "test_data_refs", "oracle_refs", "cleanup_policy", "runner_type", "automation_mapping"])},
        {"name": "automation_reuse_resolve", "description": "Search existing tests/fixtures/clients/helpers/auth/routes/data/assertions/cleanup before script generation; records mapping in R1.", "inputSchema": _schema({"worker_id": s, "lease_id": s, "spec": o, "search_roots": a, "extra_keywords": a}, ["worker_id", "lease_id", "spec", "search_roots"])},
        {"name": "script_build", "description": "AUTOMATION_ENGINEER writes a governed script artifact only after reuse resolution; Case/Oracle fingerprints are immutable.", "inputSchema": _schema({"worker_id": s, "lease_id": s, "spec": o, "resolution": o, "source_content": s, "file_name": s, "test_symbol": s, "builder_evidence_refs": a, "revision": {"type": "integer", "minimum": 1}}, ["worker_id", "lease_id", "spec", "resolution", "source_content", "file_name", "test_symbol", "builder_evidence_refs"])},
        {"name": "script_validate", "description": "Deterministically validate generated/repaired pytest or JUnit script and record SCRIPT_READY/SCRIPT_INVALID in R1.", "inputSchema": _schema({"worker_id": s, "lease_id": s, "spec": o, "script": o, "cwd": s, "env": o}, ["worker_id", "lease_id", "spec", "script", "cwd"])},
        {"name": "runner_execute", "description": "Execute SCRIPT_READY through production Pytest/JUnit RunnerAdapter and Wave9 ExecutionIntegrityGate; records attempt/assertion/evidence in R1.", "inputSchema": _schema({"worker_id": s, "lease_id": s, "case": o, "spec": o, "script": o, "validation": o, "prepared_attempt": o, "cwd": s, "env": o}, ["worker_id", "lease_id", "case", "spec", "script", "validation", "prepared_attempt", "cwd"])},
        {"name": "failure_diagnose", "description": "Evidence-backed failure ownership; optional CAT evidence and CodeGraph/Git RCA candidate are recorded canonically. Assertion failure alone cannot become PRODUCT.", "inputSchema": _schema({"worker_id": s, "lease_id": s, "release_id": s, "context": o, "classification": o, "cat_result": o, "rca_candidate": o}, ["worker_id", "lease_id", "release_id", "context", "classification"])},
        {"name": "recovery_decide", "description": "Compute fail-closed recovery decision from canonical failure diagnosis and append it to R1.", "inputSchema": _schema({"worker_id": s, "lease_id": s, "release_id": s, "context": o, "diagnosis": o, "history": {"type": "array", "items": o}}, ["worker_id", "lease_id", "release_id", "context", "diagnosis", "history"])},
        {"name": "recovery_execute", "description": "Execute/verify a recovery action result, enforce independent budgets/signature loop breaker, and create a fresh successor Attempt reference; records recovery action in R1.", "inputSchema": _schema({"worker_id": s, "lease_id": s, "release_id": s, "context": o, "diagnosis": o, "decision": o, "history": {"type": "array", "items": o}, "action_result": o, "budgets": o}, ["worker_id", "lease_id", "release_id", "context", "diagnosis", "decision", "history", "action_result"])},
        {"name": "execution_convergence", "description": "Evaluate PASS/product/manual/budget convergence from append-only attempt history and stable FailureSignature.", "inputSchema": _schema({"release_id": s, "diagnosis": o, "history": {"type": "array", "items": o}, "budgets": o, "pass_observed": b}, ["release_id", "history"])},
    ]


def _strip(payload: Mapping[str, Any], fields: Sequence[str]) -> Dict[str, Any]:
    return {key: payload.get(key) for key in fields}


def _spec(payload: Mapping[str, Any]) -> ExecutableTestSpec:
    fields = (
        "spec_id", "tc_id", "case_version", "case_fingerprint", "oracle_fingerprint", "release_id",
        "requirement_id", "sst_id", "layer", "target_requirements", "preconditions", "test_data_refs",
        "ordered_actions", "oracle_refs", "evidence_requirements", "cleanup_policy", "runner_type",
        "automation_mapping", "status",
    )
    raw = _strip(payload, fields)
    for name in ("target_requirements", "preconditions", "test_data_refs", "ordered_actions", "oracle_refs", "evidence_requirements"):
        raw[name] = tuple(raw.get(name) or ())
    return ExecutableTestSpec(**raw)


def _script(payload: Mapping[str, Any]) -> ScriptArtifact:
    fields = (
        "script_id", "spec_id", "tc_id", "case_version", "layer", "runner_type", "source_ref", "test_symbol",
        "case_fingerprint", "oracle_fingerprint", "reuse_refs", "builder_evidence_refs", "revision", "status",
    )
    raw = _strip(payload, fields)
    raw["reuse_refs"] = tuple(raw.get("reuse_refs") or ())
    raw["builder_evidence_refs"] = tuple(raw.get("builder_evidence_refs") or ())
    return ScriptArtifact(**raw)


def _validation(payload: Mapping[str, Any]) -> ScriptValidation:
    steps = tuple(ProcessStepResult(**_strip(item, ("name", "command", "exit_code", "stdout_ref", "stderr_ref", "duration_ms", "passed"))) for item in (payload.get("steps") or []))
    # JSON payloads carry command as arrays; dataclass contract uses tuple.
    normalized_steps = tuple(ProcessStepResult(step.name, tuple(step.command), step.exit_code, step.stdout_ref, step.stderr_ref, step.duration_ms, step.passed) for step in steps)
    return ScriptValidation(
        validation_id=payload["validation_id"], script_id=payload["script_id"],
        runner_type=payload["runner_type"], test_symbol=payload["test_symbol"],
        steps=normalized_steps, evidence_refs=tuple(payload.get("evidence_refs") or ()), status=payload["status"],
    )


def _prepared(payload: Mapping[str, Any]) -> PreparedAttempt:
    fields = (
        "status", "attempt_id", "tc_id", "case_version", "target_id", "precondition_evidence",
        "initial_state_bindings", "input_data_bindings", "binding_evidence", "cleanup_policy", "oracle_snapshot",
    )
    raw = _strip(payload, fields)
    raw["precondition_evidence"] = tuple(raw.get("precondition_evidence") or ())
    raw["binding_evidence"] = tuple(raw.get("binding_evidence") or ())
    return PreparedAttempt(**raw)


def _history(rows: Sequence[Mapping[str, Any]]) -> AttemptHistory:
    history = AttemptHistory()
    pending = list(rows)
    # Parent-before-child deterministic load.
    while pending:
        progressed = False
        for raw in list(pending):
            parent = raw.get("parent_attempt_id")
            if parent and history.get(parent) is None:
                continue
            history.append(AttemptHistoryEntry(
                attempt_id=raw["attempt_id"], parent_attempt_id=parent,
                tc_id=raw["tc_id"], case_version=int(raw["case_version"]), target_id=raw["target_id"],
                layer=raw["layer"], status=raw["status"], evidence_refs=tuple(raw.get("evidence_refs") or ()),
                recorded_at=int(raw.get("recorded_at", 0)), failure_signature_id=raw.get("failure_signature_id"),
            ))
            pending.remove(raw); progressed = True
        if not progressed:
            raise ExecutionClosureMcpError("INVALID_ATTEMPT_HISTORY_PARENT_CHAIN")
    return history


def _correlation(payload: Optional[Mapping[str, Any]]) -> Optional[CorrelationScope]:
    if not payload:
        return None
    return CorrelationScope(
        applications=tuple(payload.get("applications") or ()),
        window_start=int(payload["window_start"]), window_end=int(payload["window_end"]),
        request_id=payload.get("request_id"), trace_id=payload.get("trace_id"), business_id=payload.get("business_id"),
    )


def _failure_context(payload: Mapping[str, Any]) -> FailureContext:
    values = dict(payload)
    values["execution_evidence_refs"] = tuple(values.get("execution_evidence_refs") or ())
    values["runner_log_refs"] = tuple(values.get("runner_log_refs") or ())
    values["correlation"] = _correlation(values.get("correlation"))
    return FailureContext(**values)


def _diagnosis(payload: Mapping[str, Any]) -> DiagnosisResult:
    sig_raw = payload.get("failure_signature")
    signature = FailureSignature(**sig_raw) if isinstance(sig_raw, dict) else None
    rca_raw = payload.get("root_cause_candidate")
    rca = None
    if isinstance(rca_raw, dict):
        rca = RootCauseCandidate(
            candidate_id=rca_raw["candidate_id"], symbol=rca_raw["symbol"],
            call_path=tuple(rca_raw.get("call_path") or ()), git_change_refs=tuple(rca_raw.get("git_change_refs") or ()),
            requirement_refs=tuple(rca_raw.get("requirement_refs") or ()), evidence_refs=tuple(rca_raw.get("evidence_refs") or ()),
            confidence=float(rca_raw["confidence"]),
        )
    return DiagnosisResult(
        diagnosis_id=payload["diagnosis_id"], attempt_id=payload["attempt_id"], failure_class=payload["failure_class"],
        evidence_refs=tuple(payload.get("evidence_refs") or ()), cat_required=bool(payload.get("cat_required")),
        cat_queried=bool(payload.get("cat_queried")), rationale=payload["rationale"], classifier_ref=payload["classifier_ref"],
        failure_signature=signature, root_cause_candidate=rca,
    )


def _decision(payload: Mapping[str, Any]) -> DiagnosisRecoveryDecision:
    return DiagnosisRecoveryDecision(
        diagnosis_id=payload["diagnosis_id"], attempt_id=payload["attempt_id"], action=payload["action"],
        retry_allowed=bool(payload["retry_allowed"]), reprepare_allowed=bool(payload["reprepare_allowed"]),
        terminal=bool(payload["terminal"]), next_attempt_id=payload.get("next_attempt_id"), reason=payload["reason"],
    )


def _append(truth, event_type: str, payload: Dict[str, Any]):
    return truth.append_atomic(event_type, payload)


def _safe_file(state_root: Path, release_id: str, file_name: str) -> Path:
    base = Path(file_name).name
    if not base or base != file_name or not re.match(r"^[A-Za-z0-9_.-]+$", base):
        raise ExecutionClosureMcpError("INVALID_SCRIPT_FILE_NAME")
    folder = state_root / "generated-tests" / re.sub(r"[^A-Za-z0-9_.-]+", "_", release_id)
    folder.mkdir(parents=True, exist_ok=True)
    return folder / base


def _oracle(snapshot: Dict[str, Any], actual: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    oracle = snapshot or {}
    oracle_type = str(oracle.get("type", "")).lower()
    if oracle_type == "field_equals" or ("field" in oracle and "value" in oracle):
        field = oracle.get("field")
        expected = oracle.get("value")
        value: Any = actual
        for part in str(field).split("."):
            if not isinstance(value, dict) or part not in value:
                value = None; break
            value = value[part]
        passed = value == expected
        details = {"field": field, "expected": expected, "actual": value}
    elif isinstance(oracle.get("checks"), list) and oracle["checks"]:
        check = oracle["checks"][0]
        expected = check.get("expected")
        value = actual.get("business")
        passed = value == expected
        details = {"expected": expected, "actual": value}
    else:
        raise ExecutionClosureMcpError("UNSUPPORTED_DETERMINISTIC_ORACLE")
    attempt = context["attempt_id"]
    return {"passed": passed, "assertion_ref": "assertion://%s" % attempt, "evidence_refs": ["oracle-evidence://%s" % attempt], "details": details}


def _record_execution_truth(truth, spec: ExecutableTestSpec, record) -> Dict[str, Any]:
    attempt = {
        "attempt_id": record.attempt_id, "release_id": spec.release_id, "requirement_id": spec.requirement_id,
        "tc_id": record.tc_id, "case_version": record.case_version, "target_id": record.target_id,
        "layer": record.layer, "status": record.status, "actual_result": record.actual_result,
        "tool_call_refs": list(record.tool_call_refs), "evidence_refs": list(record.evidence_refs),
        "spec_id": spec.spec_id, "oracle_fingerprint": spec.oracle_fingerprint,
    }
    attempt_receipt = _append(truth, "EXECUTION_ATTEMPT_UPSERTED", attempt)
    assertion_receipt = None
    if record.assertion_ref:
        assertion = {
            "id": record.assertion_ref, "release_id": spec.release_id, "attempt_id": record.attempt_id,
            "tc_id": record.tc_id, "oracle_ref": spec.oracle_refs[0], "passed": bool(record.assertion_passed),
            "evidence_refs": [ref for ref in record.evidence_refs if ref.startswith("oracle-evidence://")] or list(record.evidence_refs[:1]),
            "spec_id": spec.spec_id, "oracle_fingerprint": spec.oracle_fingerprint,
        }
        assertion_receipt = _append(truth, "ASSERTION_UPSERTED", assertion)
    evidence_receipts = []
    for ref in record.evidence_refs:
        eid = "EVID-" + sha256((record.attempt_id + "|" + ref).encode("utf-8")).hexdigest()[:24]
        evidence_receipts.append(_append(truth, "EVIDENCE_UPSERTED", {
            "id": eid, "release_id": spec.release_id, "kind": "EXECUTION", "ref": ref,
            "source_artifact_ref": "attempt://%s" % record.attempt_id,
            "requirement_id": spec.requirement_id, "tc_id": spec.tc_id, "attempt_id": record.attempt_id,
            "metadata": {"runner_type": spec.runner_type, "spec_id": spec.spec_id},
        }))
    return {"attempt": attempt_receipt, "assertion": assertion_receipt, "evidence": evidence_receipts}


def call_execution_closure_tool(
    name: str,
    arguments: Dict[str, Any],
    *,
    authority,
    truth,
    broker,
    state_root: Path,
) -> Optional[Dict[str, Any]]:
    if name == "executable_spec_build":
        authority.authorize_artifact(arguments["worker_id"], arguments["lease_id"], "executable_test_spec")
        spec = ExecutableSpecBuilder().build(
            case=arguments["case"], target_requirements=tuple(arguments["target_requirements"]),
            test_data_refs=tuple(arguments["test_data_refs"]), oracle_refs=tuple(arguments["oracle_refs"]),
            cleanup_policy=arguments["cleanup_policy"], runner_type=arguments["runner_type"],
            automation_mapping=arguments["automation_mapping"],
        )
        receipt = _append(truth, "EXECUTABLE_TEST_SPEC_UPSERTED", spec.to_artifact())
        return {"spec": asdict(spec), "r1_receipt": asdict(receipt)}

    if name == "automation_reuse_resolve":
        authority.authorize_artifact(arguments["worker_id"], arguments["lease_id"], "automation_mapping")
        spec = _spec(arguments["spec"])
        resolution = AutomationReuseResolver().resolve(spec=spec, search_roots=arguments["search_roots"], extra_keywords=arguments.get("extra_keywords") or ())
        mapping_id = "MAP-" + sha256((spec.spec_id + "|" + json.dumps(resolution.mapping(), sort_keys=True)).encode("utf-8")).hexdigest()[:24]
        payload = {
            "mapping_id": mapping_id, "release_id": spec.release_id, "requirement_id": spec.requirement_id,
            "tc_id": spec.tc_id, "case_version": spec.case_version, "layer": spec.layer, "spec_id": spec.spec_id,
            "reuse": resolution.mapping()["reuse"], "evidence_refs": list(resolution.evidence_refs),
        }
        receipt = _append(truth, "AUTOMATION_MAPPING_UPSERTED", payload)
        return {"resolution": asdict(resolution), "mapping": payload, "r1_receipt": asdict(receipt)}

    if name == "script_build":
        authority.authorize_artifact(arguments["worker_id"], arguments["lease_id"], "script_artifact")
        spec = _spec(arguments["spec"])
        resolution_raw = arguments["resolution"]
        assets = tuple(AutomationAsset(**item) for item in (resolution_raw.get("assets") or []))
        resolution = AutomationResolution(spec.tc_id, assets, tuple(resolution_raw.get("searched_roots") or ()), tuple(resolution_raw.get("evidence_refs") or ()))
        path = _safe_file(state_root, spec.release_id, arguments["file_name"])
        path.write_text(arguments["source_content"], encoding="utf-8")
        source_evidence = "script-source://" + sha256(arguments["source_content"].encode("utf-8")).hexdigest()
        evidence_refs = list(arguments["builder_evidence_refs"]) + [source_evidence]
        script = AIScriptBuilder().build(
            spec=spec, resolution=resolution,
            generator=lambda _spec, _mapping: {"source_ref": "file://" + str(path), "test_symbol": arguments["test_symbol"], "evidence_refs": evidence_refs},
            revision=int(arguments.get("revision", 1)),
        )
        payload = asdict(script)
        payload.update({"release_id": spec.release_id, "requirement_id": spec.requirement_id, "sst_id": spec.sst_id})
        receipt = _append(truth, "SCRIPT_ARTIFACT_UPSERTED", payload)
        return {"script": payload, "r1_receipt": asdict(receipt)}

    if name == "script_validate":
        authority.authorize_artifact(arguments["worker_id"], arguments["lease_id"], "script_validation")
        spec = _spec(arguments["spec"]); script = _script(arguments["script"])
        validation = ScriptValidator().validate(spec=spec, script=script, cwd=arguments["cwd"], env=arguments.get("env") or None, execute_target=True)
        payload = validation.to_artifact(); payload["release_id"] = spec.release_id; payload["spec_id"] = spec.spec_id; payload["tc_id"] = spec.tc_id
        receipt = _append(truth, "SCRIPT_VALIDATION_UPSERTED", payload)
        return {"validation": payload, "r1_receipt": asdict(receipt)}

    if name == "runner_execute":
        spec = _spec(arguments["spec"]); script = _script(arguments["script"]); validation = _validation(arguments["validation"]); prepared = _prepared(arguments["prepared_attempt"])
        runner_type = script.runner_type.upper()
        if runner_type == "PYTEST": runner = PytestRunnerAdapter()
        elif runner_type == "JUNIT": runner = JUnitRunnerAdapter()
        else: raise ExecutionClosureMcpError("RUNNER_ADAPTER_NOT_AVAILABLE:%s" % runner_type)
        runtime = ExecutionRuntime(authority=authority, tool_broker=broker, oracle_evaluator=_oracle)
        record = runtime.execute_with_runner(
            case=arguments["case"], executable_spec=spec, script=script, validation=validation,
            prepared=prepared, worker_id=arguments["worker_id"], lease_id=arguments["lease_id"],
            runner=runner, cwd=arguments["cwd"], env=arguments.get("env") or None,
        )
        receipts = _record_execution_truth(truth, spec, record)
        return {"execution": asdict(record), "r1_receipts": receipts}

    if name == "failure_diagnose":
        ctx = _failure_context(arguments["context"])
        classification = arguments["classification"]
        runtime = DiagnosisRuntime(
            authority=authority, tool_broker=broker,
            classifier=lambda _ctx, _signals: classification,
            cat_query=(lambda _scope, _ctx: arguments["cat_result"]) if arguments.get("cat_result") else None,
            rca_resolver=(lambda _ctx, _signals, _cls: arguments["rca_candidate"]) if arguments.get("rca_candidate") else None,
        )
        result = runtime.diagnose(context=ctx, worker_id=arguments["worker_id"], lease_id=arguments["lease_id"])
        rca_receipt = None
        rca_id = None
        if result.root_cause_candidate:
            rca = asdict(result.root_cause_candidate); rca.update({"release_id": arguments["release_id"], "attempt_id": ctx.attempt_id})
            rca_id = result.root_cause_candidate.candidate_id
            rca_receipt = _append(truth, "ROOT_CAUSE_CANDIDATE_UPSERTED", rca)
        payload = {
            "diagnosis_id": result.diagnosis_id, "release_id": arguments["release_id"], "attempt_id": result.attempt_id,
            "failure_class": result.failure_class, "evidence_refs": list(result.evidence_refs), "classifier_ref": result.classifier_ref,
            "rationale": result.rationale, "failure_signature_id": result.failure_signature.signature_id, "root_cause_candidate_id": rca_id,
        }
        receipt = _append(truth, "FAILURE_DIAGNOSIS_UPSERTED", payload)
        return {"diagnosis": asdict(result), "r1_receipt": asdict(receipt), "rca_receipt": asdict(rca_receipt) if rca_receipt else None}

    if name == "recovery_decide":
        authority.authorize_artifact(arguments["worker_id"], arguments["lease_id"], "recovery_decision")
        ctx = _failure_context(arguments["context"]); diag = _diagnosis(arguments["diagnosis"]); history = _history(arguments["history"])
        decision = RecoveryEngine(history).decide(ctx, diag)
        did = "RDEC-" + sha256((diag.diagnosis_id + "|" + decision.action).encode("utf-8")).hexdigest()[:24]
        payload = {"decision_id": did, "release_id": arguments["release_id"], "diagnosis_id": decision.diagnosis_id, "attempt_id": decision.attempt_id, "action": decision.action, "terminal": decision.terminal, "next_attempt_id": decision.next_attempt_id, "retry_allowed": decision.retry_allowed, "reprepare_allowed": decision.reprepare_allowed, "reason": decision.reason}
        receipt = _append(truth, "RECOVERY_DECISION_UPSERTED", payload)
        return {"decision": asdict(decision), "decision_id": did, "r1_receipt": asdict(receipt)}

    if name == "recovery_execute":
        authority.authorize_artifact(arguments["worker_id"], arguments["lease_id"], "recovery_action")
        ctx = _failure_context(arguments["context"]); diag = _diagnosis(arguments["diagnosis"]); decision = _decision(arguments["decision"]); history = _history(arguments["history"])
        budgets = ExecutionBudgets(**(arguments.get("budgets") or {}))
        controller = ExecutionConvergenceController(history, budgets)
        executor = RecoveryActionExecutor(history=history, convergence=controller, adapters={decision.action: lambda _c, _d, _r: arguments["action_result"]})
        result = executor.execute(context=ctx, diagnosis=diag, decision=decision)
        payload = asdict(result); payload["release_id"] = arguments["release_id"]
        receipt = _append(truth, "RECOVERY_ACTION_UPSERTED", payload)
        return {"recovery_action": payload, "attempt_history": [asdict(x) for x in history.entries()], "r1_receipt": asdict(receipt)}

    if name == "execution_convergence":
        history = _history(arguments["history"]); controller = ExecutionConvergenceController(history, ExecutionBudgets(**(arguments.get("budgets") or {}))
        if arguments.get("pass_observed"):
            result = controller.pass_result()
        else:
            if not arguments.get("diagnosis"):
                raise ExecutionClosureMcpError("DIAGNOSIS_REQUIRED_WHEN_PASS_NOT_OBSERVED")
            result = controller.evaluate_failure(_diagnosis(arguments["diagnosis"]))
        return {"convergence": asdict(result), "release_id": arguments["release_id"]}

    return None
