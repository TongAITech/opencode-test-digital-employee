"""RC6 Execution Closure Overlay: automation reuse, script build and real runners.

The runtime never treats generated source as ready merely because a model wrote
it.  Existing automation assets are resolved first, generated/repaired scripts
remain bound to the frozen Case/Oracle fingerprints, deterministic validation
must pass, and production runners invoke real local processes/tools.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import py_compile
import subprocess
import sys
import time
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .executable_spec import ExecutableSpecBuilder, ExecutableSpecError, ExecutableTestSpec, canonical_fingerprint


class AutomationContractError(RuntimeError):
    pass


REUSE_CATEGORIES = (
    "test",
    "fixture",
    "api_client",
    "db_helper",
    "page_object",
    "auth_skill",
    "route_binding",
    "data_builder",
    "assertion_helper",
    "cleanup_helper",
)


@dataclass(frozen=True)
class AutomationAsset:
    category: str
    ref: str
    score: int
    evidence_ref: str


@dataclass(frozen=True)
class AutomationResolution:
    tc_id: str
    assets: Tuple[AutomationAsset, ...]
    searched_roots: Tuple[str, ...]
    evidence_refs: Tuple[str, ...]

    def mapping(self) -> Dict[str, Any]:
        grouped: Dict[str, List[str]] = {name: [] for name in REUSE_CATEGORIES}
        for asset in self.assets:
            grouped.setdefault(asset.category, []).append(asset.ref)
        return {
            "resolver": "AUTOMATION_REUSE_RESOLVER",
            "reuse": grouped,
            "evidence_refs": list(self.evidence_refs),
        }


class AutomationReuseResolver:
    """Deterministic repository/local-asset search before new script generation."""

    CATEGORY_HINTS: Dict[str, Tuple[str, ...]] = {
        "test": ("test", "case", "spec"),
        "fixture": ("fixture", "conftest", "setup", "before"),
        "api_client": ("client", "api", "http", "request"),
        "db_helper": ("db", "sql", "tdsql", "oceanbase", "tidb", "database"),
        "page_object": ("page", "locator", "playwright", "browser"),
        "auth_skill": ("auth", "4a", "foura", "login", "sso"),
        "route_binding": ("route", "endpoint", "gateway", "binding"),
        "data_builder": ("data", "builder", "factory", "seed"),
        "assertion_helper": ("assert", "oracle", "verify", "check"),
        "cleanup_helper": ("cleanup", "teardown", "rollback", "delete"),
    }

    def __init__(self, max_files: int = 5000):
        self.max_files = int(max_files)
        if self.max_files <= 0:
            raise ValueError("max_files must be positive")

    def resolve(
        self,
        *,
        spec: ExecutableTestSpec,
        search_roots: Sequence[str],
        extra_keywords: Sequence[str] = (),
    ) -> AutomationResolution:
        roots = tuple(str(Path(root).resolve()) for root in search_roots)
        keywords = {
            spec.tc_id.lower(),
            spec.requirement_id.lower(),
            spec.layer.lower(),
        }
        if spec.sst_id:
            keywords.add(spec.sst_id.lower())
        keywords.update(str(x).lower() for x in extra_keywords if str(x).strip())
        candidates: List[AutomationAsset] = []
        scanned = 0
        for root_text in roots:
            root = Path(root_text)
            if not root.exists():
                continue
            for path in sorted(root.rglob("*")):
                if scanned >= self.max_files:
                    break
                if not path.is_file():
                    continue
                scanned += 1
                rel = str(path)
                lowered = rel.lower()
                for category, hints in self.CATEGORY_HINTS.items():
                    hint_hits = sum(1 for hint in hints if hint in lowered)
                    key_hits = sum(1 for key in keywords if key and key in lowered)
                    if hint_hits == 0:
                        continue
                    score = hint_hits * 10 + key_hits * 25
                    ref = "file://" + rel
                    evidence = "reuse-scan://" + sha256((category + "|" + rel).encode("utf-8")).hexdigest()[:24]
                    candidates.append(AutomationAsset(category, ref, score, evidence))
        # Stable ordering and bounded results avoid context blow-up.
        ordered = sorted(candidates, key=lambda item: (-item.score, item.category, item.ref))
        selected: List[AutomationAsset] = []
        per_category: Dict[str, int] = {}
        for item in ordered:
            if per_category.get(item.category, 0) >= 8:
                continue
            selected.append(item)
            per_category[item.category] = per_category.get(item.category, 0) + 1
        refs = tuple(dict.fromkeys(item.evidence_ref for item in selected))
        return AutomationResolution(spec.tc_id, tuple(selected), roots, refs)


@dataclass(frozen=True)
class ScriptArtifact:
    script_id: str
    spec_id: str
    tc_id: str
    case_version: int
    layer: str
    runner_type: str
    source_ref: str
    test_symbol: str
    case_fingerprint: str
    oracle_fingerprint: str
    reuse_refs: Tuple[str, ...]
    builder_evidence_refs: Tuple[str, ...]
    revision: int
    status: str = "SCRIPT_GENERATED"

    def to_artifact(self) -> Dict[str, Any]:
        return asdict(self)


class AIScriptBuilder:
    """Governed AUTOMATION_ENGINEER output wrapper.

    `generator` may be an AI Worker adapter, but the runtime owns identity,
    fingerprints and output validation.  The generator cannot rewrite the
    frozen oracle through its returned metadata.
    """

    def build(
        self,
        *,
        spec: ExecutableTestSpec,
        resolution: AutomationResolution,
        generator: Callable[[ExecutableTestSpec, Dict[str, Any]], Dict[str, Any]],
        revision: int = 1,
    ) -> ScriptArtifact:
        raw = generator(spec, resolution.mapping())
        if not isinstance(raw, dict):
            raise AutomationContractError("SCRIPT_BUILDER_RESULT_REQUIRED")
        source_ref = raw.get("source_ref")
        test_symbol = raw.get("test_symbol")
        evidence_refs = raw.get("evidence_refs")
        if not isinstance(source_ref, str) or not source_ref.strip():
            raise AutomationContractError("SCRIPT_SOURCE_REF_REQUIRED")
        if not isinstance(test_symbol, str) or not test_symbol.strip():
            raise AutomationContractError("SCRIPT_TEST_SYMBOL_REQUIRED")
        if not isinstance(evidence_refs, list) or not evidence_refs or not all(isinstance(x, str) and x for x in evidence_refs):
            raise AutomationContractError("SCRIPT_BUILDER_EVIDENCE_REQUIRED")
        returned_case_fp = raw.get("case_fingerprint", spec.case_fingerprint)
        returned_oracle_fp = raw.get("oracle_fingerprint", spec.oracle_fingerprint)
        try:
            ExecutableSpecBuilder.verify_script_or_repair_binding(
                spec,
                case_fingerprint=returned_case_fp,
                oracle_fingerprint=returned_oracle_fp,
            )
        except ExecutableSpecError as exc:
            raise AutomationContractError(str(exc))
        reuse_refs = tuple(asset.ref for asset in resolution.assets)
        identity = {
            "spec_id": spec.spec_id,
            "source_ref": source_ref,
            "test_symbol": test_symbol,
            "revision": revision,
        }
        return ScriptArtifact(
            script_id="SCRIPT-" + canonical_fingerprint(identity)[:24],
            spec_id=spec.spec_id,
            tc_id=spec.tc_id,
            case_version=spec.case_version,
            layer=spec.layer,
            runner_type=spec.runner_type,
            source_ref=source_ref,
            test_symbol=test_symbol,
            case_fingerprint=spec.case_fingerprint,
            oracle_fingerprint=spec.oracle_fingerprint,
            reuse_refs=reuse_refs,
            builder_evidence_refs=tuple(evidence_refs),
            revision=int(revision),
        )


@dataclass(frozen=True)
class ProcessStepResult:
    name: str
    command: Tuple[str, ...]
    exit_code: int
    stdout_ref: str
    stderr_ref: str
    duration_ms: int
    passed: bool


@dataclass(frozen=True)
class ScriptValidation:
    validation_id: str
    script_id: str
    runner_type: str
    test_symbol: str
    steps: Tuple[ProcessStepResult, ...]
    evidence_refs: Tuple[str, ...]
    status: str

    @property
    def ready(self) -> bool:
        return self.status == "SCRIPT_READY" and bool(self.steps) and all(step.passed for step in self.steps)

    def to_artifact(self) -> Dict[str, Any]:
        out = asdict(self)
        out["steps"] = [asdict(step) for step in self.steps]
        return out


class _ProcessHarness:
    def __init__(self, timeout_seconds: int = 180):
        self.timeout_seconds = int(timeout_seconds)

    @staticmethod
    def _ref(kind: str, payload: str) -> str:
        return "%s://%s" % (kind, sha256(payload.encode("utf-8", errors="replace")).hexdigest())

    def run(self, name: str, command: Sequence[str], cwd: str, env: Optional[Mapping[str, str]] = None) -> ProcessStepResult:
        started = time.monotonic()
        merged = os.environ.copy()
        if env:
            merged.update({str(k): str(v) for k, v in env.items()})
        try:
            completed = subprocess.run(
                list(command),
                cwd=cwd,
                env=merged,
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
            stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
            stderr += "\nPROCESS_TIMEOUT"
            code = 124
        duration = int((time.monotonic() - started) * 1000)
        return ProcessStepResult(
            name=name,
            command=tuple(str(x) for x in command),
            exit_code=code,
            stdout_ref=self._ref("stdout", stdout),
            stderr_ref=self._ref("stderr", stderr),
            duration_ms=duration,
            passed=code == 0,
        )


class ScriptValidator:
    """Deterministic readiness gate. SCRIPT_GENERATED is never SCRIPT_READY."""

    def __init__(self, timeout_seconds: int = 180):
        self.harness = _ProcessHarness(timeout_seconds)

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
        execute_target: bool = True,
    ) -> ScriptValidation:
        ExecutableSpecBuilder.verify_script_or_repair_binding(
            spec,
            case_fingerprint=script.case_fingerprint,
            oracle_fingerprint=script.oracle_fingerprint,
        )
        if script.spec_id != spec.spec_id or script.tc_id != spec.tc_id:
            raise AutomationContractError("SCRIPT_SPEC_IDENTITY_MISMATCH")
        runner = script.runner_type.upper()
        steps: List[ProcessStepResult] = []
        if runner == "PYTEST":
            path = self._local_path(script.source_ref)
            # py_compile gives a deterministic syntax/importable-source preflight.
            steps.append(self.harness.run("python_compile", (sys.executable, "-m", "py_compile", path), cwd, env))
            if steps[-1].passed:
                node = "%s::%s" % (path, script.test_symbol) if "::" not in script.test_symbol else script.test_symbol
                steps.append(self.harness.run("pytest_collect", (sys.executable, "-m", "pytest", "--collect-only", "-q", node), cwd, env))
                # pytest collection performs fixture/dependency resolution for the target symbol.
                if steps[-1].passed:
                    steps.append(self.harness.run("fixture_dependency_resolution", (sys.executable, "-m", "pytest", "--setup-plan", "-q", node), cwd, env))
                if execute_target and steps[-1].passed:
                    steps.append(self.harness.run("targeted_execution", (sys.executable, "-m", "pytest", "-q", node), cwd, env))
        elif runner == "JUNIT":
            symbol = script.test_symbol
            source_path = self._local_path(script.source_ref)
            if not Path(cwd, "pom.xml").is_file():
                raise AutomationContractError("JUNIT_POM_REQUIRED")
            # Maven is resolved by capability/path, never by exact version pin.
            steps.append(self.harness.run("dependency_resolution", ("mvn", "-q", "-DskipTests", "dependency:go-offline"), cwd, env))
            if steps[-1].passed:
                steps.append(self.harness.run("compile", ("mvn", "-q", "-DskipTests", "test-compile"), cwd, env))
            if steps[-1].passed:
                # Existence of compiled source plus Surefire selector is deterministic discovery evidence.
                selector = "-Dtest=%s" % symbol
                steps.append(self.harness.run("test_discovery", ("mvn", "-q", selector, "-DfailIfNoTests=true", "-DskipTests=false", "test"), cwd, env))
            if execute_target and steps[-1].passed:
                selector = "-Dtest=%s" % symbol
                steps.append(self.harness.run("targeted_execution", ("mvn", "-q", selector, "-DfailIfNoTests=true", "-DskipTests=false", "test"), cwd, env))
            if source_path and not Path(source_path).exists() and not Path(cwd, source_path).exists():
                raise AutomationContractError("JUNIT_SOURCE_REF_NOT_FOUND")
        else:
            raise AutomationContractError("DETERMINISTIC_VALIDATOR_NOT_AVAILABLE:%s" % runner)

        if not steps:
            raise AutomationContractError("VALIDATION_STEPS_REQUIRED")
        ready = all(step.passed for step in steps)
        refs = tuple(dict.fromkeys([step.stdout_ref for step in steps] + [step.stderr_ref for step in steps]))
        identity = {"script_id": script.script_id, "steps": [asdict(x) for x in steps]}
        return ScriptValidation(
            validation_id="VAL-" + canonical_fingerprint(identity)[:24],
            script_id=script.script_id,
            runner_type=runner,
            test_symbol=script.test_symbol,
            steps=tuple(steps),
            evidence_refs=refs,
            status="SCRIPT_READY" if ready else "SCRIPT_INVALID",
        )


@dataclass(frozen=True)
class RunnerExecutionResult:
    runner_type: str
    test_symbol: str
    exit_code: int
    status: str
    actual_result: Dict[str, Any]
    stdout_ref: str
    stderr_ref: str
    tool_call_refs: Tuple[str, ...]
    evidence_refs: Tuple[str, ...]
    duration_ms: int


class RunnerAdapter(ABC):
    runner_type = "ABSTRACT"

    def __init__(self, timeout_seconds: int = 300):
        self.harness = _ProcessHarness(timeout_seconds)

    @abstractmethod
    def command(self, script: ScriptArtifact) -> Tuple[str, ...]:
        raise NotImplementedError

    def execute(
        self,
        *,
        spec: ExecutableTestSpec,
        script: ScriptArtifact,
        validation: ScriptValidation,
        cwd: str,
        env: Optional[Mapping[str, str]] = None,
    ) -> RunnerExecutionResult:
        if not validation.ready or validation.script_id != script.script_id:
            raise AutomationContractError("SCRIPT_READY_RUNTIME_GATE_REQUIRED")
        if script.runner_type.upper() != self.runner_type:
            raise AutomationContractError("RUNNER_TYPE_MISMATCH")
        ExecutableSpecBuilder.verify_script_or_repair_binding(
            spec,
            case_fingerprint=script.case_fingerprint,
            oracle_fingerprint=script.oracle_fingerprint,
        )
        result = self.harness.run("real_runner_execution", self.command(script), cwd, env)
        call_ref = "process-call://" + sha256((script.script_id + "|" + str(time.time_ns())).encode("utf-8")).hexdigest()[:24]
        evidence = (result.stdout_ref, result.stderr_ref)
        return RunnerExecutionResult(
            runner_type=self.runner_type,
            test_symbol=script.test_symbol,
            exit_code=result.exit_code,
            status="EXECUTED",
            actual_result={
                "process_exit_code": result.exit_code,
                "runner_passed": result.passed,
                "test_symbol": script.test_symbol,
            },
            stdout_ref=result.stdout_ref,
            stderr_ref=result.stderr_ref,
            tool_call_refs=(call_ref,),
            evidence_refs=evidence,
            duration_ms=result.duration_ms,
        )


class PytestRunnerAdapter(RunnerAdapter):
    runner_type = "PYTEST"

    def command(self, script: ScriptArtifact) -> Tuple[str, ...]:
        path = ScriptValidator._local_path(script.source_ref)
        node = "%s::%s" % (path, script.test_symbol) if "::" not in script.test_symbol else script.test_symbol
        return (sys.executable, "-m", "pytest", "-q", node)


class JUnitRunnerAdapter(RunnerAdapter):
    runner_type = "JUNIT"

    def command(self, script: ScriptArtifact) -> Tuple[str, ...]:
        return ("mvn", "-q", "-Dtest=%s" % script.test_symbol, "-DfailIfNoTests=true", "-DskipTests=false", "test")
