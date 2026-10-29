from pathlib import Path

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_deterministic_first import (
    DeterministicFirstEvaluator,
    DeterministicFirstRequest,
)
from rc7_runtime.rc72_model_economy import ModelCallClass


RELEASE = "RC7.2"


def _service(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    return truth, DeterministicFirstEvaluator(truth, release_id=RELEASE)


def _request(
    *,
    actual_code="OK",
    deterministic_complete=False,
    fresh_runtime_proof_required=False,
    operator="EQ",
):
    return DeterministicFirstRequest(
        mission_id="M-1",
        node="N7_EXECUTION",
        workitem_id="WI-1",
        attempt_id="ATT-1",
        evaluator_kind="BUSINESS_ORACLE",
        oracle_snapshot={
            "checks": [
                {
                    "id": "CHK-CODE",
                    "type": "BUSINESS_RULE",
                    "actual_path": "response.business_code",
                    "operator": operator,
                    "expected": "OK",
                    "evidence_ref": "design-evidence://business-code",
                }
            ]
        },
        actual_result={"response": {"business_code": actual_code}},
        context={"attempt_id": "ATT-1", "environment": "FAT1"},
        deterministic_complete=deterministic_complete,
        fresh_runtime_proof_required=fresh_runtime_proof_required,
    )


class SemanticSpy:
    def __init__(self, decision="PASS"):
        self.calls = 0
        self.decision = decision

    def __call__(self, request, deterministic):
        self.calls += 1
        assert request.mission_id == "M-1"
        assert deterministic["passed"] is True
        refs = [] if self.decision in {"UNKNOWN", "BLOCKED"} else ["EVD-SEMANTIC-1"]
        return {
            "decision": self.decision,
            "evidence_refs": refs,
            "summary": "semantic reviewer result",
        }


def test_deterministic_failure_is_conclusive_and_never_calls_model(tmp_path: Path):
    truth, service = _service(tmp_path)
    spy = SemanticSpy()

    outcome = service.evaluate(
        _request(actual_code="LIMIT_EXCEEDED"),
        semantic_evaluator=spy,
    )

    assert outcome.route == "DETERMINISTIC"
    assert outcome.decision == "FAIL"
    assert outcome.passed is False
    assert outcome.model_call_class == ModelCallClass.DETERMINISTIC_NO_LLM
    assert outcome.model_call_required is False
    assert outcome.model_call_invoked is False
    assert spy.calls == 0
    rows = truth.query("rc72_deterministic_first_evaluation", evaluation_id=outcome.evaluation_id)
    assert len(rows) == 1
    assert rows[0]["deterministic_assertion_ref"].startswith("oracle-assertion://")
    assert rows[0]["deterministic_evidence_refs"]


def test_complete_deterministic_pass_skips_model(tmp_path: Path):
    _, service = _service(tmp_path)
    spy = SemanticSpy()

    outcome = service.evaluate(
        _request(deterministic_complete=True),
        semantic_evaluator=spy,
    )

    assert outcome.route == "DETERMINISTIC"
    assert outcome.decision == "PASS"
    assert outcome.passed is True
    assert outcome.reason == "DETERMINISTIC_CONTRACT_COMPLETE"
    assert outcome.model_call_class == ModelCallClass.DETERMINISTIC_NO_LLM
    assert outcome.model_call_invoked is False
    assert spy.calls == 0


def test_incomplete_deterministic_pass_escalates_to_semantic_model_once(tmp_path: Path):
    _, service = _service(tmp_path)
    spy = SemanticSpy("PASS")

    outcome = service.evaluate(_request(), semantic_evaluator=spy)

    assert outcome.route == "SEMANTIC_MODEL"
    assert outcome.decision == "PASS"
    assert outcome.model_call_class == ModelCallClass.LLM_REQUIRED
    assert outcome.model_call_required is True
    assert outcome.model_call_invoked is True
    assert outcome.semantic_decision == "PASS"
    assert outcome.semantic_evidence_refs == ("EVD-SEMANTIC-1",)
    assert spy.calls == 1


def test_fresh_runtime_proof_prevents_deterministic_auto_pass(tmp_path: Path):
    _, service = _service(tmp_path)
    spy = SemanticSpy("PASS")

    outcome = service.evaluate(
        _request(deterministic_complete=True, fresh_runtime_proof_required=True),
        semantic_evaluator=spy,
    )

    assert outcome.route == "SEMANTIC_MODEL"
    assert outcome.model_call_required is True
    assert outcome.model_call_invoked is True
    assert spy.calls == 1


def test_unknown_semantic_result_stays_unknown_never_becomes_pass(tmp_path: Path):
    truth, service = _service(tmp_path)
    spy = SemanticSpy("UNKNOWN")

    outcome = service.evaluate(_request(), semantic_evaluator=spy)

    assert outcome.route == "SEMANTIC_MODEL"
    assert outcome.decision == "UNKNOWN"
    assert outcome.passed is False
    assert outcome.semantic_decision == "UNKNOWN"
    assert spy.calls == 1
    row = truth.query("rc72_deterministic_first_evaluation", evaluation_id=outcome.evaluation_id)[0]
    assert row["decision"] == "UNKNOWN"
    assert row["passed"] is False


def test_invalid_deterministic_contract_blocks_without_model_fallback(tmp_path: Path):
    _, service = _service(tmp_path)
    spy = SemanticSpy()

    outcome = service.evaluate(
        _request(operator="ASK_AI"),
        semantic_evaluator=spy,
    )

    assert outcome.route == "BLOCKED"
    assert outcome.decision == "BLOCKED"
    assert outcome.passed is False
    assert outcome.reason.startswith("DETERMINISTIC_CONTRACT_INVALID:")
    assert outcome.model_call_required is False
    assert outcome.model_call_invoked is False
    assert spy.calls == 0


def test_without_semantic_delegate_router_returns_model_required_not_fake_pass(tmp_path: Path):
    truth, service = _service(tmp_path)

    outcome = service.evaluate(_request(), semantic_evaluator=None)

    assert outcome.route == "SEMANTIC_MODEL"
    assert outcome.decision == "MODEL_REQUIRED"
    assert outcome.passed is False
    assert outcome.model_call_class == ModelCallClass.LLM_REQUIRED
    assert outcome.model_call_required is True
    assert outcome.model_call_invoked is False
    row = truth.query("rc72_deterministic_first_evaluation", evaluation_id=outcome.evaluation_id)[0]
    assert row["decision"] == "MODEL_REQUIRED"
    assert row["model_call_invoked"] is False


def test_fresh_proof_without_delegate_is_explicitly_model_required(tmp_path: Path):
    _, service = _service(tmp_path)

    outcome = service.evaluate(
        _request(deterministic_complete=True, fresh_runtime_proof_required=True),
        semantic_evaluator=None,
    )

    assert outcome.decision == "MODEL_REQUIRED"
    assert outcome.reason == "FRESH_RUNTIME_PROOF_REQUIRES_SEMANTIC_EVALUATOR"
    assert outcome.passed is False
