"""C10 product-boundary contract: real DSH prompt and R1 usage, no proxy typing bypass."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_model_economy import TokenEconomyError, TokenEconomyService
from rc7_runtime.rc72_model_usage import TokenUsageAuditService
from rc7_runtime.rc72_native_n1_launcher import NativeN1ReadDshLauncher
from rc7_runtime.rc72_production_economy_wiring import (
    ProductionEconomyBindingError,
    bind_production_model_economy,
)


class _FakeDshProcessLauncher(DshHeadlessWorkerLauncher):
    """The same command_runner/persist boundaries used by the native launcher."""

    def __init__(self, truth, release_id, root, runner):
        self.truth = truth
        self.release_id = release_id
        self.state_root = root
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.command_runner = runner

    def execute(self, assignment, prompt):
        # Mimics native N1/4A input prefixing before subprocess.run.
        final_prompt = "NATIVE_APPROVED_CONTEXT\n" + prompt
        process = self.command_runner(
            ["dsh", "--json", final_prompt],
            capture_output=True, text=True, check=False, timeout=5,
        )
        raw = self._persist_raw_worker_output(assignment, process.stdout, process.stderr)
        return SimpleNamespace(evidence_refs=[raw]), {"status": "CONTRACT_ONLY"}

    def _persist_raw_worker_output(self, assignment, stdout, stderr):
        path = self.state_root / (assignment.assignment_id + ".jsonl")
        path.write_text(stdout, encoding="utf-8")
        return "file://" + path.as_posix()


class _Runner:
    def __init__(self, stdout, error=None):
        self.stdout, self.error = stdout, error
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((tuple(command), dict(kwargs)))
        if self.error is not None:
            raise self.error
        return SimpleNamespace(stdout=self.stdout, stderr="", returncode=0)


def _assignment(*, attempt="ATT-1", scope="WI-1"):
    return SimpleNamespace(
        mission_id="M-1",
        attempt_id=attempt,
        assignment_id="ASSIGN-" + attempt,
        agent_id="CODE-AGENT",
        scope=scope,
    )


def _setup(tmp_path, *, stdout, call_class="LLM_REQUIRED", error=None, max_calls=2):
    truth = TruthRuntime(tmp_path / "r1" / "event-stream.jsonl")
    economy = TokenEconomyService(truth, release_id="REL-1")
    economy.configure_budget(
        mission_id="M-1", max_total_tokens=10, max_model_calls=max_calls,
        max_single_call_tokens=100, max_retry_tokens=100, max_retry_calls=1,
        max_same_context_calls=2,
    )
    audit = TokenUsageAuditService(truth, release_id="REL-1")
    runner = _Runner(stdout, error)
    launcher = _FakeDshProcessLauncher(truth, "REL-1", tmp_path / "out", runner)
    binder = bind_production_model_economy(
        launcher, economy=economy, usage_audit=audit,
        metadata_resolver=lambda a: {
            "mission_id": a.mission_id,
            "attempt_id": a.attempt_id,
            "agent_id": a.agent_id,
            "workitem_id": a.scope,
            "node": "N3_CODE_ANALYSIS",
            "stage": "N3_CODE_REVIEW",
            "call_class": call_class,
            "mission_criticality": "BLOCKING",
            "semantic_cost_class": "HIGH",
        },
    )
    assert binder is launcher
    assert isinstance(launcher, DshHeadlessWorkerLauncher)
    return truth, economy, audit, launcher, runner


def _stdout(*, usage=True):
    final = {"type": "final", "text": "{}"}
    if usage:
        final.update({
            "provider": "bank-provider", "model": "bank-model",
            "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
        })
    events = [
        {"type": "session", "session_id": "dsh-real-session"},
        {"type": "tool_call", "tool_name": "codegraph"},
        final,
    ]
    return "\n".join(json.dumps(event) for event in events) + "\n"


def test_real_command_boundary_tracks_native_augmented_prompt_and_measured_usage(tmp_path):
    truth, economy, _, launcher, runner = _setup(tmp_path, stdout=_stdout())
    invocation, output = launcher.execute(_assignment(), "Semantic test requirement")
    assert output == {"status": "CONTRACT_ONLY"}
    assert len(runner.calls) == 1
    actual_prompt = runner.calls[0][0][-1]
    assert actual_prompt.startswith("NATIVE_APPROVED_CONTEXT\n")
    assert invocation.evidence_refs[0].startswith("file://")

    call = truth.query("rc72_token_call", mission_id="M-1")[0]
    assert call["state"] == "COMPLETED"
    assert call["usage_status"] == "MEASURED"
    assert call["total_tokens"] == 120
    assert call["context_sha256"] == hashlib.sha256(actual_prompt.encode("utf-8")).hexdigest()
    assert call["workitem_id"] == "WI-1"
    assert "MISSION_QUOTA_EQUIVALENT_TARGET_EXCEEDED" in call["economy_signal"]

    usage = truth.query("rc72_token_usage", mission_id="M-1")[0]
    assert usage["observation_status"] == "OBSERVED"
    assert usage["input_tokens"] == 100
    assert usage["output_tokens"] == 20
    assert usage["total_tokens"] == 120
    assert usage["provider"] == "bank-provider"
    assert usage["dsh_session_id"] == "dsh-real-session"
    assert economy.summary("M-1")["measured_total_tokens"] == 120
    assert economy.summary("M-1")["actual_total_tokens"] == 120
    assert economy.summary("M-1")["usage_total_status"] == "MEASURED"


def test_unknown_usage_never_becomes_measured_zero_or_blocks_required_next_call(tmp_path):
    truth, economy, _, launcher, runner = _setup(tmp_path, stdout=_stdout(usage=False))
    launcher.execute(_assignment(), "first required work")
    launcher.execute(_assignment(attempt="ATT-2", scope="WI-2"), "second required work")
    calls = truth.query("rc72_token_call", mission_id="M-1")
    assert len(calls) == 2 and len(runner.calls) == 2
    assert all(item["usage_status"] == "UNKNOWN" for item in calls)
    assert economy.summary("M-1")["unknown_usage_calls"] == 2
    assert economy.summary("M-1")["actual_total_tokens"] is None
    assert economy.summary("M-1")["usage_total_status"] == "UNKNOWN"
    assert economy.qualification("M-1").status == "HOLD"
    observations = truth.query("rc72_token_usage", mission_id="M-1")
    assert len(observations) == 2
    assert all(item["observation_status"] == "UNKNOWN" and item["total_tokens"] is None for item in observations)


def test_deterministic_work_is_blocked_before_any_dsh_process_is_spawned(tmp_path):
    truth, _, _, launcher, runner = _setup(
        tmp_path, stdout=_stdout(), call_class="DETERMINISTIC_NO_LLM",
    )
    with pytest.raises(TokenEconomyError, match="DETERMINISTIC_STEP_MUST_NOT_USE_LLM"):
        launcher.execute(_assignment(), "DB query that must use tools directly")
    assert runner.calls == []
    calls = truth.query("rc72_token_call", mission_id="M-1")
    assert len(calls) == 1
    assert calls[0]["state"] == "BLOCKED"
    assert calls[0]["usage_status"] == "PENDING"


def test_quota_pressure_only_warns_and_does_not_drop_mandatory_work(tmp_path):
    truth, _, _, launcher, runner = _setup(tmp_path, stdout=_stdout(), max_calls=1)
    launcher.execute(_assignment(), "first obligation")
    launcher.execute(_assignment(attempt="ATT-2", scope="WI-2"), "second obligation")
    assert len(runner.calls) == 2
    calls = truth.query("rc72_token_call", mission_id="M-1")
    assert {item["workitem_id"] for item in calls} == {"WI-1", "WI-2"}
    assert all(item["state"] == "COMPLETED" for item in calls)
    assert any("MISSION_MODEL_CALL_TARGET_EXCEEDED" in item["economy_signal"] for item in calls)


def test_process_exception_retains_unknown_usage_and_does_not_fabricate_success(tmp_path):
    truth, economy, _, launcher, runner = _setup(
        tmp_path, stdout="", error=TimeoutError("simulated provider timeout"),
    )
    with pytest.raises(TimeoutError):
        launcher.execute(_assignment(), "mandatory semantic work")
    assert len(runner.calls) == 1
    row = truth.query("rc72_token_call", mission_id="M-1")[0]
    assert row["state"] == "COMPLETED_UNKNOWN"
    assert row["usage_status"] == "UNKNOWN"
    assert economy.qualification("M-1").status == "HOLD"
    assert truth.query("rc72_token_usage", mission_id="M-1") == []


def test_unbound_runner_and_duplicate_hook_fail_closed(tmp_path):
    truth, economy, audit, launcher, runner = _setup(tmp_path, stdout=_stdout())
    with pytest.raises(ProductionEconomyBindingError, match="UNBOUND_DSH_PROCESS"):
        launcher.command_runner(["dsh", "--json", "not assigned"])
    assert runner.calls == []
    with pytest.raises(ProductionEconomyBindingError, match="DUPLICATE_BINDING"):
        bind_production_model_economy(
            launcher, economy=economy, usage_audit=audit,
            metadata_resolver=lambda a: {},
        )
    assert truth.query("rc72_token_call", mission_id="M-1") == []


def test_native_n1_launcher_type_is_preserved_without_changing_mission_factory_guard(tmp_path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    economy = TokenEconomyService(truth, release_id="REL-1")
    audit = TokenUsageAuditService(truth, release_id="REL-1")
    # Native subclass type must remain intact after binding, regardless of
    # the N1 read-gate's later service binding and actual Field admission.
    launcher = NativeN1ReadDshLauncher.__new__(NativeN1ReadDshLauncher)
    launcher.truth, launcher.release_id = truth, "REL-1"
    launcher.command_runner = lambda *args, **kwargs: None
    launcher.execute = lambda *args, **kwargs: None
    launcher._persist_raw_worker_output = lambda *args, **kwargs: "file://not-called"
    assert bind_production_model_economy(
        launcher, economy=economy, usage_audit=audit,
        metadata_resolver=lambda a: {},
    ) is launcher
    assert isinstance(launcher, DshHeadlessWorkerLauncher)
    assert isinstance(launcher, NativeN1ReadDshLauncher)


def test_native_tool_usage_must_not_be_recorded_as_provider_token_measurement(tmp_path):
    stdout = "\n".join([
        json.dumps({"type": "session", "session_id": "dsh-real-session"}),
        json.dumps({"type": "tool_result", "tool_name": "CAT", "usage": {
            "input_tokens": 900, "output_tokens": 100, "total_tokens": 1000,
        }}),
        json.dumps({"type": "final", "text": "{}"}),
    ]) + "\n"
    truth, economy, _, launcher, runner = _setup(tmp_path, stdout=stdout)
    launcher.execute(_assignment(), "must keep tool evidence separate")
    assert len(runner.calls) == 1
    call = truth.query("rc72_token_call", mission_id="M-1")[0]
    usage = truth.query("rc72_token_usage", mission_id="M-1")[0]
    assert call["usage_status"] == "UNKNOWN"
    assert usage["observation_status"] == "UNKNOWN"
    assert usage["total_tokens"] is None
    assert economy.summary("M-1")["actual_total_tokens"] is None


def test_conflicting_model_usage_snapshots_hold_measured_economy_qualification(tmp_path):
    stdout = "\n".join([
        json.dumps({"type": "message", "usage": {
            "input_tokens": 100, "output_tokens": 10, "total_tokens": 110,
        }}),
        json.dumps({"type": "final", "usage": {
            "input_tokens": 200, "output_tokens": 20, "total_tokens": 220,
        }}),
    ]) + "\n"
    truth, economy, _, launcher, runner = _setup(tmp_path, stdout=stdout)
    launcher.execute(_assignment(), "ambiguous cumulative or delta usage")
    call = truth.query("rc72_token_call", mission_id="M-1")[0]
    observation = truth.query("rc72_token_usage", mission_id="M-1")[0]
    assert call["usage_status"] == "UNKNOWN"
    assert observation["observation_status"] == "UNKNOWN"
    assert economy.qualification("M-1").status == "HOLD"



def test_native_runner_return_is_a_real_process_receipt_not_inference_count(tmp_path):
    truth, economy, _, launcher, runner = _setup(tmp_path, stdout=_stdout(usage=True))
    launcher.execute(_assignment(), "actual native runner")
    summary = economy.summary("M-1")
    assert len(runner.calls) == 1
    assert summary["dsh_process_invocations"] == 1
    assert summary["dsh_process_invocation_count_status"] == "MEASURED"
    assert summary["dsh_process_launch_error_count"] == 0
    assert summary["provider_inference_call_count"] is None
    assert summary["provider_inference_call_count_status"] == "UNKNOWN"
    call = truth.query("rc72_token_call", mission_id="M-1")[0]
    assert call["process_outcome"] == "RETURNED"


def test_native_runner_error_records_unknown_usage_and_zero_confirmed_process_returns(tmp_path):
    failure = RuntimeError("BANK_PROVIDER_UNAVAILABLE")
    truth, economy, _, launcher, runner = _setup(
        tmp_path, stdout="", error=failure,
    )
    with pytest.raises(RuntimeError, match="BANK_PROVIDER_UNAVAILABLE"):
        launcher.execute(_assignment(), "required task still pending")
    assert len(runner.calls) == 1
    summary = economy.summary("M-1")
    assert summary["dsh_process_invocation_count_status"] == "MEASURED"
    assert summary["dsh_process_invocations"] == 0
    assert summary["dsh_process_launch_error_count"] == 1
    assert summary["actual_total_tokens"] is None
    call = truth.query("rc72_token_call", mission_id="M-1")[0]
    assert call["process_outcome"] == "RAISED"
    assert call["usage_status"] == "UNKNOWN"
    assert economy.qualification("M-1").status == "HOLD"
