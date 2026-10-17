from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from rc6_runtime.automation import ProcessStepResult, ScriptArtifact, ScriptValidation
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.bank_mission import start_or_resume
from rc7_runtime.case_fanout_conformance import AcceptedCaseInventoryReader, record_script_ready
from rc7_runtime.case_script_bundle_resolver import (
    CaseScriptBundleResolverError,
    CaseScriptExecutionBundleResolver,
)
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.models import Artifact, Evaluation, EvaluationResult, Evidence, TaskStatus
from rc7_runtime.script_contract import AcceptedTestDesignScriptContractCompiler
from rc7_runtime.truth_overlay import append_entity


MISSION = "MISSION-BUNDLE-RESOLVE"
RELEASE = "REL-BUNDLE-RESOLVE"
DESIGN_ARTIFACT = "ART-TD-BUNDLE-RESOLVE"
SCRIPT_ARTIFACT = "ART-SCRIPT-BUNDLE-RESOLVE"


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


def _case():
    return {
        "tc_id": "TC-BUNDLE-1",
        "case_version": 1,
        "requirement_id": "REQ-BUNDLE",
        "sst_id": "SST-BUNDLE",
        "layer": "L2",
        "preconditions": [],
        "test_data": {
            "initial_state": [],
            "input_data": [],
            "cleanup_policy": {"mode": "NONE", "required": False},
        },
        "cleanup_policy": {"mode": "NONE", "required": False},
        "steps": [{"action": "query", "target": "loan"}],
        "expected": "loan returned",
        "oracle": {"checks": [{"type": "BUSINESS_RULE", "expected": "FOUND"}]},
        "evidence_requirements": ["runner-output"],
        "target_requirements": ["REQ-BUNDLE"],
        "test_data_refs": [],
        "oracle_refs": ["oracle://bundle/found"],
        "runner_type": "PYTEST",
        "coverage_links": [],
    }


def _setup(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PFC_RC7_SOURCE_COMMIT", "b" * 40)
    r1 = tmp_path / "runtime-state" / "r1" / "event-stream.jsonl"
    start_or_resume(
        r1_path=str(r1),
        mission_id=MISSION,
        release_id=RELEASE,
        goal="rebuild exact case execution bundle from R1",
        graph_version="v2",
    )
    truth = TruthRuntime(r1)
    control = ClosedLoopControlPlane(truth, RELEASE, MISSION)
    design_row = next(row for row in truth.query("rc7_task", mission_id=MISSION) if row.get("node") == "TEST_DESIGN")
    script_row = next(row for row in truth.query("rc7_task", mission_id=MISSION) if row.get("node") == "SCRIPT_READINESS")
    design_task_id = str(design_row["task_id"])
    script_task_id = str(script_row["task_id"])

    design_evidence = Evidence(
        evidence_id="EVD-TD-BUNDLE",
        mission_id=MISSION,
        kind="TEST_DESIGN_SOURCE",
        source_ref="dsh://test-design",
        content_ref="evidence://td-bundle",
        subject_refs=[design_task_id],
    )
    append_entity(truth, design_evidence, release_id=RELEASE, artifact_version=1)
    envelope = {
        "task_id": design_task_id,
        "artifact": {
            "artifact_id": DESIGN_ARTIFACT,
            "artifact_type": "TEST_DESIGN_MODEL",
            "content_ref": "runtime://accepted-design",
            "parent_refs": [],
            "evidence_refs": [design_evidence.evidence_id],
        },
        "semantic_payload": {"cases": [_case()], "obligations": [{"obligation_id": "OB-1"}]},
        "evidence": [],
    }
    raw = (json.dumps(envelope, sort_keys=True, indent=2) + "\n").encode()
    design_path = tmp_path / "accepted-design.json"
    design_path.write_bytes(raw)
    append_entity(
        truth,
        Artifact(
            artifact_id=DESIGN_ARTIFACT,
            mission_id=MISSION,
            artifact_type="TEST_DESIGN_MODEL",
            producer_task_id=design_task_id,
            content_ref="file://" + str(design_path.resolve()),
            evidence_refs=[design_evidence.evidence_id],
            content_hash="sha256:" + hashlib.sha256(raw).hexdigest(),
        ),
        release_id=RELEASE,
        artifact_version=1,
    )
    evaluation = Evaluation(
        evaluation_id="EVAL-TD-BUNDLE",
        mission_id=MISSION,
        node="TEST_DESIGN",
        artifact_refs=[DESIGN_ARTIFACT],
        result=EvaluationResult.PASS,
        evaluator_ref="independent-test-design-reviewer",
        evidence_refs=[design_evidence.evidence_id],
    )
    append_entity(truth, evaluation, release_id=RELEASE, artifact_version=1)
    task = control.scheduler.task(design_task_id)
    task.state = TaskStatus.PASS
    task.output_artifact_refs = [DESIGN_ARTIFACT]
    task.evaluation_id = evaluation.evaluation_id
    append_entity(truth, task, release_id=RELEASE, artifact_version=int(design_row["artifact_version"]) + 1)

    contract = AcceptedTestDesignScriptContractCompiler().compile(
        truth,
        mission_id=MISSION,
        design_artifact_id=DESIGN_ARTIFACT,
        tc_id="TC-BUNDLE-1",
        automation_mapping={"reuse": {}},
    )
    source_text = "def test_bundle_case():\n    actual = 1\n    assert actual == 1\n"
    source_path = tmp_path / "test_bundle_generated.py"
    source_path.write_text(source_text, encoding="utf-8")
    source_digest = hashlib.sha256(source_text.encode()).hexdigest()
    script_id = _stable_id("SCRIPT-RC7", MISSION, contract.spec.spec_id, source_digest, "test_bundle_case")
    binding = {
        "spec_id": contract.spec.spec_id,
        "tc_id": contract.spec.tc_id,
        "case_version": contract.spec.case_version,
        "runner_type": contract.spec.runner_type,
        "case_fingerprint": contract.spec.case_fingerprint,
        "oracle_fingerprint": contract.spec.oracle_fingerprint,
        "design_content_hash": contract.design_content_hash,
    }
    script_envelope = {
        "task_id": script_task_id,
        "artifact": {
            "artifact_id": SCRIPT_ARTIFACT,
            "artifact_type": "EXECUTABLE_SCRIPT",
            "content_ref": "worker://script",
            "parent_refs": [DESIGN_ARTIFACT],
            "evidence_refs": ["EVD-SCRIPT-CANDIDATE"],
        },
        "semantic_payload": {
            "binding": binding,
            "source_text": source_text,
            "test_symbol": "test_bundle_case",
        },
        "evidence": [],
    }
    script_raw = (json.dumps(script_envelope, sort_keys=True, indent=2) + "\n").encode()
    candidate_path = tmp_path / "script-candidate.json"
    candidate_path.write_bytes(script_raw)
    candidate_evidence = Evidence(
        evidence_id="EVD-SCRIPT-CANDIDATE",
        mission_id=MISSION,
        kind="DSH_SCRIPT_BUILD_PROOF",
        source_ref="dsh://script-worker",
        content_ref="evidence://script-candidate",
        subject_refs=[script_task_id],
    )
    append_entity(truth, candidate_evidence, release_id=RELEASE, artifact_version=1)
    append_entity(
        truth,
        Artifact(
            artifact_id=SCRIPT_ARTIFACT,
            mission_id=MISSION,
            artifact_type="EXECUTABLE_SCRIPT",
            producer_task_id=script_task_id,
            content_ref="file://" + str(candidate_path.resolve()),
            parent_refs=[DESIGN_ARTIFACT],
            evidence_refs=[candidate_evidence.evidence_id],
            content_hash="sha256:" + hashlib.sha256(script_raw).hexdigest(),
        ),
        release_id=RELEASE,
        artifact_version=1,
    )
    source_evidence = Evidence(
        evidence_id="EVD-SCRIPT-SOURCE-BUNDLE",
        mission_id=MISSION,
        kind="RUNTIME_PERSISTED_SCRIPT_SOURCE",
        source_ref="dsh://script-worker",
        content_ref="file://" + str(source_path.resolve()),
        subject_refs=[script_task_id, SCRIPT_ARTIFACT, contract.spec.spec_id],
        content_hash="sha256:" + source_digest,
    )
    append_entity(truth, source_evidence, release_id=RELEASE, artifact_version=1)
    validation_evidence = Evidence(
        evidence_id="EVD-SCRIPT-VALIDATION-BUNDLE",
        mission_id=MISSION,
        kind="SCRIPT_READINESS_VALIDATION_PROOF",
        source_ref="runtime://script-validator",
        content_ref="validation://bundle",
        subject_refs=[script_task_id, SCRIPT_ARTIFACT, script_id],
    )
    append_entity(truth, validation_evidence, release_id=RELEASE, artifact_version=1)
    script = ScriptArtifact(
        script_id=script_id,
        spec_id=contract.spec.spec_id,
        tc_id=contract.spec.tc_id,
        case_version=contract.spec.case_version,
        layer=contract.spec.layer,
        runner_type=contract.spec.runner_type,
        source_ref="file://" + str(source_path.resolve()),
        test_symbol="test_bundle_case",
        case_fingerprint=contract.spec.case_fingerprint,
        oracle_fingerprint=contract.spec.oracle_fingerprint,
        reuse_refs=(),
        builder_evidence_refs=(candidate_evidence.evidence_id, source_evidence.evidence_id),
        revision=1,
    )
    step = ProcessStepResult(
        name="pytest_collect",
        command=("pytest", "--collect-only"),
        exit_code=0,
        stdout_ref="stdout://bundle",
        stderr_ref="stderr://bundle",
        duration_ms=1,
        passed=True,
    )
    validation = ScriptValidation(
        validation_id="VAL-BUNDLE",
        script_id=script_id,
        runner_type=script.runner_type,
        test_symbol=script.test_symbol,
        steps=(step,),
        evidence_refs=(validation_evidence.evidence_id,),
        status="SCRIPT_READY",
    )
    receipt_id = record_script_ready(
        truth,
        mission_id=MISSION,
        release_id=RELEASE,
        task_id=script_task_id,
        artifact_id=SCRIPT_ARTIFACT,
        contract=contract,
        script=script,
        validation=validation,
        evidence_root=str(tmp_path / "evidence"),
    )
    return truth, source_path, receipt_id, script_id, contract


def test_resolver_rebuilds_current_case_bundle_without_session_state(tmp_path, monkeypatch):
    truth, source_path, receipt_id, script_id, contract = _setup(tmp_path, monkeypatch)
    bundle = CaseScriptExecutionBundleResolver(
        evidence_root=str(tmp_path / "revalidation"),
        validation_timeout_seconds=30,
    ).resolve(
        truth,
        mission_id=MISSION,
        tc_id="TC-BUNDLE-1",
        cwd=str(tmp_path),
    )

    assert bundle.spec.spec_id == contract.spec.spec_id
    assert bundle.script.script_id == script_id
    assert bundle.script.source_ref == "file://" + str(source_path.resolve())
    assert bundle.validation.ready is True
    assert bundle.upstream_result_ref.endswith(receipt_id + ".json")
    assert Path(bundle.spec_ref.removeprefix("file://")).is_file()


def test_resolver_rejects_source_drift_even_when_ready_receipt_still_exists(tmp_path, monkeypatch):
    truth, source_path, _receipt_id, _script_id, _contract = _setup(tmp_path, monkeypatch)
    source_path.write_text("def test_bundle_case():\n    assert False\n", encoding="utf-8")

    with pytest.raises(CaseScriptBundleResolverError, match="CASE_SCRIPT_SOURCE_(CANDIDATE_DRIFT|HASH_MISMATCH)"):
        CaseScriptExecutionBundleResolver(
            evidence_root=str(tmp_path / "revalidation"),
            validation_timeout_seconds=30,
        ).resolve(
            truth,
            mission_id=MISSION,
            tc_id="TC-BUNDLE-1",
            cwd=str(tmp_path),
        )


def test_current_receipt_selection_ignores_superseded_design(tmp_path):
    current = tmp_path / "current.json"
    old = tmp_path / "old.json"
    current_payload = {
        "design_artifact_id": "ART-DESIGN",
        "design_content_hash": "sha256:current",
        "case_hash": "sha256:case",
        "tc_id": "TC-1",
    }
    old_payload = dict(current_payload, design_content_hash="sha256:old")
    rows = []
    for evidence_id, path, payload, created_at in (
        ("EVD-OLD", old, old_payload, 99),
        ("EVD-CURRENT", current, current_payload, 1),
    ):
        raw = json.dumps(payload, sort_keys=True).encode()
        path.write_bytes(raw)
        rows.append({
            "evidence_id": evidence_id,
            "mission_id": MISSION,
            "kind": "CASE_SCRIPT_READY",
            "content_ref": "file://" + str(path),
            "content_hash": "sha256:" + hashlib.sha256(raw).hexdigest(),
            "created_at": created_at,
        })

    class FakeTruth:
        def query(self, artifact_type, **filters):
            assert artifact_type == "rc7_evidence"
            return [row for row in rows if all(row.get(k) == v for k, v in filters.items())]

    row, payload = CaseScriptExecutionBundleResolver._current_receipt(
        FakeTruth(),
        mission_id=MISSION,
        tc_id="TC-1",
        design_artifact_id="ART-DESIGN",
        design_content_hash="sha256:current",
        case_hash="sha256:case",
    )
    assert row["evidence_id"] == "EVD-CURRENT"
    assert payload["design_content_hash"] == "sha256:current"
