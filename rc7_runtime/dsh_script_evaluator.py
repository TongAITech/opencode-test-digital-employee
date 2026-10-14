"""RC7 DSH Script candidate -> runtime source -> deterministic readiness gate.

The automation Worker may propose source code, but cannot declare SCRIPT_READY,
choose Case/Oracle fingerprints, or supply authoritative validation results.
RC7 persists source itself, binds it to a Runtime-compiled ExecutableTestSpec,
runs an evidence-backed non-business readiness validator, canonicalizes logs
into R1 Evidence, and only then lets ScriptReadinessClosedLoop decide PASS or
repair.
"""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from rc6_runtime.automation import ScriptArtifact, ScriptValidation

from .candidate_payload import CandidatePayloadReader
from .closed_loop_control import ClosedLoopControlPlane
from .models import Evaluation, EvaluationResult, Evidence, Gap, GapSeverity, TaskStatus
from .script_contract import CompiledScriptContract
from .script_readiness_loop import ScriptReadinessClosedLoop, ScriptReadinessLoopResult
from .script_validation import EvidenceBackedScriptReadinessValidator, RC7ScriptValidationError
from .truth_overlay import append_entity


class DshScriptReadinessEvaluatorError(RuntimeError):
    pass


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


@dataclass(frozen=True)
class DshScriptReadinessEvaluation:
    task_id: str
    artifact_id: str
    worker_id: str
    script: Optional[ScriptArtifact]
    validation: Optional[ScriptValidation]
    source_ref: Optional[str]
    loop_result: ScriptReadinessLoopResult


class DshScriptReadinessEvaluator:
    def __init__(
        self,
        *,
        evidence_root: str,
        validation_timeout_seconds: int = 180,
    ) -> None:
        self.evidence_root = Path(evidence_root).resolve()
        self.reader = CandidatePayloadReader()
        self.loop = ScriptReadinessClosedLoop(validation_timeout_seconds=validation_timeout_seconds)
        self.validator = EvidenceBackedScriptReadinessValidator(
            evidence_root=str(self.evidence_root),
            timeout_seconds=validation_timeout_seconds,
        )

    def evaluate(
        self,
        control: ClosedLoopControlPlane,
        task_id: str,
        artifact_id: str,
        *,
        contract: CompiledScriptContract,
        cwd: str,
        env: Optional[Mapping[str, str]] = None,
    ) -> DshScriptReadinessEvaluation:
        task = control.scheduler.task(task_id)
        if task.node != "SCRIPT_READINESS":
            raise DshScriptReadinessEvaluatorError("SCRIPT_EVALUATOR_TASK_NODE_MISMATCH")
        if task.state != TaskStatus.OUTPUT_PRODUCED:
            raise DshScriptReadinessEvaluatorError("SCRIPT_EVALUATOR_CANDIDATE_REQUIRED")
        worker_id = str(task.lease_owner or "")
        if not worker_id:
            raise DshScriptReadinessEvaluatorError("SCRIPT_WORKER_IDENTITY_MISSING")
        if artifact_id not in task.output_artifact_refs:
            raise DshScriptReadinessEvaluatorError("SCRIPT_ARTIFACT_NOT_TASK_OUTPUT")
        if contract.design_artifact_id not in task.input_artifact_refs:
            raise DshScriptReadinessEvaluatorError("SCRIPT_CONTRACT_PARENT_NOT_TASK_INPUT")

        candidate = self.reader.load(
            control.truth,
            artifact_id,
            expected_mission_id=control.mission_id,
            expected_task_id=task_id,
        )
        payload = dict(candidate.semantic_payload)
        artifact_row = control.truth.query("rc7_artifact", artifact_id=artifact_id)[0]
        candidate_evidence = self._durable_evidence_ids(control, artifact_row)

        binding_reasons = self._binding_reasons(payload.get("binding"), contract)
        source_text = payload.get("source_text")
        test_symbol = payload.get("test_symbol")
        if not isinstance(source_text, str) or not source_text.strip():
            binding_reasons.append("SCRIPT_SOURCE_TEXT_REQUIRED")
        if not isinstance(test_symbol, str) or not test_symbol.strip():
            binding_reasons.append("SCRIPT_TEST_SYMBOL_REQUIRED")
        if binding_reasons:
            result = self._repair_result(
                control,
                artifact_id=artifact_id,
                contract=contract,
                reasons=binding_reasons,
                category="SCRIPT_BINDING_VIOLATION",
                evidence_refs=candidate_evidence,
            )
            return DshScriptReadinessEvaluation(task_id, artifact_id, worker_id, None, None, None, result)

        assert isinstance(source_text, str)
        assert isinstance(test_symbol, str)
        source_path, source_evidence_id = self._persist_source(
            control,
            task_id=task_id,
            artifact_id=artifact_id,
            contract=contract,
            worker_id=worker_id,
            source_text=source_text,
        )
        builder_evidence = tuple(dict.fromkeys(candidate_evidence + [source_evidence_id]))
        script_id = _stable_id(
            "SCRIPT-RC7",
            control.mission_id,
            contract.spec.spec_id,
            hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
            test_symbol,
        )
        script = ScriptArtifact(
            script_id=script_id,
            spec_id=contract.spec.spec_id,
            tc_id=contract.spec.tc_id,
            case_version=contract.spec.case_version,
            layer=contract.spec.layer,
            runner_type=contract.spec.runner_type,
            source_ref="file://" + str(source_path),
            test_symbol=test_symbol.strip(),
            case_fingerprint=contract.spec.case_fingerprint,
            oracle_fingerprint=contract.spec.oracle_fingerprint,
            reuse_refs=tuple(self._reuse_refs(contract.spec.automation_mapping)),
            builder_evidence_refs=builder_evidence,
            revision=1,
        )

        structural_reasons = self._source_structure_reasons(script, source_text)
        try:
            raw_validation = self.validator.validate(
                spec=contract.spec,
                script=script,
                cwd=cwd,
                env=env,
            )
        except (RC7ScriptValidationError, OSError) as exc:
            reasons = structural_reasons + ["SCRIPT_VALIDATOR_ERROR:%s" % exc]
            result = self._repair_result(
                control,
                artifact_id=artifact_id,
                contract=contract,
                reasons=reasons,
                category="SCRIPT_VALIDATION_FAILED",
                evidence_refs=list(builder_evidence),
            )
            return DshScriptReadinessEvaluation(
                task_id,
                artifact_id,
                worker_id,
                script,
                None,
                script.source_ref,
                result,
            )

        validation = self._canonicalize_validation_evidence(
            control,
            task_id=task_id,
            artifact_id=artifact_id,
            script=script,
            validation=raw_validation,
        )
        base = self.loop.evaluate(
            mission_id=control.mission_id,
            artifact_ref=artifact_id,
            spec=contract.spec,
            script=script,
            validation=validation,
            evaluator_ref="rc7-runtime-script-readiness-gate",
        )
        result = self._merge_structural_gaps(
            control,
            artifact_id=artifact_id,
            base=base,
            contract=contract,
            reasons=structural_reasons,
            evidence_refs=list(validation.evidence_refs) + list(builder_evidence),
        )
        return DshScriptReadinessEvaluation(
            task_id=task_id,
            artifact_id=artifact_id,
            worker_id=worker_id,
            script=script,
            validation=validation,
            source_ref=script.source_ref,
            loop_result=result,
        )

    def evaluate_and_apply(
        self,
        control: ClosedLoopControlPlane,
        task_id: str,
        artifact_id: str,
        *,
        contract: CompiledScriptContract,
        cwd: str,
        env: Optional[Mapping[str, str]] = None,
    ) -> DshScriptReadinessEvaluation:
        evaluated = self.evaluate(
            control,
            task_id,
            artifact_id,
            contract=contract,
            cwd=cwd,
            env=env,
        )
        control.accept_evaluation(
            task_id,
            evaluation=evaluated.loop_result.evaluation,
            gaps=evaluated.loop_result.gaps,
        )
        return evaluated

    @staticmethod
    def _durable_evidence_ids(
        control: ClosedLoopControlPlane,
        artifact_row: Mapping[str, object],
    ) -> List[str]:
        refs = artifact_row.get("evidence_refs", [])
        if not isinstance(refs, list) or not refs:
            raise DshScriptReadinessEvaluatorError("SCRIPT_CANDIDATE_EVIDENCE_MISSING")
        result = []
        for ref in refs:
            if not isinstance(ref, str) or not ref:
                continue
            rows = control.truth.query("rc7_evidence", evidence_id=ref)
            if len(rows) != 1 or rows[0].get("mission_id") != control.mission_id:
                raise DshScriptReadinessEvaluatorError("SCRIPT_CANDIDATE_EVIDENCE_NOT_DURABLE:%s" % ref)
            result.append(ref)
        if not result:
            raise DshScriptReadinessEvaluatorError("SCRIPT_CANDIDATE_HAS_NO_DURABLE_EVIDENCE")
        return list(dict.fromkeys(result))

    @staticmethod
    def _binding_reasons(raw: object, contract: CompiledScriptContract) -> List[str]:
        if not isinstance(raw, dict):
            return ["SCRIPT_BINDING_OBJECT_REQUIRED"]
        expected = {
            "spec_id": contract.spec.spec_id,
            "tc_id": contract.spec.tc_id,
            "case_version": contract.spec.case_version,
            "runner_type": contract.spec.runner_type,
            "case_fingerprint": contract.spec.case_fingerprint,
            "oracle_fingerprint": contract.spec.oracle_fingerprint,
            "design_content_hash": contract.design_content_hash,
        }
        reasons = []
        for key, value in expected.items():
            if raw.get(key) != value:
                reasons.append("SCRIPT_BINDING_MISMATCH:%s" % key)
        return reasons

    def _persist_source(
        self,
        control: ClosedLoopControlPlane,
        *,
        task_id: str,
        artifact_id: str,
        contract: CompiledScriptContract,
        worker_id: str,
        source_text: str,
    ) -> Tuple[Path, str]:
        runner = contract.spec.runner_type.upper()
        suffix = ".py" if runner == "PYTEST" else ".java" if runner == "JUNIT" else ".txt"
        digest = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        folder = self.evidence_root / "script-sources" / control.mission_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / ("%s-%s%s" % (contract.spec.tc_id, digest[:16], suffix))
        path.write_text(source_text, encoding="utf-8")
        evidence_id = _stable_id("EVD-SCRIPT-SOURCE", control.mission_id, artifact_id, digest)
        if not control.truth.query("rc7_evidence", evidence_id=evidence_id):
            append_entity(
                control.truth,
                Evidence(
                    evidence_id=evidence_id,
                    mission_id=control.mission_id,
                    kind="RUNTIME_PERSISTED_SCRIPT_SOURCE",
                    source_ref="dsh://worker/%s" % worker_id,
                    content_ref="file://" + str(path),
                    subject_refs=[task_id, artifact_id, contract.spec.spec_id],
                    content_hash="sha256:" + digest,
                ),
                release_id=control.release_id,
                artifact_version=1,
            )
        return path, evidence_id

    @staticmethod
    def _reuse_refs(mapping: Mapping[str, object]) -> Sequence[str]:
        reuse = mapping.get("reuse", {}) if isinstance(mapping, Mapping) else {}
        refs = []
        if isinstance(reuse, dict):
            for value in reuse.values():
                if isinstance(value, list):
                    refs.extend(item for item in value if isinstance(item, str) and item)
        return tuple(dict.fromkeys(refs))

    @staticmethod
    def _source_structure_reasons(script: ScriptArtifact, source_text: str) -> List[str]:
        if script.runner_type.upper() != "PYTEST":
            return []
        try:
            tree = ast.parse(source_text)
        except SyntaxError:
            return []  # the real validator owns syntax failure evidence
        symbol = script.test_symbol.split("::")[-1]
        functions = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == symbol]
        if not functions:
            return ["SCRIPT_TEST_SYMBOL_IMPLEMENTATION_MISSING"]
        target = functions[0]
        meaningful_call = any(isinstance(node, ast.Call) for node in ast.walk(target))
        asserts = [node for node in ast.walk(target) if isinstance(node, ast.Assert)]
        nontrivial_assert = any(not (isinstance(node.test, ast.Constant) and node.test.value is True) for node in asserts)
        if not meaningful_call and not nontrivial_assert:
            return ["ASSERTION_IMPLEMENTATION_DEFECT:PLACEHOLDER_ONLY"]
        return []

    @staticmethod
    def _canonicalize_validation_evidence(
        control: ClosedLoopControlPlane,
        *,
        task_id: str,
        artifact_id: str,
        script: ScriptArtifact,
        validation: ScriptValidation,
    ) -> ScriptValidation:
        evidence_ids = []
        for ref in validation.evidence_refs:
            if not isinstance(ref, str) or not ref:
                continue
            digest = ""
            if ref.startswith("file://"):
                path = Path(ref[len("file://"):])
                if path.is_file():
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
            evidence_id = _stable_id("EVD-SCRIPT-VALIDATION", control.mission_id, script.script_id, ref, digest)
            if not control.truth.query("rc7_evidence", evidence_id=evidence_id):
                append_entity(
                    control.truth,
                    Evidence(
                        evidence_id=evidence_id,
                        mission_id=control.mission_id,
                        kind="SCRIPT_READINESS_VALIDATION_PROOF",
                        source_ref="runtime://script-validator",
                        content_ref=ref,
                        subject_refs=[task_id, artifact_id, script.script_id, validation.validation_id],
                        content_hash=("sha256:" + digest) if digest else None,
                    ),
                    release_id=control.release_id,
                    artifact_version=1,
                )
            evidence_ids.append(evidence_id)
        return ScriptValidation(
            validation_id=validation.validation_id,
            script_id=validation.script_id,
            runner_type=validation.runner_type,
            test_symbol=validation.test_symbol,
            steps=validation.steps,
            evidence_refs=tuple(dict.fromkeys(evidence_ids)),
            status=validation.status,
        )

    def _merge_structural_gaps(
        self,
        control: ClosedLoopControlPlane,
        *,
        artifact_id: str,
        base: ScriptReadinessLoopResult,
        contract: CompiledScriptContract,
        reasons: Sequence[str],
        evidence_refs: Sequence[str],
    ) -> ScriptReadinessLoopResult:
        if not reasons:
            return base
        extra = []
        for reason in sorted(set(reasons)):
            extra.append(
                Gap(
                    gap_id=_stable_id("GAP-SCRIPT-STRUCT", control.mission_id, artifact_id, reason),
                    mission_id=control.mission_id,
                    source_node="SCRIPT_READINESS",
                    category="ASSERTION_IMPLEMENTATION_DEFECT",
                    severity=GapSeverity.HIGH,
                    target_node="SCRIPT_READINESS",
                    description=reason,
                    subject_refs=[artifact_id, contract.spec.spec_id, contract.spec.tc_id],
                    evidence_refs=list(dict.fromkeys(evidence_refs)),
                    acceptance_criteria=["generated script implements a non-placeholder executable assertion/oracle path"],
                )
            )
        gaps = tuple(list(base.gaps) + extra)
        dimensions = dict(base.evaluation.dimensions)
        dimensions["structural_reasons"] = sorted(set(reasons))
        evaluation = Evaluation(
            evaluation_id=_stable_id("EVAL-SCRIPT-RC7", control.mission_id, artifact_id, ",".join(sorted(gap.gap_id for gap in gaps))),
            mission_id=control.mission_id,
            node="SCRIPT_READINESS",
            artifact_refs=[artifact_id],
            result=EvaluationResult.REPAIR_REQUIRED,
            evaluator_ref=base.evaluation.evaluator_ref,
            dimensions=dimensions,
            gap_refs=[gap.gap_id for gap in gaps],
            evidence_refs=list(dict.fromkeys(list(base.evaluation.evidence_refs) + list(evidence_refs))),
        )
        return ScriptReadinessLoopResult(evaluation=evaluation, gaps=gaps, script_ready=False)

    def _repair_result(
        self,
        control: ClosedLoopControlPlane,
        *,
        artifact_id: str,
        contract: CompiledScriptContract,
        reasons: Sequence[str],
        category: str,
        evidence_refs: Sequence[str],
    ) -> ScriptReadinessLoopResult:
        gaps = []
        for reason in sorted(set(reasons)):
            gaps.append(
                Gap(
                    gap_id=_stable_id("GAP-SCRIPT-RC7", control.mission_id, artifact_id, category, reason),
                    mission_id=control.mission_id,
                    source_node="SCRIPT_READINESS",
                    category=category,
                    severity=GapSeverity.HIGH if category != "SCRIPT_BINDING_VIOLATION" else GapSeverity.BLOCKER,
                    target_node="SCRIPT_READINESS",
                    description=reason,
                    subject_refs=[artifact_id, contract.spec.spec_id, contract.spec.tc_id],
                    evidence_refs=list(dict.fromkeys(evidence_refs)),
                    acceptance_criteria=["runtime Script readiness contract no longer reports %s" % reason],
                )
            )
        evaluation = Evaluation(
            evaluation_id=_stable_id("EVAL-SCRIPT-RC7", control.mission_id, artifact_id, category, ",".join(sorted(set(reasons)))),
            mission_id=control.mission_id,
            node="SCRIPT_READINESS",
            artifact_refs=[artifact_id],
            result=EvaluationResult.REPAIR_REQUIRED,
            evaluator_ref="rc7-runtime-script-readiness-gate",
            dimensions={
                "gate_status": "SCRIPT_NOT_READY",
                "reasons": list(sorted(set(reasons))),
                "business_assertion_executed": False,
                "case_fingerprint": contract.spec.case_fingerprint,
                "oracle_fingerprint": contract.spec.oracle_fingerprint,
            },
            gap_refs=[gap.gap_id for gap in gaps],
            evidence_refs=list(dict.fromkeys(evidence_refs)),
        )
        return ScriptReadinessLoopResult(evaluation=evaluation, gaps=tuple(gaps), script_ready=False)
