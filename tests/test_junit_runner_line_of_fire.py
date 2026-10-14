from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from rc6_runtime.authority import AuthorityRuntime
from rc6_runtime.automation import AIScriptBuilder, AutomationReuseResolver, JUnitRunnerAdapter, ScriptValidator
from rc6_runtime.capability import ToolCapabilityBroker
from rc6_runtime.executable_spec import ExecutableSpecBuilder
from rc6_runtime.execution import ExecutionRuntime
from rc6_runtime.preparation import PreparedAttempt


TARGET = "TARGET-RC6-L1-JUNIT-LINE-OF-FIRE"


def _case():
    return {
        "tc_id": "TC-L1-JUNIT-001",
        "case_version": 1,
        "release_id": "BLOAN-PF1.2.0",
        "requirement_id": "STBB19-320",
        "sst_id": "STB915-7489",
        "condition_id": "COND-L1-JUNIT",
        "objective": "prove real JUnit process execution through RC6 runner adapter",
        "layer": "L1",
        "preconditions": [{"id": "java", "state": "READY"}, {"id": "maven", "state": "READY"}],
        "test_data": {},
        "steps": ["compile test source", "discover target JUnit test", "execute target JUnit test"],
        "expected": "target JUnit process passes",
        "oracle": {"type": "field_equals", "field": "runner_passed", "value": True},
        "evidence_requirements": ["maven stdout", "maven stderr", "junit process call"],
        "status": "FROZEN",
    }


def _oracle(snapshot, actual, context):
    expected = snapshot.get("value")
    observed = actual.get(snapshot.get("field"))
    return {
        "passed": observed == expected,
        "assertion_ref": "assertion://%s" % context["attempt_id"],
        "evidence_refs": ["oracle-evidence://%s" % context["attempt_id"]],
        "details": {"expected": expected, "actual": observed},
    }


def _ready(broker, tool_id, worker_id):
    broker.discover(tool_id, "path://%s" % tool_id)
    broker.mark_executable(tool_id, "exec://%s" % tool_id)
    broker.register(tool_id, "runtime://%s" % tool_id)
    broker.bind_worker(tool_id, worker_id, visible=True, permitted=True)
    broker.record_probe(tool_id, success=True, tool_call_ref="probe://%s" % tool_id, evidence_ref="probe-evidence://%s" % tool_id)
    broker.mark_target_ready(tool_id, TARGET, "target-evidence://%s" % tool_id)


def test_real_junit_compile_discovery_targeted_execution_and_l1_integrity():
    assert shutil.which("mvn"), "Maven capability is required for JUnit line-of-fire qualification"
    assert shutil.which("java"), "Java capability is required for JUnit line-of-fire qualification"
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        source = root / "src" / "test" / "java" / "com" / "bank" / "Rc6JUnitLineOfFireTest.java"
        source.parent.mkdir(parents=True)
        source.write_text(
            "package com.bank;\n"
            "import org.junit.Test;\n"
            "import static org.junit.Assert.assertEquals;\n"
            "public class Rc6JUnitLineOfFireTest {\n"
            "  @Test public void shouldExecuteRealJUnitProcess() {\n"
            "    assertEquals(4, 2 + 2);\n"
            "  }\n"
            "}\n",
            encoding="utf-8",
        )
        (root / "pom.xml").write_text(
            "<project xmlns=\"http://maven.apache.org/POM/4.0.0\" xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\" xsi:schemaLocation=\"http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd\">\n"
            "  <modelVersion>4.0.0</modelVersion>\n"
            "  <groupId>rc6.qualification</groupId>\n"
            "  <artifactId>junit-line-of-fire</artifactId>\n"
            "  <version>1.0-SNAPSHOT</version>\n"
            "  <properties><maven.compiler.source>8</maven.compiler.source><maven.compiler.target>8</maven.compiler.target></properties>\n"
            "  <dependencies><dependency><groupId>junit</groupId><artifactId>junit</artifactId><version>4.13.2</version><scope>test</scope></dependency></dependencies>\n"
            "</project>\n",
            encoding="utf-8",
        )

        case = _case()
        spec = ExecutableSpecBuilder().build(
            case=case,
            target_requirements=("TARGET-QUALIFIED", "maven:READY", "junit:READY"),
            test_data_refs=(),
            oracle_refs=("oracle://TC-L1-JUNIT-001@1",),
            cleanup_policy={"mode": "NONE"},
            runner_type="JUNIT",
            automation_mapping={"reuse_refs": []},
        )
        resolution = AutomationReuseResolver().resolve(spec=spec, search_roots=(str(root),))
        script = AIScriptBuilder().build(
            spec=spec,
            resolution=resolution,
            generator=lambda value, mapping: {
                "source_ref": "file://" + str(source),
                "test_symbol": "com.bank.Rc6JUnitLineOfFireTest#shouldExecuteRealJUnitProcess",
                "case_fingerprint": value.case_fingerprint,
                "oracle_fingerprint": value.oracle_fingerprint,
                "evidence_refs": ["builder-evidence://real-junit"],
            },
        )
        validation = ScriptValidator(timeout_seconds=180).validate(
            spec=spec,
            script=script,
            cwd=str(root),
            execute_target=True,
        )
        assert validation.ready
        assert [step.name for step in validation.steps] == [
            "dependency_resolution", "compile", "test_discovery", "targeted_execution"
        ]
        assert all(step.exit_code == 0 for step in validation.steps)

        authority = AuthorityRuntime(b"0123456789abcdef0123456789abcdef")
        broker = ToolCapabilityBroker()
        worker = authority.issue_identity("L1_EXECUTE", "EXECUTION", "L1", 0, "session-l1-junit")
        lease = authority.issue_lease(
            worker.worker_id,
            "case:TC-L1-JUNIT-001@1",
            ["execution_attempt", "assertion", "evidence"],
            ["maven", "junit"],
        )
        _ready(broker, "maven", worker.worker_id)
        _ready(broker, "junit", worker.worker_id)
        prepared = PreparedAttempt(
            status="PREPARED",
            attempt_id="ATT-L1-JUNIT-1",
            tc_id="TC-L1-JUNIT-001",
            case_version=1,
            target_id=TARGET,
            precondition_evidence=("evidence://java-ready", "evidence://maven-ready"),
            initial_state_bindings={},
            input_data_bindings={},
            binding_evidence=("evidence://junit-prepared",),
            cleanup_policy={"mode": "NONE"},
            oracle_snapshot={"field": "runner_passed", "value": True},
        )
        record = ExecutionRuntime(authority=authority, tool_broker=broker, oracle_evaluator=_oracle).execute_with_runner(
            case=case,
            executable_spec=spec,
            script=script,
            validation=validation,
            prepared=prepared,
            worker_id=worker.worker_id,
            lease_id=lease.lease_id,
            runner=JUnitRunnerAdapter(timeout_seconds=180),
            cwd=str(root),
        )
        assert record.status == "PASS"
        assert record.integrity_passed
        assert record.actual_result["runner_passed"] is True
        assert any(ref.startswith("maven-process://") for ref in record.tool_call_refs)
        assert any(ref.startswith("junit-process://") for ref in record.tool_call_refs)
        assert record.assertion_passed is True
