from pathlib import Path
import json
import subprocess

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc7_runtime.candidate_payload import CandidatePayloadReader
from rc7_runtime.dsh_code_evaluator import DshCodeEvaluator
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_n3_code_analysis_anchor import N3CodeAnalysisEvidenceAnchorService
from rc7_runtime.rc72_n3_code_analysis_handoff import N3CodeAnalysisDshHandoffService
from rc7_runtime.rc72_n3_code_analysis_promotion import N3CodeAnalysisCandidatePromotionService
from rc7_runtime.rc72_n3_code_analysis_review import N3CodeAnalysisReviewService

from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE
from test_rc72_n3_code_analysis_handoff import _ready


_CHANGED_FILE = "src/main/java/example/ChangedService.java"
_CHANGED_SYMBOL = "example.ChangedService#execute"


def _impact_surfaces():
    # The fixture enumerates every mandatory v2 impact dimension so the test
    # exercises the real deterministic gate rather than a StubEvaluator.
    kinds = (
        ("CALLER", "caller/callee graph impact"),
        ("API", "API/controller contract impact"),
        ("DATABASE", "persistence/data constraint impact"),
        ("CONFIG", "configuration impact"),
        ("MESSAGE", "event/message impact"),
        ("EXCEPTION", "error/exception impact"),
        ("TRANSACTION", "transaction boundary impact"),
        ("SIDE_EFFECT", "side-effect/state impact"),
        ("SECURITY", "authorization/security impact"),
        ("PERFORMANCE", "performance impact"),
    )
    return [
        {
            "id": "IMP-%02d-%s" % (index, kind),
            "kind": kind,
            "source_symbol_id": _CHANGED_SYMBOL,
            "source_file": _CHANGED_FILE,
            "reason": reason,
        }
        for index, (kind, reason) in enumerate(kinds, 1)
    ]


def _gate_ready_candidate(row):
    requirement_id = "REQ-%s" % row["application_id"]
    codegraph_ref = "tool://codegraph/%s" % row["target_id"]
    git_ref = "tool://git/%s" % row["target_id"]
    return {
        "status": "CANDIDATE",
        "application_id": row["application_id"],
        "target_id": row["target_id"],
        "repository_ref": row["repository_ref"],
        "source_revision": row["source_revision"],
        "requirement_ids": [requirement_id],
        "source_revisions": [row["source_revision"]],
        "changed_files": [_CHANGED_FILE],
        "changed_symbols": [_CHANGED_SYMBOL],
        "symbol_explanations": [
            {
                "symbol": _CHANGED_SYMBOL,
                "explanation": "real Git/CodeGraph backed downstream impact inventory",
                "evidence_refs": [codegraph_ref],
                "impact_surfaces": _impact_surfaces(),
                "impact_exclusions": [],
                "impact_dimension_exclusions": [],
            }
        ],
        "reverse_requirement_mappings": [
            {
                "requirement_id": requirement_id,
                "symbol": _CHANGED_SYMBOL,
                "evidence_ref": codegraph_ref,
            }
        ],
        "evidence_refs": [git_ref, codegraph_ref],
        "codegraph_required": True,
        "unknowns": [],
        "gaps": [],
    }


def _analyzer_launcher(tmp_path: Path, truth, row):
    dsh = tmp_path / "dsh-n3-gate-analyzer"
    dsh.write_text("fixture executable placeholder", encoding="utf-8")
    patch = tmp_path / "patch-n3-gate-analyzer.json"
    patch.write_text("{}", encoding="utf-8")

    def runner(command, **kwargs):
        prompt = str(command[-1])
        assert "RC72_N3_REAL_CODE_GATE_EXTENSION_V2" in prompt
        assert "impact_dimension_exclusions" in prompt
        assert row["repository_ref"] in prompt
        assert row["source_revision"] in prompt
        events = [
            {"type": "session", "session_id": "session-n3-real-gate-analyzer"},
            {"type": "tool_call", "tool_name": "git"},
            {"type": "tool_call", "tool_name": "codegraph"},
            {
                "type": "final",
                "text": json.dumps(_gate_ready_candidate(row), ensure_ascii=False),
            },
        ]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="\n".join(json.dumps(item, ensure_ascii=False) for item in events) + "\n",
            stderr="",
        )

    return DshHeadlessWorkerLauncher(
        dsh_bin=str(dsh),
        patch_path=str(patch),
        cwd=str(tmp_path),
        truth=truth,
        authority=RC72AuthorityRuntime(b"rc72-n3-real-gate-analyzer-key"),
        coordinator_instance_id="coordinator-n3-real-gate-analyzer",
        release_id=RELEASE,
        state_root=str(tmp_path / "state-n3-code"),
        command_runner=runner,
    )


def _reviewer_launcher(tmp_path: Path, truth):
    dsh = tmp_path / "dsh-n3-gate-reviewer"
    dsh.write_text("fixture executable placeholder", encoding="utf-8")
    patch = tmp_path / "patch-n3-gate-reviewer.json"
    patch.write_text("{}", encoding="utf-8")

    def runner(command, **kwargs):
        prompt = str(command[-1])
        assert "independent RC7 Code Sufficiency Reviewer" in prompt
        assert "impact_surfaces" in prompt
        events = [
            {"type": "session", "session_id": "session-n3-real-gate-reviewer"},
            {"type": "tool_call", "tool_name": "git"},
            {"type": "tool_call", "tool_name": "codegraph"},
            {
                "type": "final",
                "text": json.dumps(
                    {
                        "decision": "PASS",
                        "gap_ids": [],
                        "summary": "independent real-tool review accepts the impact inventory",
                    }
                ),
            },
        ]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="\n".join(json.dumps(item) for item in events) + "\n",
            stderr="",
        )

    return DshHeadlessWorkerLauncher(
        dsh_bin=str(dsh),
        patch_path=str(patch),
        cwd=str(tmp_path),
        truth=truth,
        authority=RC72AuthorityRuntime(b"rc72-n3-real-gate-reviewer-key"),
        coordinator_instance_id="coordinator-n3-real-gate-reviewer",
        release_id=RELEASE,
        state_root=str(tmp_path / "state-n3-code-review"),
        command_runner=runner,
    )


def test_gate_ready_analyzer_candidate_passes_real_dsh_code_evaluator(tmp_path: Path):
    truth, _dispatched, assigned = _ready(tmp_path)
    row = assigned["assignments"][0]

    handoff = N3CodeAnalysisDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_analyzer_launcher(tmp_path, truth, row),
    ).handoff(
        release_batch_id=BATCH,
        target_id=row["target_id"],
    )
    assert handoff["dsh_session_id"] == "session-n3-real-gate-analyzer"

    anchor = N3CodeAnalysisEvidenceAnchorService(
        truth,
        source_commit=COMMIT,
        state_root=str(tmp_path / "state-n3-code"),
    ).anchor(
        release_batch_id=BATCH,
        target_id=row["target_id"],
    )
    promoted = N3CodeAnalysisCandidatePromotionService(
        truth,
        release_id=RELEASE,
        mission_id=MISSION,
        source_commit=COMMIT,
        state_root=str(tmp_path / "state-n3-code"),
    ).promote(
        release_batch_id=BATCH,
        target_id=row["target_id"],
    )
    assert promoted["task_state"] == "OUTPUT_PRODUCED"
    assert promoted["changed_symbols"] == [_CHANGED_SYMBOL]

    durable = CandidatePayloadReader().load(
        truth,
        promoted["artifact_id"],
        expected_mission_id=MISSION,
        expected_task_id=promoted["task_id"],
    )
    semantic = dict(durable.semantic_payload)
    assert semantic["gate_contract"] == "RC72_N3_REAL_CODE_GATE_EXTENSION_V2"
    assert semantic["source_revisions"] == {row["repository_ref"]: row["source_revision"]}
    assert semantic["changed_symbols"] == [{"id": _CHANGED_SYMBOL}]
    assert semantic["symbol_explanations"][0]["symbol_id"] == _CHANGED_SYMBOL
    assert semantic["reverse_requirement_mappings"][0]["symbol_id"] == _CHANGED_SYMBOL
    assert len(semantic["impact_surfaces"]) == 10
    assert semantic["impact_dimension_exclusions"] == []
    assert semantic["sufficiency_v2_required"] is True

    evaluator = DshCodeEvaluator(
        _reviewer_launcher(tmp_path, truth),
        reviewer_allowed_tools=("git", "codegraph"),
    )
    reviewed = N3CodeAnalysisReviewService(
        truth,
        release_id=RELEASE,
        mission_id=MISSION,
        source_commit=COMMIT,
        evaluator=evaluator,
    ).review(
        release_batch_id=BATCH,
        target_id=row["target_id"],
    )

    assert reviewed["status"] == "REVIEW_APPLIED"
    assert reviewed["task_state"] == "PASS"
    assert reviewed["gate_status"] == "SUFFICIENT"
    assert reviewed["analyzer_session_id"] == "session-n3-real-gate-analyzer"
    assert reviewed["reviewer_session_id"] == "session-n3-real-gate-reviewer"
    assert reviewed["reviewer_session_id"] != reviewed["analyzer_session_id"]
    assert reviewed["analyzer_tool_evidence_ids"]
    assert reviewed["reviewer_evidence_ids"]

    evaluation = truth.query(
        "rc7_evaluation", evaluation_id=reviewed["evaluation_id"]
    )[0]
    assert evaluation["result"] == "PASS"
    assert evaluation["dimensions"]["gate_status"] == "SUFFICIENT"
    assert evaluation["dimensions"]["code_impact_sufficiency_v2_ready"] is True
    impact = evaluation["dimensions"]["metrics"]["impact_sufficiency_v2"]
    assert impact["status"] == "SUFFICIENT"
    assert impact["unaccounted_dimensions"] == []
    assert impact["uncovered_symbol_ids"] == []
    assert impact["uncovered_files"] == []

    n3 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N3_CODE_ANALYSIS"
    )[0]
    n4 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    )[0]
    assert n3["state"] == "RUNNING"
    assert n4["state"] == "NOT_STARTED"
    assert truth.query(
        "rc72_node_delivery", mission_id=MISSION, node_type="N3_CODE_ANALYSIS"
    ) == []
    assert truth.query(
        "rc72_node_gate", mission_id=MISSION, node_type="N3_CODE_ANALYSIS"
    ) == []


def test_legacy_candidate_without_impact_inventory_stays_fail_closed_under_real_gate(
    tmp_path: Path,
):
    # Existing V1 analyzer fixtures remain replayable for compatibility, but
    # their lack of impact inventory must not be silently upgraded to PASS.
    from test_rc72_n3_code_analysis_review import _ready_for_review

    truth, assignment, _anchor_row, promoted = _ready_for_review(tmp_path)
    evaluator = DshCodeEvaluator(
        _reviewer_launcher(tmp_path, truth),
        reviewer_allowed_tools=("git", "codegraph"),
    )
    reviewed = N3CodeAnalysisReviewService(
        truth,
        release_id=RELEASE,
        mission_id=MISSION,
        source_commit=COMMIT,
        evaluator=evaluator,
    ).review(
        release_batch_id=BATCH,
        target_id=assignment["target_id"],
    )

    assert reviewed["task_id"] == promoted["task_id"]
    assert reviewed["task_state"] == "REPAIR_REQUIRED"
    assert reviewed["gate_status"] == "NOT_SUFFICIENT_CONTENT"
    evaluation = truth.query(
        "rc7_evaluation", evaluation_id=reviewed["evaluation_id"]
    )[0]
    reasons = list(evaluation["dimensions"]["reasons"])
    assert any(reason.startswith("CODE_IMPACT_") for reason in reasons)
    n4 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    )[0]
    assert n4["state"] == "NOT_STARTED"
