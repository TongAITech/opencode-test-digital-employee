"""RC7 evidence-backed Script readiness validator.

Readiness proves that a generated script is structurally executable without
executing the product/business assertion. Every subprocess stdout/stderr is
persisted as a real file so repair/diagnosis can locate the first failing step.
For JUnit, RC7 deliberately does NOT invoke ``mvn test`` during readiness;
dependency resolution + test compilation + source symbol discovery are enough
for the SCRIPT_READY gate. Formal Execution owns the actual business result.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
from typing import Callable, Mapping, Optional, Sequence

from rc6_runtime.automation import AutomationContractError, ProcessStepResult, ScriptArtifact, ScriptValidation
from rc6_runtime.executable_spec import ExecutableSpecBuilder, ExecutableTestSpec, canonical_fingerprint


class RC7ScriptValidationError(AutomationContractError):
    pass


class EvidenceBackedScriptReadinessValidator:
    def __init__(
        self,
        *,
        evidence_root: str,
        timeout_seconds: int = 180,
        command_runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    ) -> None:
        self.evidence_root = Path(evidence_root).resolve()
        self.timeout_seconds = int(timeout_seconds)
        self.command_runner = command_runner
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    @staticmethod
    def _local_path(source_ref: str) -> str:
        if source_ref.startswith("file://"):
            return source_ref[len("file://"):]
        return source_ref

    def validate(
        self,
        *,
        spec: ExecutableTestSpec,
        script: ScriptArtifact,
        cwd: str,
        env: Optional[Mapping[str, str]] = None,
    ) -> ScriptValidation:
        ExecutableSpecBuilder.verify_script_or_repair_binding(
            spec,
            case_fingerprint=script.case_fingerprint,
            oracle_fingerprint=script.oracle_fingerprint,
        )
        if script.spec_id != spec.spec_id or script.tc_id != spec.tc_id:
            raise RC7ScriptValidationError("SCRIPT_SPEC_IDENTITY_MISMATCH")
        source_path = Path(self._local_path(script.source_ref))
        if not source_path.is_absolute():
            source_path = Path(cwd).resolve() / source_path
        if not source_path.is_file():
            raise RC7ScriptValidationError("SCRIPT_SOURCE_REF_NOT_FOUND")

        run_id = "VALRUN-" + uuid.uuid4().hex
        run_root = self.evidence_root / "script-validation" / script.script_id / run_id
        run_root.mkdir(parents=True, exist_ok=True)
        merged = os.environ.copy()
        if env:
            merged.update({str(key): str(value) for key, value in env.items()})

        runner = script.runner_type.upper()
        steps = []
        if runner == "PYTEST":
            steps.append(self._run("python_compile", (sys.executable, "-m", "py_compile", str(source_path)), cwd, merged, run_root))
            if steps[-1].passed:
                node = "%s::%s" % (str(source_path), script.test_symbol) if "::" not in script.test_symbol else script.test_symbol
                steps.append(self._run("pytest_collect", (sys.executable, "-m", "pytest", "--collect-only", "-q", node), cwd, merged, run_root))
            if steps[-1].passed:
                steps.append(self._run("fixture_dependency_resolution", (sys.executable, "-m", "pytest", "--setup-plan", "-q", node), cwd, merged, run_root))
        elif runner == "JUNIT":
            pom = Path(cwd).resolve() / "pom.xml"
            if not pom.is_file():
                raise RC7ScriptValidationError("JUNIT_POM_REQUIRED")
            steps.append(self._run("dependency_resolution", ("mvn", "-q", "-DskipTests", "dependency:go-offline"), cwd, merged, run_root))
            if steps[-1].passed:
                steps.append(self._run("test_compile", ("mvn", "-q", "-DskipTests", "test-compile"), cwd, merged, run_root))
            if steps[-1].passed:
                steps.append(self._junit_symbol_discovery(source_path, script.test_symbol, cwd, merged, run_root))
        else:
            raise RC7ScriptValidationError("DETERMINISTIC_READINESS_VALIDATOR_NOT_AVAILABLE:%s" % runner)

        if not steps:
            raise RC7ScriptValidationError("VALIDATION_STEPS_REQUIRED")
        ready = all(step.passed for step in steps)
        evidence_refs = []
        for step in steps:
            evidence_refs.extend([step.stdout_ref, step.stderr_ref])
        manifest = {
            "run_id": run_id,
            "script_id": script.script_id,
            "spec_id": spec.spec_id,
            "runner_type": runner,
            "business_assertion_executed": False,
            "steps": [
                {
                    "name": step.name,
                    "command": list(step.command),
                    "exit_code": step.exit_code,
                    "passed": step.passed,
                    "stdout_ref": step.stdout_ref,
                    "stderr_ref": step.stderr_ref,
                    "duration_ms": step.duration_ms,
                }
                for step in steps
            ],
        }
        manifest_path = run_root / "validation-manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        evidence_refs.append("file://" + str(manifest_path))
        identity = {"script_id": script.script_id, "steps": manifest["steps"]}
        return ScriptValidation(
            validation_id="VAL-" + canonical_fingerprint(identity)[:24],
            script_id=script.script_id,
            runner_type=runner,
            test_symbol=script.test_symbol,
            steps=tuple(steps),
            evidence_refs=tuple(dict.fromkeys(evidence_refs)),
            status="SCRIPT_READY" if ready else "SCRIPT_INVALID",
        )

    def _run(
        self,
        name: str,
        command: Sequence[str],
        cwd: str,
        env: Mapping[str, str],
        run_root: Path,
    ) -> ProcessStepResult:
        started = time.monotonic()
        stdout = ""
        stderr = ""
        code = 1
        try:
            completed = self.command_runner(
                list(command),
                cwd=cwd,
                env=dict(env),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            code = int(completed.returncode)
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            stderr += "\nPROCESS_TIMEOUT"
            code = 124
        except OSError as exc:
            stderr = "%s:%s" % (type(exc).__name__, exc)
            code = 127
        duration_ms = int((time.monotonic() - started) * 1000)
        safe = "".join(char if char.isalnum() or char in "-_" else "_" for char in name)
        stdout_path = run_root / (safe + ".stdout.log")
        stderr_path = run_root / (safe + ".stderr.log")
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")
        return ProcessStepResult(
            name=name,
            command=tuple(str(item) for item in command),
            exit_code=code,
            stdout_ref="file://" + str(stdout_path),
            stderr_ref="file://" + str(stderr_path),
            duration_ms=duration_ms,
            passed=(code == 0),
        )

    def _junit_symbol_discovery(
        self,
        source_path: Path,
        test_symbol: str,
        cwd: str,
        env: Mapping[str, str],
        run_root: Path,
    ) -> ProcessStepResult:
        symbol = test_symbol.split("#")[-1].split(".")[-1].strip()
        if not symbol:
            raise RC7ScriptValidationError("JUNIT_TEST_SYMBOL_REQUIRED")
        probe = (
            "from pathlib import Path; import sys; "
            "text=Path(sys.argv[1]).read_text(encoding='utf-8'); "
            "sys.exit(0 if sys.argv[2] in text else 3)"
        )
        return self._run(
            "test_symbol_discovery",
            (sys.executable, "-c", probe, str(source_path), symbol),
            cwd,
            env,
            run_root,
        )
