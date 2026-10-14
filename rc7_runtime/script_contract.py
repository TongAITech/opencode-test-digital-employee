"""Deterministic Test Design -> frozen Case -> ExecutableTestSpec compiler.

A Script Worker never gets authority to reinterpret a TestCase. RC7 first
reloads the runtime-hashed, accepted TEST_DESIGN_MODEL, selects one concrete
case, freezes the exact executable fields under Runtime ownership, and compiles
an immutable ExecutableTestSpec through the inherited RC6 builder. Missing
steps/data/oracle/runner semantics fail before any script Worker is launched.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

from rc6_runtime.executable_spec import ExecutableTestSpec
from rc6_runtime.truth import TruthRuntime

from .candidate_payload import CandidatePayloadReader
from .script_readiness_loop import ScriptReadinessClosedLoop


class ScriptContractError(RuntimeError):
    pass


def _require_text(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ScriptContractError(code)
    return value.strip()


def _text_tuple(value: Any, code: str, *, nonempty: bool = False) -> Tuple[str, ...]:
    if not isinstance(value, list):
        raise ScriptContractError(code)
    result = tuple(item.strip() for item in value if isinstance(item, str) and item.strip())
    if len(result) != len(value) or (nonempty and not result):
        raise ScriptContractError(code)
    return result


@dataclass(frozen=True)
class CompiledScriptContract:
    design_artifact_id: str
    design_content_hash: str
    tc_id: str
    frozen_case: Dict[str, Any]
    spec: ExecutableTestSpec


class AcceptedTestDesignScriptContractCompiler:
    """Compile one accepted Test Design case into immutable script truth."""

    def __init__(self) -> None:
        self.reader = CandidatePayloadReader()
        self.readiness = ScriptReadinessClosedLoop()

    def compile(
        self,
        truth: TruthRuntime,
        *,
        mission_id: str,
        design_artifact_id: str,
        tc_id: str,
        automation_mapping: Optional[Mapping[str, Any]] = None,
    ) -> CompiledScriptContract:
        artifact_rows = truth.query("rc7_artifact", artifact_id=design_artifact_id)
        if len(artifact_rows) != 1:
            raise ScriptContractError("SCRIPT_PARENT_TEST_DESIGN_ARTIFACT_NOT_UNIQUE")
        artifact_row = artifact_rows[0]
        if artifact_row.get("mission_id") != mission_id:
            raise ScriptContractError("SCRIPT_PARENT_TEST_DESIGN_MISSION_MISMATCH")
        if artifact_row.get("artifact_type_name") != "TEST_DESIGN_MODEL":
            raise ScriptContractError("SCRIPT_PARENT_TEST_DESIGN_TYPE_REQUIRED")
        producer_task_id = artifact_row.get("producer_task_id")
        if not isinstance(producer_task_id, str) or not producer_task_id:
            raise ScriptContractError("SCRIPT_PARENT_TEST_DESIGN_PRODUCER_REQUIRED")
        task_rows = truth.query("rc7_task", task_id=producer_task_id)
        if len(task_rows) != 1 or task_rows[0].get("state") != "PASS":
            raise ScriptContractError("SCRIPT_PARENT_TEST_DESIGN_NOT_ACCEPTED")

        candidate = self.reader.load(
            truth,
            design_artifact_id,
            expected_mission_id=mission_id,
            expected_task_id=producer_task_id,
        )
        cases = candidate.semantic_payload.get("cases")
        if not isinstance(cases, list) or not cases:
            raise ScriptContractError("SCRIPT_PARENT_TEST_CASES_REQUIRED")
        matches = [case for case in cases if isinstance(case, dict) and case.get("tc_id") == tc_id]
        if len(matches) != 1:
            raise ScriptContractError("SCRIPT_TARGET_TEST_CASE_NOT_UNIQUE:%s" % tc_id)
        raw_case = dict(matches[0])

        mission_rows = truth.query("rc7_mission", mission_id=mission_id)
        if len(mission_rows) != 1:
            raise ScriptContractError("SCRIPT_MISSION_NOT_FOUND")
        release_id = _require_text(mission_rows[0].get("release_id"), "SCRIPT_RELEASE_ID_REQUIRED")
        requirement_id = _require_text(raw_case.get("requirement_id"), "SCRIPT_CASE_REQUIREMENT_ID_REQUIRED")
        layer = _require_text(raw_case.get("layer"), "SCRIPT_CASE_LAYER_REQUIRED").upper()
        case_version = raw_case.get("case_version", 1)
        if not isinstance(case_version, int) or case_version < 1:
            raise ScriptContractError("SCRIPT_CASE_VERSION_INVALID")

        preconditions = raw_case.get("preconditions")
        if not isinstance(preconditions, list):
            raise ScriptContractError("SCRIPT_CASE_PRECONDITIONS_REQUIRED")
        steps = raw_case.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ScriptContractError("SCRIPT_CASE_STEPS_REQUIRED")
        expected = _require_text(raw_case.get("expected"), "SCRIPT_CASE_EXPECTED_REQUIRED")
        oracle = raw_case.get("oracle")
        if oracle in (None, "", [], {}):
            raise ScriptContractError("SCRIPT_CASE_ORACLE_REQUIRED")
        evidence_requirements = _text_tuple(
            raw_case.get("evidence_requirements"),
            "SCRIPT_CASE_EVIDENCE_REQUIREMENTS_REQUIRED",
            nonempty=True,
        )
        target_requirements = raw_case.get("target_requirements", [requirement_id])
        target_tuple = _text_tuple(target_requirements, "SCRIPT_TARGET_REQUIREMENTS_INVALID", nonempty=True)
        data_tuple = _text_tuple(raw_case.get("test_data_refs", []), "SCRIPT_TEST_DATA_REFS_INVALID")
        oracle_tuple = _text_tuple(raw_case.get("oracle_refs"), "SCRIPT_ORACLE_REFS_REQUIRED", nonempty=True)
        cleanup_policy = raw_case.get("cleanup_policy")
        if not isinstance(cleanup_policy, dict):
            raise ScriptContractError("SCRIPT_CLEANUP_POLICY_REQUIRED")
        runner_type = _require_text(raw_case.get("runner_type"), "SCRIPT_RUNNER_TYPE_REQUIRED").upper()

        # Runtime owns the freeze. Worker-authored status/release fields cannot
        # weaken or redirect the immutable execution contract.
        frozen_case = dict(raw_case)
        frozen_case.update(
            {
                "tc_id": tc_id,
                "case_version": case_version,
                "release_id": release_id,
                "requirement_id": requirement_id,
                "layer": layer,
                "status": "FROZEN",
                "preconditions": preconditions,
                "steps": steps,
                "expected": expected,
                "oracle": oracle,
                "evidence_requirements": list(evidence_requirements),
            }
        )
        spec = self.readiness.compile_execution_contract(
            case=frozen_case,
            target_requirements=target_tuple,
            test_data_refs=data_tuple,
            oracle_refs=oracle_tuple,
            cleanup_policy=cleanup_policy,
            runner_type=runner_type,
            automation_mapping=dict(automation_mapping or {"reuse": {}}),
        )
        return CompiledScriptContract(
            design_artifact_id=design_artifact_id,
            design_content_hash=candidate.content_hash,
            tc_id=tc_id,
            frozen_case=frozen_case,
            spec=spec,
        )
