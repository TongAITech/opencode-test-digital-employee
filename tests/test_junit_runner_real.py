from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from rc6_runtime import (
    AIScriptBuilder,
    AuthorityRuntime,
    AutomationResolution,
    ExecutableSpecBuilder,
    ExecutionRuntime,
    JUnitRunnerAdapter,
    PreparedAttempt,
    ScriptValidator,
    ToolCapabilityBroker,
)


pytestmark = pytest.mark.skipif(
    os.environ.get("RC6_RUN_REAL_JUNIT") != "1",
    reason="real Maven/JUnit dependency qualification runs only in its capability-gated CI job",
)


def oracle(snapshot, actual, context):
    expected = bool(snapshot["value"])
    observed = bool(actual.get(snapshot["field"]))
    return {
        "passed": observed is expected,
        "assertion_ref": "assertion://%s/junit-runner" % context["attempt_id"],
        "evidence_refs": ["oracle-evidence://%s/junit" % context["attempt_id"]],
        "details": {"expected": expected, "actual": observed},
    }


def test_real_junit_compile_discovery_targeted_execution_and_runner(tmp_path):
    if shutil.which("mvn") is None or shutil.which("java") is None:
        pytest.fail("REAL_JUNIT_CAPABILITY_NOT_AVAILABLE:mvn/java")

    pom = tmp_path / "pom.xml"
    pom.write_text(
        """<project xmlns="http://maven.apache.org/POM/4.0.0"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
 xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
 <modelVersion>4.0.0</modelVersion>
 <groupId>rc6.qualification</groupId>
 <artifactId>execution-closure-junit</artifactId>
 <version>1.0-SNAPSHOT</version>
 <properties>
  <maven.compiler.source>8</maven.compiler.source>
  <maven.compiler.target>8</maven.compiler.target>
  <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
 </properties>
 <dependencies>
  <dependency>
   <groupId>org.junit.jupiter</groupId>
   <artifactId>junit-jupiter</artifactId>
   <version>5.10.2</version>
   <scope>test</scope>
  </dependency>
 </dependencies>
 <build>
  <plugins>
   <plugin>
    <groupId>org.apache.maven.plugins</groupId>
    <artifactId>maven-surefire-plugin</artifactId>
    <version>3.2.5</version>
   </plugin>
  </plugins>
 </build>
</project>
""",
        encoding="utf-8",
    )
    java_dir = tmp_path / "src" / "test" / "java"
    java_dir.mkdir(parents=True)
    source = java_dir / "Rc6JUnitRealTest.java"
    source.write_text(
        "import org.junit.jupiter.api.Test;\n"
        "import static org.junit.jupiter.api.Assertions.assertEquals;\n"
        "public class Rc6JUnitRealTest {\n"
        "  @Test public void shouldPass() { assertEquals(4, 2 + 2); }\n"
        "}\n",
        encoding="utf-8",
    )

    case = {
        "tc_id": "TC-L1-JUNIT-REAL", "case_version": 1, "release_id": "RC6-ENGINEERING",
        "requirement_id": "QUAL-JUNIT", "sst_id": None, "layer": "L1",
        "preconditions": [], "test_data": {}, "steps": ["execute JUnit test"],
        "expected": "targeted JUnit test process passes",
        "oracle": {"type": "field_equals", "field": "runner_passed", "value": True},
        "evidence_requirements": ["maven", "junit", "stdout", "oracle"], "status": "FROZEN",
    }
    spec = ExecutableSpecBuilder().build(
        case=case,
        target_requirements=("maven:READY", "junit:READY"),
        test_data_refs=(), oracle_refs=("oracle://junit-runner",), cleanup_policy={"mode": "NONE"},
        runner_type="JUNIT", automation_mapping={"reuse": {}},
    )
    resolution = AutomationResolution(spec.tc_id, (), (str(tmp_path),), ())
    script = AIScriptBuilder().build(
        spec=spec, resolution=resolution,
        generator=lambda s, mapping: {
            "source_ref": "file://" + str(source),
            "test_symbol": "Rc6JUnitRealTest#shouldPass",
            "case_fingerprint": s.case_fingerprint,
            "oracle_fingerprint": s.oracle_fingerprint,
            "evidence_refs": ["builder://junit-real"],
        },
    )
    validation = ScriptValidator(timeout_seconds=240).validate(
        spec=spec, script=script, cwd=str(tmp_path), execute_target=True,
    )
    assert validation.ready
    assert [step.name for step in validation.steps] == [
        "dependency_resolution", "compile", "test_discovery", "targeted_execution",
    ]
    assert all(step.exit_code == 0 for step in validation.steps)

    target_id = "TARGET-JUNIT-LOCAL"
    authority = AuthorityRuntime(b"0123456789abcdef0123456789abcdef")
    broker = ToolCapabilityBroker()
    worker = authority.issue_identity("L1_EXECUTE", "EXECUTION", "L1", 0, "dsh://l1-junit/1")
    lease = authority.issue_lease(
        worker.worker_id,
        "case:TC-L1-JUNIT-REAL@1",
        ["execution_attempt", "assertion", "evidence", "coverage_observation"],
        ["maven", "junit"],
    )
    for tool_id, location in (("maven", shutil.which("mvn")), ("junit", str(source))):
        broker.discover(tool_id, location)
        broker.mark_executable(tool_id, location)
        broker.register(tool_id, "process://%s" % tool_id)
        broker.bind_worker(tool_id, worker.worker_id, visible=True, permitted=True)
        broker.record_probe(tool_id, success=True, tool_call_ref="probe://%s" % tool_id, evidence_ref="evidence://%s/probe" % tool_id)
        broker.mark_target_ready(tool_id, target_id, "evidence://%s/target" % tool_id)

    prepared = PreparedAttempt(
        status="PREPARED", attempt_id="ATT-JUNIT-1", tc_id=spec.tc_id, case_version=1, target_id=target_id,
        precondition_evidence=("precondition://maven-junit-ready",), initial_state_bindings={},
        input_data_bindings={}, binding_evidence=("binding://junit",), cleanup_policy={"mode": "NONE"},
        oracle_snapshot={"type": "field_equals", "field": "runner_passed", "value": True},
    )
    record = ExecutionRuntime(authority=authority, tool_broker=broker, oracle_evaluator=oracle).execute_with_runner(
        case=case, executable_spec=spec, script=script, validation=validation, prepared=prepared,
        worker_id=worker.worker_id, lease_id=lease.lease_id, runner=JUnitRunnerAdapter(timeout_seconds=240),
        cwd=str(tmp_path),
    )
    assert record.status == "PASS"
    assert record.integrity_passed is True
    assert record.actual_result["runner_passed"] is True
    assert any(ref.startswith("maven-process://") for ref in record.tool_call_refs)
    assert any(ref.startswith("junit-process://") for ref in record.tool_call_refs)
