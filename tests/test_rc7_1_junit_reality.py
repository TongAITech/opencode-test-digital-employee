import tempfile
import unittest
from pathlib import Path

from rc6_runtime.automation import (
    AutomationContractError,
    ProcessStepResult,
    ScriptArtifact,
    ScriptValidation,
)
from rc6_runtime.executable_spec import ExecutableTestSpec
from rc7_runtime.junit_reality import RealityCheckedJUnitRunnerAdapter


class _FakeHarness:
    def __init__(self, callback):
        self.callback = callback

    def run(self, name, command, cwd, env=None):
        return self.callback(name, command, cwd, env or {})


class JUnitRealityGateTests(unittest.TestCase):
    def _objects(self, root):
        source = Path(root) / "SampleTest.java"
        source.write_text("class SampleTest {}", encoding="utf-8")
        spec = ExecutableTestSpec(
            spec_id="SPEC-1",
            tc_id="TC-1",
            case_version=1,
            case_fingerprint="case-fp",
            oracle_fingerprint="oracle-fp",
            release_id="R-1",
            requirement_id="REQ-1",
            sst_id="SST-1",
            layer="L1",
            target_requirements=("REQ-1",),
            preconditions=(),
            test_data_refs=(),
            ordered_actions=({"order": 1, "description": "run"},),
            oracle_refs=("oracle://1",),
            evidence_requirements=("junit_xml",),
            cleanup_policy={"mode": "NONE"},
            runner_type="JUNIT",
            automation_mapping={},
        )
        script = ScriptArtifact(
            script_id="SCRIPT-1",
            spec_id=spec.spec_id,
            tc_id=spec.tc_id,
            case_version=spec.case_version,
            layer=spec.layer,
            runner_type="JUNIT",
            source_ref="file://" + str(source),
            test_symbol="SampleTest#works",
            case_fingerprint=spec.case_fingerprint,
            oracle_fingerprint=spec.oracle_fingerprint,
            reuse_refs=(),
            builder_evidence_refs=("evidence://builder",),
            revision=1,
        )
        validation_step = ProcessStepResult(
            name="validation",
            command=("mvn", "test"),
            exit_code=0,
            stdout_ref="stdout://validation",
            stderr_ref="stderr://validation",
            duration_ms=1,
            passed=True,
        )
        validation = ScriptValidation(
            validation_id="VAL-1",
            script_id=script.script_id,
            runner_type="JUNIT",
            test_symbol=script.test_symbol,
            steps=(validation_step,),
            evidence_refs=("evidence://validation",),
            status="SCRIPT_READY",
        )
        return spec, script, validation

    @staticmethod
    def _result(root, exit_code=0, stdout="", stderr=""):
        stdout_path = Path(root) / "stdout.log"
        stderr_path = Path(root) / "stderr.log"
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")
        return ProcessStepResult(
            name="real_runner_execution",
            command=("mvn", "test"),
            exit_code=exit_code,
            stdout_ref="file://" + str(stdout_path),
            stderr_ref="file://" + str(stderr_path),
            duration_ms=9,
            passed=(exit_code == 0),
        )

    @staticmethod
    def _report(root, *, tests=1, failures=0, errors=0, skipped=0):
        folder = Path(root) / "target" / "surefire-reports"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "TEST-SampleTest.xml"
        path.write_text(
            '<testsuite name="SampleTest" tests="%d" failures="%d" errors="%d" skipped="%d" time="0.12"></testsuite>'
            % (tests, failures, errors, skipped),
            encoding="utf-8",
        )
        return path

    def test_stale_xml_cannot_turn_exit_zero_into_pass(self):
        with tempfile.TemporaryDirectory() as root:
            spec, script, validation = self._objects(root)
            self._report(root, tests=1)
            adapter = RealityCheckedJUnitRunnerAdapter(evidence_root=str(Path(root) / "evidence"))
            adapter.harness = _FakeHarness(lambda *_args, **_kwargs: self._result(root, 0, "BUILD SUCCESS", ""))
            with self.assertRaises(AutomationContractError) as ctx:
                adapter.execute(spec=spec, script=script, validation=validation, cwd=root)
            self.assertEqual(str(ctx.exception), "JUNIT_CURRENT_RUN_XML_REQUIRED")

    def test_fresh_current_run_xml_is_parsed_and_persisted(self):
        with tempfile.TemporaryDirectory() as root:
            spec, script, validation = self._objects(root)

            def run(_name, _command, _cwd, _env):
                self._report(root, tests=2, failures=0, errors=0, skipped=1)
                return self._result(root, 0, "BUILD SUCCESS", "")

            adapter = RealityCheckedJUnitRunnerAdapter(evidence_root=str(Path(root) / "evidence"))
            adapter.harness = _FakeHarness(run)
            result = adapter.execute(spec=spec, script=script, validation=validation, cwd=root)
            self.assertTrue(result.actual_result["junit_current_run"])
            self.assertEqual(result.actual_result["classification"], "TEST_PASS")
            self.assertEqual(result.actual_result["tests"], 2)
            self.assertEqual(result.actual_result["skipped"], 1)
            report_refs = result.actual_result["junit_report_refs"]
            self.assertEqual(len(report_refs), 1)
            self.assertTrue(Path(report_refs[0][len("file://"):]).is_file())
            self.assertTrue(Path(result.actual_result["junit_trace_ref"][len("file://"):]).is_file())

    def test_current_run_failure_remains_test_fail(self):
        with tempfile.TemporaryDirectory() as root:
            spec, script, validation = self._objects(root)

            def run(_name, _command, _cwd, _env):
                self._report(root, tests=1, failures=1)
                return self._result(root, 1, "Tests run: 1, Failures: 1", "")

            adapter = RealityCheckedJUnitRunnerAdapter(evidence_root=str(Path(root) / "evidence"))
            adapter.harness = _FakeHarness(run)
            result = adapter.execute(spec=spec, script=script, validation=validation, cwd=root)
            self.assertEqual(result.actual_result["classification"], "TEST_FAIL")
            self.assertEqual(result.actual_result["failures"], 1)
            self.assertNotEqual(result.exit_code, 0)

    def test_missing_maven_dependency_is_blocked_not_pass(self):
        with tempfile.TemporaryDirectory() as root:
            spec, script, validation = self._objects(root)
            adapter = RealityCheckedJUnitRunnerAdapter(evidence_root=str(Path(root) / "evidence"))
            adapter.harness = _FakeHarness(
                lambda *_args, **_kwargs: self._result(
                    root,
                    1,
                    "",
                    "Could not resolve dependencies for project bank:test:jar:1.0",
                )
            )
            result = adapter.execute(spec=spec, script=script, validation=validation, cwd=root)
            self.assertEqual(result.actual_result["classification"], "BLOCKED_ENVIRONMENT")
            self.assertEqual(result.actual_result["blocked_reason"], "MAVEN_DEPENDENCY_UNAVAILABLE")
            self.assertFalse(result.actual_result["junit_current_run"])
            self.assertNotEqual(result.exit_code, 0)

    def test_rc7_package_bootstrap_installs_strict_adapter(self):
        from rc6_runtime import automation

        self.assertIs(automation.JUnitRunnerAdapter, RealityCheckedJUnitRunnerAdapter)


if __name__ == "__main__":
    unittest.main()
