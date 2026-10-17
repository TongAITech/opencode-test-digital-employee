"""Rebuild one trusted Script execution bundle from durable RC7 truth.

Field execution must not depend on a coordinator remembering a script path.
For one accepted Case this resolver selects the latest current-design
CASE_SCRIPT_READY receipt, reloads the runtime-hashed Script candidate and
runtime-persisted source, recompiles the frozen Case contract from the accepted
Test Design, verifies every fingerprint/identity binding and re-runs the
non-business Script readiness validator.

No chat/session state is consumed.  Superseded Design receipts, worker-declared
source refs and stale spec/oracle fingerprints fail closed.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping, Optional, Tuple

from rc6_runtime.automation import ScriptArtifact
from rc6_runtime.truth import TruthRuntime

from .candidate_payload import CandidatePayloadError, CandidatePayloadReader
from .case_fanout_conformance import (
    AcceptedCaseInventoryReader,
    CaseFanoutConformanceError,
    SCRIPT_READY_KIND,
    contract_enabled,
)
from .runtime_execution import VerifiedScriptExecutionBundle
from .script_contract import AcceptedTestDesignScriptContractCompiler, ScriptContractError
from .script_validation import EvidenceBackedScriptReadinessValidator, RC7ScriptValidationError


class CaseScriptBundleResolverError(RuntimeError):
    pass


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


def _receipt_payload(row: Mapping[str, object]) -> Mapping[str, object]:
    ref = str(row.get("content_ref") or "")
    if not ref.startswith("file://"):
        raise CaseScriptBundleResolverError("CASE_SCRIPT_RECEIPT_FILE_REQUIRED")
    path = Path(ref[len("file://"):]).expanduser().resolve()
    if not path.is_file():
        raise CaseScriptBundleResolverError("CASE_SCRIPT_RECEIPT_FILE_MISSING")
    raw = path.read_bytes()
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    if digest != str(row.get("content_hash") or ""):
        raise CaseScriptBundleResolverError("CASE_SCRIPT_RECEIPT_HASH_MISMATCH")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CaseScriptBundleResolverError("CASE_SCRIPT_RECEIPT_JSON_INVALID") from exc
    if not isinstance(payload, dict):
        raise CaseScriptBundleResolverError("CASE_SCRIPT_RECEIPT_OBJECT_REQUIRED")
    return payload


class CaseScriptExecutionBundleResolver:
    def __init__(
        self,
        *,
        evidence_root: str,
        validation_timeout_seconds: int = 180,
    ) -> None:
        self.evidence_root = Path(evidence_root).expanduser().resolve()
        self.validation_timeout_seconds = int(validation_timeout_seconds)
        if self.validation_timeout_seconds <= 0:
            raise ValueError("validation_timeout_seconds must be positive")
        self.candidate_reader = CandidatePayloadReader()
        self.contract_compiler = AcceptedTestDesignScriptContractCompiler()

    def resolve(
        self,
        truth: TruthRuntime,
        *,
        mission_id: str,
        tc_id: str,
        cwd: str,
        env: Optional[Mapping[str, str]] = None,
    ) -> VerifiedScriptExecutionBundle:
        mission_id = str(mission_id or "").strip()
        tc_id = str(tc_id or "").strip()
        if not mission_id or not tc_id:
            raise CaseScriptBundleResolverError("MISSION_AND_TC_ID_REQUIRED")
        try:
            if not contract_enabled(truth, mission_id):
                raise CaseScriptBundleResolverError("CASE_FANOUT_CONTRACT_REQUIRED")
            inventory = AcceptedCaseInventoryReader().load(truth, mission_id)
        except CaseFanoutConformanceError as exc:
            raise CaseScriptBundleResolverError(str(exc)) from exc
        accepted = next((item for item in inventory.cases if item.tc_id == tc_id), None)
        if accepted is None:
            raise CaseScriptBundleResolverError("CASE_NOT_IN_ACCEPTED_DESIGN:%s" % tc_id)

        receipt_row, receipt = self._current_receipt(
            truth,
            mission_id=mission_id,
            tc_id=tc_id,
            design_artifact_id=inventory.design_artifact_id,
            design_content_hash=inventory.design_content_hash,
            case_hash=accepted.case_hash,
        )
        try:
            contract = self.contract_compiler.compile(
                truth,
                mission_id=mission_id,
                design_artifact_id=inventory.design_artifact_id,
                tc_id=tc_id,
                automation_mapping={"reuse": {}},
            )
        except ScriptContractError as exc:
            raise CaseScriptBundleResolverError("CASE_SCRIPT_CONTRACT_RECOMPILE_FAILED:%s" % exc) from exc
        expected_receipt = {
            "design_artifact_id": inventory.design_artifact_id,
            "design_content_hash": inventory.design_content_hash,
            "case_hash": accepted.case_hash,
            "tc_id": tc_id,
            "case_version": accepted.case_version,
            "layer": accepted.layer,
            "spec_id": contract.spec.spec_id,
            "case_fingerprint": contract.spec.case_fingerprint,
            "oracle_fingerprint": contract.spec.oracle_fingerprint,
        }
        for field, value in expected_receipt.items():
            if receipt.get(field) != value:
                raise CaseScriptBundleResolverError(
                    "CASE_SCRIPT_RECEIPT_BINDING_MISMATCH:%s:%s" % (tc_id, field)
                )

        candidate_id = str(receipt.get("script_candidate_artifact_id") or "")
        script_task_id = str(receipt.get("script_task_id") or "")
        if not candidate_id or not script_task_id:
            raise CaseScriptBundleResolverError("CASE_SCRIPT_CANDIDATE_IDENTITY_REQUIRED:%s" % tc_id)
        try:
            candidate = self.candidate_reader.load(
                truth,
                candidate_id,
                expected_mission_id=mission_id,
                expected_task_id=script_task_id,
            )
        except CandidatePayloadError as exc:
            raise CaseScriptBundleResolverError("CASE_SCRIPT_CANDIDATE_INVALID:%s" % exc) from exc
        semantic = candidate.semantic_payload
        binding = semantic.get("binding")
        source_text = semantic.get("source_text")
        test_symbol = semantic.get("test_symbol")
        if not isinstance(binding, dict):
            raise CaseScriptBundleResolverError("CASE_SCRIPT_BINDING_REQUIRED:%s" % tc_id)
        if not isinstance(source_text, str) or not source_text.strip():
            raise CaseScriptBundleResolverError("CASE_SCRIPT_SOURCE_TEXT_REQUIRED:%s" % tc_id)
        if not isinstance(test_symbol, str) or not test_symbol.strip():
            raise CaseScriptBundleResolverError("CASE_SCRIPT_TEST_SYMBOL_REQUIRED:%s" % tc_id)
        for field, value in {
            "spec_id": contract.spec.spec_id,
            "tc_id": tc_id,
            "case_version": accepted.case_version,
            "runner_type": contract.spec.runner_type,
            "case_fingerprint": contract.spec.case_fingerprint,
            "oracle_fingerprint": contract.spec.oracle_fingerprint,
            "design_content_hash": inventory.design_content_hash,
        }.items():
            if binding.get(field) != value:
                raise CaseScriptBundleResolverError(
                    "CASE_SCRIPT_CANDIDATE_BINDING_MISMATCH:%s:%s" % (tc_id, field)
                )

        source_ref, source_digest, source_evidence_id = self._source_truth(
            truth,
            mission_id=mission_id,
            script_task_id=script_task_id,
            candidate_id=candidate_id,
            spec_id=contract.spec.spec_id,
            source_text=source_text,
        )
        script_id = _stable_id(
            "SCRIPT-RC7",
            mission_id,
            contract.spec.spec_id,
            source_digest,
            test_symbol.strip(),
        )
        if receipt.get("script_id") != script_id:
            raise CaseScriptBundleResolverError("CASE_SCRIPT_ID_DRIFT:%s" % tc_id)

        artifact_rows = truth.query("rc7_artifact", artifact_id=candidate_id)
        candidate_evidence = list(artifact_rows[0].get("evidence_refs") or []) if len(artifact_rows) == 1 else []
        script = ScriptArtifact(
            script_id=script_id,
            spec_id=contract.spec.spec_id,
            tc_id=tc_id,
            case_version=accepted.case_version,
            layer=accepted.layer,
            runner_type=contract.spec.runner_type,
            source_ref=source_ref,
            test_symbol=test_symbol.strip(),
            case_fingerprint=contract.spec.case_fingerprint,
            oracle_fingerprint=contract.spec.oracle_fingerprint,
            reuse_refs=(),
            builder_evidence_refs=tuple(
                dict.fromkeys(
                    [str(ref) for ref in candidate_evidence if isinstance(ref, str) and ref]
                    + [source_evidence_id]
                )
            ),
            revision=1,
        )
        try:
            validation = EvidenceBackedScriptReadinessValidator(
                evidence_root=str(self.evidence_root),
                timeout_seconds=self.validation_timeout_seconds,
            ).validate(spec=contract.spec, script=script, cwd=cwd, env=env)
        except (RC7ScriptValidationError, OSError) as exc:
            raise CaseScriptBundleResolverError("CASE_SCRIPT_REVALIDATION_FAILED:%s" % exc) from exc
        if not validation.ready:
            raise CaseScriptBundleResolverError("CASE_SCRIPT_REVALIDATION_NOT_READY:%s" % tc_id)

        spec_ref = self._persist_runtime_spec(
            mission_id=mission_id,
            tc_id=tc_id,
            contract=contract,
        )
        task_rows = truth.query("rc7_task", task_id=script_task_id)
        if len(task_rows) != 1 or task_rows[0].get("mission_id") != mission_id:
            raise CaseScriptBundleResolverError("CASE_SCRIPT_TASK_NOT_UNIQUE:%s" % tc_id)
        evaluation_id = str(task_rows[0].get("evaluation_id") or receipt_row.get("evidence_id") or "")
        return VerifiedScriptExecutionBundle(
            upstream_mission_id=mission_id,
            upstream_task_id=script_task_id,
            upstream_evaluation_id=evaluation_id,
            upstream_result_ref=str(receipt_row.get("content_ref") or ""),
            spec_ref=spec_ref,
            frozen_case=dict(contract.frozen_case),
            spec=contract.spec,
            script=script,
            validation=validation,
            source_sha256=source_digest,
        )

    @staticmethod
    def _current_receipt(
        truth: TruthRuntime,
        *,
        mission_id: str,
        tc_id: str,
        design_artifact_id: str,
        design_content_hash: str,
        case_hash: str,
    ) -> Tuple[Mapping[str, object], Mapping[str, object]]:
        matches = []
        for row in truth.query("rc7_evidence", mission_id=mission_id):
            if row.get("kind") != SCRIPT_READY_KIND:
                continue
            payload = _receipt_payload(row)
            if (
                payload.get("design_artifact_id") == design_artifact_id
                and payload.get("design_content_hash") == design_content_hash
                and payload.get("case_hash") == case_hash
                and payload.get("tc_id") == tc_id
            ):
                matches.append((int(row.get("created_at", 0)), str(row.get("evidence_id") or ""), row, payload))
        if not matches:
            raise CaseScriptBundleResolverError("CASE_SCRIPT_READY_RECEIPT_REQUIRED:%s" % tc_id)
        matches.sort(key=lambda item: (item[0], item[1]))
        _created, _id, row, payload = matches[-1]
        return row, payload

    @staticmethod
    def _source_truth(
        truth: TruthRuntime,
        *,
        mission_id: str,
        script_task_id: str,
        candidate_id: str,
        spec_id: str,
        source_text: str,
    ) -> Tuple[str, str, str]:
        matches = []
        for row in truth.query("rc7_evidence", mission_id=mission_id):
            refs = list(row.get("subject_refs") or [])
            if (
                row.get("kind") == "RUNTIME_PERSISTED_SCRIPT_SOURCE"
                and script_task_id in refs
                and candidate_id in refs
                and spec_id in refs
            ):
                matches.append(row)
        if len(matches) != 1:
            raise CaseScriptBundleResolverError(
                "CASE_SCRIPT_SOURCE_EVIDENCE_NOT_UNIQUE:%s:%d" % (candidate_id, len(matches))
            )
        row = matches[0]
        ref = str(row.get("content_ref") or "")
        if not ref.startswith("file://"):
            raise CaseScriptBundleResolverError("CASE_SCRIPT_SOURCE_FILE_REQUIRED")
        path = Path(ref[len("file://"):]).expanduser().resolve()
        if not path.is_file():
            raise CaseScriptBundleResolverError("CASE_SCRIPT_SOURCE_FILE_MISSING")
        raw = path.read_bytes()
        try:
            persisted = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CaseScriptBundleResolverError("CASE_SCRIPT_SOURCE_NOT_UTF8") from exc
        if persisted != source_text:
            raise CaseScriptBundleResolverError("CASE_SCRIPT_SOURCE_CANDIDATE_DRIFT")
        digest = hashlib.sha256(raw).hexdigest()
        if str(row.get("content_hash") or "") != "sha256:" + digest:
            raise CaseScriptBundleResolverError("CASE_SCRIPT_SOURCE_HASH_MISMATCH")
        evidence_id = str(row.get("evidence_id") or "")
        if not evidence_id:
            raise CaseScriptBundleResolverError("CASE_SCRIPT_SOURCE_EVIDENCE_ID_REQUIRED")
        return "file://" + str(path), digest, evidence_id

    def _persist_runtime_spec(self, *, mission_id: str, tc_id: str, contract) -> str:
        payload = {
            "mission_id": mission_id,
            "design_artifact_id": contract.design_artifact_id,
            "design_content_hash": contract.design_content_hash,
            "tc_id": tc_id,
            "frozen_case": contract.frozen_case,
            "spec": contract.spec.to_artifact(),
        }
        raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n").encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        folder = self.evidence_root / "case-bundles" / mission_id / tc_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / ("spec-" + digest[:20] + ".json")
        if path.exists() and path.read_bytes() != raw:
            raise CaseScriptBundleResolverError("CASE_RUNTIME_SPEC_IMMUTABILITY_CONFLICT")
        if not path.exists():
            path.write_bytes(raw)
        return "file://" + str(path)
