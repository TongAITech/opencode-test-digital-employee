from __future__ import annotations

import json
from pathlib import Path

from rc6_runtime.automation import ScriptArtifact
from rc6_runtime.executable_spec import ExecutableSpecBuilder
from rc7_release.execution_environment import LoadedExecutionEnvironment
from rc7_release import execution_qualification_strict as qualification
from rc7_runtime.execution_environment import (
    DiagnosisTrustProbeResult,
    ExecutionEnvironmentAdapter,
    ToolProbeResult,
)
from rc7_runtime.runtime_execution import VerifiedScriptExecutionBundle
from rc7_runtime.script_validation import EvidenceBackedScriptReadinessValidator


class QualificationAdapter(ExecutionEnvironmentAdapter):
    @property
    def adapter_id(self):
        return "qualification-real-local-adapter"

    def probe_tool(self, *, tool_id, target_id, layer):
        return ToolProbeResult(
            tool_id=tool_id,
            success=True,
            locator_ref="fixture-locator://%s" % tool_id,
            executable_ref="fixture-executable://%s" % tool_id,
            registration_ref="fixture-registration://%s" % tool_id,
            tool_call_ref="fixture-probe-call://%s" % tool_id,
            evidence_ref="fixture-probe-evidence://%s" % tool_id,
            target_readiness_ref="fixture-ready://%s/%s" % (tool_id, target_id),
        )

    def diagnosis_trust(self, *, target_id, layer):
        return DiagnosisTrustProbeResult(
            auth_verified=True,
            auth_evidence_ref="fixture-trust://auth",
            route_verified=True,
            route_evidence_ref="fixture-trust://route",
            environment_verified=True,
            environment_evidence_ref="fixture-trust://environment",
            dependency_verified=True,
            dependency_evidence_ref="fixture-trust://dependency",
        )

    def resolve_precondition(self, spec, context):
        return {"success": True, "evidence_ref": "fixture-precondition://%s" % spec["id"]}

    def prepare_data(self, requirement, context, *, strategy):
        return {
            "success": True,
            "binding": {"strategy": strategy},
            "tool_call_ref": "fixture-data-call://%s" % strategy,
            "evidence_ref": "fixture-data-evidence://%s" % strategy,
        }

    def verify_data(self, requirement, binding, context):
        return {"success": True, "evidence_ref": "fixture-data-verify://%s" % requirement["id"]}


def _case():
    return {
        "tc_id": "TC-EXEC-QUAL-1",
        "case_version": 1,
        "status": "FROZEN",
        "release_id": "RC7-EXEC-QUAL",
        "requirement_id": "REQ-EXEC-QUAL",
        "sst_id": "SST-EXEC-QUAL",
        "layer": "L2",
        "preconditions": [],
        "test_data": {"initial_state": [], "input_data": [], "cleanup_policy": {"mode": "NONE"}},
        "steps": [{"order": 1, "action": "execute database-backed business rule"}],
        "expected": "business_code=OK",
        "oracle": {
            "checks": [
                {
                    "id": "CHK-BUSINESS",
                    "type": "BUSINESS_RULE",
                    "actual_path": "business_code",
                    "operator": "EQ",
                    "expected": "OK",
                }
            ]
        },
        "evidence_requirements": ["database-call", "oracle"],
        "target_requirements": ["REQ-EXEC-QUAL"],
        "test_data_refs": [],
        "oracle_refs": ["oracle://exec-qual"],
        "cleanup_policy": {"mode": "NONE"},
        "runner_type": "PYTEST",
    }


def _bundle(tmp_path: Path, business_code: str):
    case = _case()
    spec = ExecutableSpecBuilder().build(
        case=case,
        target_requirements=("REQ-EXEC-QUAL",),
        test_data_refs=(),
        oracle_refs=("oracle://exec-qual",),
        cleanup_policy={"mode": "NONE"},
        runner_type="PYTEST",
        automation_mapping={"reuse": {}},
    )
    source_path = tmp_path / ("test_exec_qual_%s.py" % business_code.lower())
    source_path.write_text(
        '''import json\nimport os\n\ndef _emit(row):\n    with open(os.environ["RC6_EXECUTION_MANIFEST"], "a", encoding="utf-8") as handle:\n        handle.write(json.dumps(row, sort_keys=True) + "\\n")\n\ndef test_execution_qualification_fixture():\n    _emit({"type":"tool_call","tool_id":"database","call_ref":"database-call://exec-qual","evidence_ref":"database-evidence://exec-qual"})\n    _emit({"type":"actual_result","value":{"business_code":"%s","source":"real-pytest-process"}})\n    assert True\n''' % business_code,
        encoding="utf-8",
    )
    script = ScriptArtifact(
        script_id="SCRIPT-EXEC-QUAL-%s" % business_code,
        spec_id=spec.spec_id,
        tc_id=spec.tc_id,
        case_version=spec.case_version,
        layer=spec.layer,
        runner_type=spec.runner_type,
        source_ref="file://" + str(source_path),
        test_symbol="test_execution_qualification_fixture",
        case_fingerprint=spec.case_fingerprint,
        oracle_fingerprint=spec.oracle_fingerprint,
        reuse_refs=(),
        builder_evidence_refs=("fixture://script-builder",),
        revision=1,
    )
    validation = EvidenceBackedScriptReadinessValidator(
        evidence_root=str(tmp_path / ("readiness-" + business_code.lower())),
        timeout_seconds=20,
    ).validate(spec=spec, script=script, cwd=str(tmp_path))
    assert validation.ready
    return VerifiedScriptExecutionBundle(
        upstream_mission_id="MISSION-UPSTREAM-SCRIPT",
        upstream_task_id="TASK-UPSTREAM-SCRIPT",
        upstream_evaluation_id="EVAL-UPSTREAM-SCRIPT",
        upstream_result_ref="file://upstream-script-result.json",
        spec_ref="file://upstream-spec.json",
        frozen_case=case,
        spec=spec,
        script=script,
        validation=validation,
        source_sha256="fixture-source-sha",
    )


def _run(tmp_path: Path, monkeypatch, business_code: str):
    bundle = _bundle(tmp_path, business_code)
    script_result = tmp_path / "rc7-dsh-script-result.json"
    script_result.write_text(json.dumps({"status": "PASS", "fixture": True}), encoding="utf-8")
    adapter = QualificationAdapter()

    monkeypatch.setattr(
        qualification.StrictScriptExecutionBundleLoader,
        "load",
        lambda self, path, cwd, env=None: bundle,
    )
    monkeypatch.setattr(
        qualification.ExecutionEnvironmentLoader,
        "load",
        lambda module_name: LoadedExecutionEnvironment(
            module_name=module_name,
            factory_name="create_execution_environment",
            adapter=adapter,
        ),
    )
    state_root = tmp_path / ("state-" + business_code.lower())
    result = qualification.run_execution_qualification(
        state_root=str(state_root),
        workspace=str(tmp_path),
        script_result=str(script_result),
        environment_module="fixture_execution_environment",
        target_id="TARGET-EXEC-QUAL",
        attempt_id="ATT-EXEC-QUAL-" + business_code,
        execution_cwd=str(tmp_path),
        timeout_seconds=20,
    )
    return state_root, result


def test_strict_execution_qualification_reports_trustworthy_business_pass(tmp_path: Path, monkeypatch):
    state_root, result = _run(tmp_path, monkeypatch, "OK")
    assert result.status == "PASS"
    assert result.test_result == "PASS"
    assert result.execution_conclusion == "TRUSTWORTHY_PASS"
    assert result.final_task_state == "PASS"
    assert result.converged is True
    assert len(result.attempt_summaries) == 1
    assert result.attempt_summaries[0]["status"] == "PASS"
    assert result.environment_admission_artifact_id
    assert result.preparation_artifact_id
    assert result.product_defect_gap_ids == ()
    assert result.defect_task_ids == ()
    saved = json.loads((state_root / "qualification" / "rc7-execution-result.json").read_text(encoding="utf-8"))
    assert saved["execution_conclusion"] == "TRUSTWORTHY_PASS"
    assert saved["r1_event_count"] > 0


def test_strict_execution_qualification_keeps_product_fail_red_and_hands_to_defect(tmp_path: Path, monkeypatch):
    _, result = _run(tmp_path, monkeypatch, "BAD")
    assert result.status == "PASS"  # control conclusion is trustworthy
    assert result.test_result == "FAIL"  # product test remains red
    assert result.execution_conclusion == "TRUSTWORTHY_PRODUCT_FAIL"
    assert result.final_task_state == "PASS"
    assert result.converged is True
    assert result.attempt_summaries[0]["failure_class"] == "PRODUCT"
    assert result.attempt_summaries[0]["recovery_action"] == "PRODUCT_DEFECT"
    assert result.gap_categories.count("PRODUCT_DEFECT") == 1
    assert len(result.product_defect_gap_ids) == 1
    assert len(result.defect_task_ids) == 1
