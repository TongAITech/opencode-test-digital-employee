"""Real native batch-call boundary, separate N7 WorkItems and evaluator sessions."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_context_economy import (
    ContextAffinity, ExecutionBatchPlanner, ExecutionMode, SemanticWorkDescriptor,
)
from rc7_runtime.rc72_model_economy import (
    MissionCriticality, SemanticCostClass, TokenEconomyService,
)
from rc7_runtime.rc72_model_usage import TokenUsageAuditService
from rc7_runtime.rc72_production_economy_wiring import (
    ProductionEconomyBindingError, bind_production_model_economy,
)
from rc7_runtime.rc72_native_shared_batch_composition import compose_native_batch_services
from rc7_runtime.rc72_native_shared_batch import (
    NativeSharedBatchError, NativeSharedExecutionBatch,
    canonical_batch_metadata_resolver, install_native_batch_candidate_overlay,
)
from rc7_runtime.rc72_native_shared_batch_review import (
    NativeBatchReviewError, NativeSharedEvaluatorBatch,
    install_native_batch_review_overlay,
)
from rc7_runtime.rc72_schedule_semantics import WorkScheduleSemanticsService
from rc7_runtime.rc72_safe_execution_batch import install_rc72_safe_execution_batch_overlay
from rc7_runtime.rc72_truth import install_rc72_truth_overlay


MISSION = "M-REAL-SHARED"
RELEASE = "REL-REAL-SHARED"


class _NativeDshLauncher(DshHeadlessWorkerLauncher):
    """Uses the exact metered native command_runner and persisted JSONL boundaries."""

    def __init__(self, truth, root, name, response, *, session_id):
        self.truth = truth
        self.release_id = RELEASE
        self.state_root = root / name
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id
        self.response = response
        self.execute_count = 0
        self.native_calls = []
        self.command_runner = self._runner

    def _runner(self, command, **kwargs):
        self.native_calls.append(tuple(command))
        events = [{"type": "session", "session_id": self.session_id}]
        calls = 2 if "execution" in self.state_root.name else 1
        for _ in range(calls):
            events.append({"type": "tool_call", "tool_name": "approved-real-tool"})
        events.append({
            "type": "final",
            "provider": "bank-model",
            "usage": {"input_tokens": 50, "output_tokens": 20, "total_tokens": 70},
            "text": json.dumps(self.response),
        })
        return SimpleNamespace(
            stdout="\n".join(json.dumps(event) for event in events) + "\n",
            stderr="", returncode=0,
        )

    def _persist_raw_worker_output(self, assignment, stdout, stderr):
        destination = self.state_root / (assignment.assignment_id + ".jsonl")
        destination.write_text(stdout, encoding="utf-8")
        return "file://" + destination.as_posix()

    def execute(self, assignment, prompt):
        self.execute_count += 1
        response = self.command_runner(["dsh", "--json", "NATIVE_APPROVED\n" + prompt])
        evidence_ref = self._persist_raw_worker_output(assignment, response.stdout, response.stderr)
        events = [json.loads(line) for line in response.stdout.splitlines()]
        calls = [
            {"call_ref": "dsh-event://tool-call/%d" % index, "tool_name": event["tool_name"]}
            for index, event in enumerate(events) if event.get("type") == "tool_call"
        ]
        return (
            SimpleNamespace(
                dsh_session_id=self.session_id,
                evidence_refs=[evidence_ref],
                tool_calls=calls,
            ),
            self.response,
        )


def _descriptor(workitem):
    return SemanticWorkDescriptor(
        workitem_id=workitem,
        mission_id=MISSION, node="EXECUTION", stage="N7",
        execution_mode=ExecutionMode.SEMANTIC,
        mission_criticality=MissionCriticality.BLOCKING,
        semantic_cost_class=SemanticCostClass.HIGH,
        affinity=ContextAffinity(
            requirement_id="REQ-REAL", sst_id="SST-REAL", service="cfg-scd",
            environment="FAT1", data_domain="loan", oracle_family="api-db",
            tool_family="dsh-agent-teams",
        ),
        input_refs=("ART-SOURCE-SHARED", "CASE-" + workitem),
    )


def _binding(truth, workitem, attempt):
    truth.append_atomic("RC72_WORKITEM_ATTEMPT_BINDING_UPSERTED", {
        "binding_id": "BIND-" + workitem, "release_id": RELEASE,
        "mission_id": MISSION, "etu_id": "ETU-" + workitem,
        "workitem_id": workitem, "case_id": "CASE-" + workitem,
        "attempt_id": attempt, "state": "RESERVED",
        "worker_id": None, "session_id": None, "task_lease_ref": None,
        "capability_lease_refs": [], "resource_lease_refs": [],
        "parent_attempt_id": None, "mission_node_id": "MN-N7",
        "mission_node_type": "N7_EXECUTION",
        "mission_node_lineage_status": "RESOLVED",
        "mission_node_lineage_reason": None,
        "created_at": 1, "updated_at": 1, "artifact_version": 1,
    })


def _execution_output():
    return {
        "status": "CANDIDATE",
        "members": [
            {
                "workitem_id": "WI-1", "attempt_id": "ATT-1",
                "observed_tool_refs": ["dsh-event://tool-call/1"],
                "proposed_observation": "negative API case was dispatched; oracle still needs verification",
                "gaps": [], "unknowns": [],
            },
            {
                "workitem_id": "WI-2", "attempt_id": "ATT-2",
                "observed_tool_refs": ["dsh-event://tool-call/2"],
                "proposed_observation": "boundary case real tool invoked; actual DB oracle still open",
                "gaps": ["DATABASE_SIDE_EFFECT_NOT_YET_PROVEN"], "unknowns": [],
            },
        ],
    }


def _review_output():
    return {
        "status": "REVIEW_CANDIDATE",
        "members": [
            {
                "workitem_id": "WI-1", "attempt_id": "ATT-1",
                "evidence_adequacy": "SUFFICIENT_CANDIDATE",
                "criticisms": [], "required_followups": ["deterministic N7 oracle replay"],
            },
            {
                "workitem_id": "WI-2", "attempt_id": "ATT-2",
                "evidence_adequacy": "INSUFFICIENT",
                "criticisms": ["DB side effects not observed"],
                "required_followups": ["N8 repair and independent N7 reexecution"],
            },
        ],
    }


def _fixture(tmp_path):
    install_rc72_truth_overlay()
    install_rc72_safe_execution_batch_overlay()
    install_native_batch_candidate_overlay()
    install_native_batch_review_overlay()
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    _binding(truth, "WI-1", "ATT-1")
    _binding(truth, "WI-2", "ATT-2")
    semantics = WorkScheduleSemanticsService(truth, release_id=RELEASE)
    for workitem in ("WI-1", "WI-2"):
        semantics.record(
            mission_id=MISSION, workitem_id=workitem,
            execution_mode=ExecutionMode.SEMANTIC,
            mission_criticality=MissionCriticality.BLOCKING,
            semantic_cost_class=SemanticCostClass.HIGH,
            source_ref="r1://accepted/semantic-batch/" + workitem,
        )
    plan = ExecutionBatchPlanner(max_batch_size=8).plan([
        _descriptor("WI-1"), _descriptor("WI-2")
    ])
    assert len(plan.batches) == 1
    batch = plan.batches[0]
    refs = set(batch.context_envelope.shared_refs)
    for item in batch.context_envelope.workitem_refs.values():
        refs.update(item)
    execution = _NativeDshLauncher(
        truth, tmp_path / "native", "execution",
        _execution_output(), session_id="session-execution",
    )
    reviewer = _NativeDshLauncher(
        truth, tmp_path / "native", "reviewer",
        _review_output(), session_id="session-reviewer",
    )
    economy = TokenEconomyService(truth, release_id=RELEASE)
    economy.configure_budget(
        mission_id=MISSION, max_total_tokens=10000, max_model_calls=10,
        max_single_call_tokens=500, max_retry_tokens=10000,
        max_retry_calls=10,
    )
    audit = TokenUsageAuditService(truth, release_id=RELEASE)
    services = compose_native_batch_services(
        truth, release_id=RELEASE, mission_id=MISSION,
        execution_launcher=execution, evaluator_launcher=reviewer,
        economy=economy, usage_audit=audit,
    )
    assert isinstance(services.execution, NativeSharedExecutionBatch)
    assert isinstance(services.evaluator, NativeSharedEvaluatorBatch)
    exec_assignment = SimpleNamespace(
        mission_id=MISSION, scope="execution-batch:" + batch.batch_id,
        assignment_id="AS-BATCH-EXEC", attempt_id="ATT-BATCH-EXEC",
        worker_instance_id="worker-execution", agent_id="shared-executor",
        input_refs=tuple(sorted(refs)), allowed_tools=("approved-real-tool",),
    )
    return truth, economy, batch, execution, reviewer, exec_assignment


def _dispatch(truth, batch, execution, assignment):
    return NativeSharedExecutionBatch(
        truth, release_id=RELEASE, launcher=execution,
    ).dispatch(
        batch, attempt_ids_by_workitem={"WI-1": "ATT-1", "WI-2": "ATT-2"},
        assignment=assignment,
    )


def _review_assignment(batch_id, raw, *, worker="worker-reviewer", session_attempt="ATT-BATCH-REVIEW"):
    return SimpleNamespace(
        mission_id=MISSION, scope="evaluation-batch:" + batch_id,
        assignment_id="AS-BATCH-REVIEW", attempt_id=session_attempt,
        worker_instance_id=worker, agent_id="independent-batch-reviewer",
        input_refs=(raw,), allowed_tools=("read-evidence",),
    )


def test_two_real_native_batch_calls_keep_independent_case_attempts_and_review_sessions(tmp_path):
    truth, economy, batch, execution, reviewer, assignment = _fixture(tmp_path)
    candidate = _dispatch(truth, batch, execution, assignment)
    assert candidate["status"] == "UNVERIFIED"
    assert len(candidate["members"]) == 2
    assert candidate["token_call_id"] == truth.query(
        "rc72_token_call", workitem_id="EXECUTION_BATCH:" + batch.batch_id
    )[0]["call_id"]
    assert candidate["members"][0]["observed_tool_refs"] != candidate["members"][1]["observed_tool_refs"]
    assert execution.execute_count == 1
    assert len(execution.native_calls) == 1
    raw_execution = execution.native_calls[0][-1]
    assert "CASE-WI-1" in raw_execution and "CASE-WI-2" in raw_execution
    assert "ART-SOURCE-SHARED" in raw_execution
    before = truth.query("rc72_workitem_attempt_binding", mission_id=MISSION)
    assert len(before) == 2 and {row["state"] for row in before} == {"RESERVED"}

    reviewed = NativeSharedEvaluatorBatch(
        truth, release_id=RELEASE, launcher=reviewer,
    ).review(
        candidate_id=candidate["candidate_id"],
        assignment=_review_assignment(batch.batch_id, candidate["raw_output_ref"]),
    )
    assert reviewer.execute_count == 1
    assert len(reviewer.native_calls) == 1
    assert reviewed["status"] == "UNVERIFIED_INDEPENDENT_REVIEW"
    assert reviewed["token_call_id"] == truth.query(
        "rc72_token_call", workitem_id="EVALUATOR_BATCH:" + batch.batch_id
    )[0]["call_id"]
    assert reviewed["dsh_session_id"] != candidate["dsh_session_id"]
    assert reviewed["worker_instance_id"] != candidate["worker_instance_id"]
    assert {x["workitem_id"] for x in reviewed["members"]} == {"WI-1", "WI-2"}
    assert {x["evidence_adequacy"] for x in reviewed["members"]} == {
        "SUFFICIENT_CANDIDATE", "INSUFFICIENT",
    }

    token_calls = truth.query("rc72_token_call", mission_id=MISSION)
    assert len(token_calls) == 2
    assert {row["workitem_id"] for row in token_calls} == {
        "EXECUTION_BATCH:" + batch.batch_id,
        "EVALUATOR_BATCH:" + batch.batch_id,
    }
    assert {row["usage_status"] for row in token_calls} == {"MEASURED"}
    assert economy.summary(MISSION)["dsh_process_invocations"] == 2
    assert economy.summary(MISSION)["provider_inference_call_count"] is None
    assert truth.query("rc72_execution_batch_receipt", batch_id=batch.batch_id)[0]["state"] == "ADMITTED"
    assert truth.query("execution_attempt", release_id=RELEASE) == []
    assert truth.query("assertion", release_id=RELEASE) == []
    assert truth.query("rc72_node_gate", mission_id=MISSION) == []
    assert {row["state"] for row in truth.query("rc72_workitem_attempt_binding", mission_id=MISSION)} == {"RESERVED"}

    # Cold R1 replay preserves candidate, review, and exact member denominator.
    replay = TruthRuntime(tmp_path / "r1.jsonl")
    assert replay.query("rc72_native_batch_candidate", candidate_id=candidate["candidate_id"])[0]["status"] == "UNVERIFIED"
    assert replay.query("rc72_native_batch_review", review_id=reviewed["review_id"])[0]["members"] == reviewed["members"]
    assert len(replay.query("rc72_token_call", mission_id=MISSION)) == 2


def test_native_batch_cold_resume_is_idempotent_without_second_model_call(tmp_path):
    truth, _, batch, execution, reviewer, assignment = _fixture(tmp_path)
    first = _dispatch(truth, batch, execution, assignment)
    again = _dispatch(truth, batch, execution, assignment)
    assert first == again and execution.execute_count == 1
    r_assignment = _review_assignment(batch.batch_id, first["raw_output_ref"])
    service = NativeSharedEvaluatorBatch(
        truth, release_id=RELEASE, launcher=reviewer,
    )
    review = service.review(candidate_id=first["candidate_id"], assignment=r_assignment)
    assert service.review(candidate_id=first["candidate_id"], assignment=r_assignment) == review
    assert reviewer.execute_count == 1


@pytest.mark.parametrize("mutation, expected", [
    ("MISSING_MEMBER", "DENOMINATOR"),
    ("FORGED_ATTEMPT", "LINEAGE"),
    ("SHARED_TOOL_REF", "TOOL_PROOF"),
    ("FAKE_TOOL_REF", "TOOL_PROOF"),
    ("MODEL_ASSERTS_PASS", "MODEL_CANNOT_ASSERT_PASS"),
])
def test_native_batch_never_persists_fabricated_or_incomplete_member_evidence(tmp_path, mutation, expected):
    truth, _, batch, execution, _, assignment = _fixture(tmp_path)
    output = _execution_output()
    if mutation == "MISSING_MEMBER":
        output["members"].pop()
    elif mutation == "FORGED_ATTEMPT":
        output["members"][1]["attempt_id"] = "ATT-FORGED"
    elif mutation == "SHARED_TOOL_REF":
        output["members"][1]["observed_tool_refs"] = ["dsh-event://tool-call/1"]
    elif mutation == "FAKE_TOOL_REF":
        output["members"][1]["observed_tool_refs"] = ["dsh-event://tool-call/9999"]
    elif mutation == "MODEL_ASSERTS_PASS":
        output["status"] = "PASS"
    execution.response = output
    with pytest.raises(NativeSharedBatchError, match=expected):
        _dispatch(truth, batch, execution, assignment)
    assert execution.execute_count == 1
    assert truth.query("rc72_native_batch_candidate", mission_id=MISSION) == []
    assert truth.query("execution_attempt", release_id=RELEASE) == []
    assert truth.query("assertion", release_id=RELEASE) == []


def test_wrong_batch_lease_or_input_scope_blocks_before_native_tool_dispatch(tmp_path):
    truth, _, batch, execution, _, assignment = _fixture(tmp_path)
    assignment.scope = "execution-batch:FAKE"
    with pytest.raises(NativeSharedBatchError, match="SCOPED_LEASE"):
        _dispatch(truth, batch, execution, assignment)
    assert execution.execute_count == 0
    assert truth.query("rc72_execution_batch_receipt", mission_id=MISSION) == []

    assignment.scope = "execution-batch:" + batch.batch_id
    assignment.input_refs = ("ART-SOURCE-SHARED",)
    with pytest.raises(NativeSharedBatchError, match="INPUT_LEASE_REFS_MISMATCH"):
        _dispatch(truth, batch, execution, assignment)
    assert execution.execute_count == 0


def test_independent_evaluator_never_accepts_same_worker_session_or_model_pass(tmp_path):
    truth, _, batch, execution, reviewer, assignment = _fixture(tmp_path)
    candidate = _dispatch(truth, batch, execution, assignment)
    service = NativeSharedEvaluatorBatch(
        truth, release_id=RELEASE, launcher=reviewer,
    )
    with pytest.raises(NativeBatchReviewError, match="WORKER_MUST_DIFFER"):
        service.review(
            candidate_id=candidate["candidate_id"],
            assignment=_review_assignment(
                batch.batch_id, candidate["raw_output_ref"],
                worker=candidate["worker_instance_id"],
            ),
        )
    assert reviewer.execute_count == 0
    reviewer.session_id = candidate["dsh_session_id"]
    with pytest.raises(NativeBatchReviewError, match="SESSION_NOT_FRESH"):
        service.review(
            candidate_id=candidate["candidate_id"],
            assignment=_review_assignment(batch.batch_id, candidate["raw_output_ref"]),
        )
    assert truth.query("rc72_native_batch_review", mission_id=MISSION) == []

    reviewer.session_id = "session-independent-new"
    reviewer.response = {"status": "PASS", "members": _review_output()["members"]}
    with pytest.raises(NativeBatchReviewError, match="MODEL_CANNOT_ASSERT_PASS"):
        service.review(
            candidate_id=candidate["candidate_id"],
            assignment=_review_assignment(
                batch.batch_id, candidate["raw_output_ref"],
                session_attempt="ATT-BATCH-REVIEW-NEW",
            ),
        )
    assert truth.query("rc72_native_batch_review", mission_id=MISSION) == []



def test_deterministic_or_missing_semantic_truth_never_spawns_dsh_batch(tmp_path):
    truth, _, batch, execution, _, assignment = _fixture(tmp_path)
    WorkScheduleSemanticsService(truth, release_id=RELEASE).record(
        mission_id=MISSION, workitem_id="WI-2",
        execution_mode=ExecutionMode.DETERMINISTIC,
        mission_criticality=MissionCriticality.BLOCKING,
        semantic_cost_class=SemanticCostClass.LOW,
        source_ref="r1://accepted/deterministic-tools-only/WI-2",
    )
    with pytest.raises(NativeSharedBatchError, match="DETERMINISTIC_OR_HYBRID_TOOL_FIRST"):
        _dispatch(truth, batch, execution, assignment)
    assert execution.execute_count == 0
    assert truth.query("rc72_execution_batch_receipt", mission_id=MISSION) == []
    assert truth.query("rc72_native_batch_candidate", mission_id=MISSION) == []



def test_batch_composer_rejects_nonindependent_or_prebound_workers_before_partial_hooking(tmp_path):
    truth, economy, batch, execution, reviewer, _ = _fixture(tmp_path)
    audit = TokenUsageAuditService(truth, release_id=RELEASE)
    clone = _NativeDshLauncher(
        truth, tmp_path / "clone", "unbound",
        _execution_output(), session_id="session-new",
    )
    with pytest.raises(ProductionEconomyBindingError, match="INDEPENDENT_LAUNCHERS_REQUIRED"):
        compose_native_batch_services(
            truth, release_id=RELEASE, mission_id=MISSION,
            execution_launcher=clone, evaluator_launcher=clone,
            economy=economy, usage_audit=audit,
        )
    assert not getattr(clone, "_rc72_production_economy_bound", False)

    with pytest.raises(ProductionEconomyBindingError, match="NATIVE_BATCH_LAUNCHER_INVALID"):
        compose_native_batch_services(
            truth, release_id=RELEASE, mission_id=MISSION,
            execution_launcher=clone, evaluator_launcher=reviewer,
            economy=economy, usage_audit=audit,
        )
    assert not getattr(clone, "_rc72_production_economy_bound", False)
    assert truth.query("rc72_token_call", mission_id=MISSION) == []
