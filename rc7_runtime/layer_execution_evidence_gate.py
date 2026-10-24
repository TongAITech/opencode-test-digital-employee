"""RC7.1 deterministic L4-L7 production evidence contract.

The gate is independent from model judgement and follows the shared canonical
layer registry:

* L4 UI_BROWSER       -> browser/UI + fresh 4A proof when required
* L5 CROSS_SYSTEM_E2E -> real end-to-end chain proof
* L6 PERFORMANCE      -> governed k6 execution proof
* L7 SECURITY         -> governed ZAP execution proof

A generic ExecutionRecord PASS is not conclusive until current-attempt evidence
for its layer is complete. Historical/self-claimed evidence cannot satisfy this
gate. Legacy RC7.1 L5=API/L6=capability/L7=E2E payloads are intentionally not
accepted as canonical evidence.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence, Tuple

from rc6_runtime.execution import ExecutionRecord

from .authority import execution_session_id


@dataclass(frozen=True)
class LayerEvidenceResult:
    passed: bool
    reason: str
    missing: Tuple[str, ...] = ()


@dataclass(frozen=True)
class L4UiEvidence:
    video_ref: str = ""
    trace_ref: str = ""
    har_ref: str = ""
    screenshot_refs: Tuple[str, ...] = ()
    oracle_ref: str = ""
    actual_result_ref: str = ""


@dataclass(frozen=True)
class L5E2EEvidence:
    stages: Tuple[str, ...] = ()
    runtime_refs: Tuple[str, ...] = ()
    oracle_ref: str = ""
    actual_result_ref: str = ""


@dataclass(frozen=True)
class L6K6Evidence:
    tool_name: str = ""
    tool_version: str = ""
    script_sha256: str = ""
    scenario_ref: str = ""
    threshold_ref: str = ""
    summary_ref: str = ""
    stdout_ref: str = ""
    exit_code: int = -1


@dataclass(frozen=True)
class L7ZapEvidence:
    tool_name: str = ""
    tool_version: str = ""
    target_ref: str = ""
    scan_config_ref: str = ""
    spider_ref: str = ""
    passive_scan_ref: str = ""
    active_scan_ref: str = ""
    html_report_ref: str = ""
    json_report_ref: str = ""
    exit_code: int = -1


class LayerExecutionEvidenceGate:
    """Fail closed for any would-be PASS at L4-L7."""

    LAYERS = {"L4", "L5", "L6", "L7"}
    L4_REQUIRED_ARTIFACTS = ("screenshot", "dom", "trace", "network")
    E2E_REQUIRED_SEGMENTS = (
        "entry",
        "frontend",
        "api",
        "service",
        "data_or_state",
        "business_result",
        "oracle",
    )
    L6_REQUIRED_REFS = ("scenario_ref", "threshold_ref", "summary_ref", "stdout_ref")
    L7_REQUIRED_REFS = (
        "scan_config_ref",
        "spider_ref",
        "passive_scan_ref",
        "active_scan_ref",
        "html_report_ref",
        "json_report_ref",
    )

    def verify_record(self, *, mission_id: str, record: ExecutionRecord) -> LayerEvidenceResult:
        layer = str(record.layer).upper()
        if layer not in self.LAYERS:
            return LayerEvidenceResult(True, "LAYER_EVIDENCE_CONTRACT_NOT_REQUIRED", ())

        actual = record.actual_result if isinstance(record.actual_result, dict) else {}
        evidence = actual.get("layer_evidence")
        if not isinstance(evidence, dict):
            return LayerEvidenceResult(False, "LAYER_EVIDENCE_REQUIRED", ("layer_evidence",))

        missing = []
        self._require_equal(missing, evidence, "layer", layer)
        self._require_equal(missing, evidence, "case_id", record.tc_id)
        self._require_equal(missing, evidence, "target_id", record.target_id)
        self._require_equal(missing, evidence, "mission_id", mission_id)
        self._require_equal(missing, evidence, "attempt_id", record.attempt_id)
        self._require_equal(missing, evidence, "worker_id", record.worker_id)
        self._require_equal(missing, evidence, "session_id", execution_session_id(record.worker_id))

        if str(evidence.get("status", "")).upper() not in {"PASS", "EXECUTED_PASS"}:
            missing.append("status=PASS")
        for field in ("started_at", "finished_at"):
            if not str(evidence.get(field, "")).strip():
                missing.append(field)
        if not isinstance(evidence.get("preconditions"), (list, tuple)):
            missing.append("preconditions")
        if not isinstance(evidence.get("test_data"), Mapping):
            missing.append("test_data")
        for field in ("steps", "expected_results", "actual_results"):
            if not self._nonempty_sequence(evidence.get(field)):
                missing.append("%s_nonempty" % field)

        record_refs = {str(ref) for ref in record.evidence_refs if str(ref)}
        layer_refs = self._refs(evidence.get("evidence_refs"))
        if not layer_refs:
            missing.append("evidence_refs")
        elif not self._refs_are_current(
            layer_refs,
            record_refs=record_refs,
            mission_id=mission_id,
            attempt_id=record.attempt_id,
        ):
            missing.append("evidence_refs_current_execution")

        self._verify_assertions(
            missing,
            evidence.get("assertions"),
            record_refs=record_refs,
            mission_id=mission_id,
            attempt_id=record.attempt_id,
        )
        self._verify_receipt(missing, evidence.get("execution_receipt"), record)

        if layer == "L4":
            self._verify_l4_payload(missing, evidence, record_refs, mission_id, record.attempt_id)
        elif layer == "L5":
            self._verify_l5_e2e_payload(missing, evidence, record_refs, mission_id, record.attempt_id)
        elif layer == "L6":
            self._verify_l6_performance_payload(missing, evidence, record_refs, mission_id, record.attempt_id)
        else:
            self._verify_l7_security_payload(missing, evidence, record_refs, mission_id, record.attempt_id)

        return self._result("%s_EVIDENCE_CONTRACT_COMPLETE" % layer, missing)

    def _verify_l4_payload(
        self,
        missing,
        evidence: Mapping[str, Any],
        record_refs: set,
        mission_id: str,
        attempt_id: str,
    ) -> None:
        browser = evidence.get("browser")
        if not isinstance(browser, dict):
            missing.append("browser")
            return
        for field in ("page_open", "actions", "state_reads"):
            if not self._nonempty_sequence(browser.get(field)):
                missing.append("browser.%s" % field)

        types = {str(item).lower() for item in self._sequence(browser.get("evidence_types"))}
        artifacts = browser.get("artifacts")
        if not isinstance(artifacts, Mapping):
            missing.append("browser.artifacts")
            artifacts = {}
        for required in self.L4_REQUIRED_ARTIFACTS:
            if required not in types:
                missing.append("browser.evidence_type:%s" % required)
            refs = self._refs(artifacts.get(required))
            if not refs:
                missing.append("browser.artifacts.%s" % required)
            elif not self._refs_are_current(refs, record_refs=record_refs, mission_id=mission_id, attempt_id=attempt_id):
                missing.append("browser.artifacts.%s_current_execution" % required)

        browser_refs = self._refs(browser.get("evidence_refs"))
        if not browser_refs:
            missing.append("browser.evidence_refs")
        elif not self._refs_are_current(browser_refs, record_refs=record_refs, mission_id=mission_id, attempt_id=attempt_id):
            missing.append("browser.evidence_refs_current_execution")

        auth = evidence.get("auth")
        if isinstance(auth, dict) and bool(auth.get("required_4a")):
            method = str(auth.get("method", "")).strip().lower()
            if method not in {"foura_auth.py", "4a_skill", "4a skill"}:
                missing.append("auth.method=foura_auth.py_or_4A_skill")
            if auth.get("fresh_login") is not True:
                missing.append("auth.fresh_login=true")
            if auth.get("historical_cookie_fallback") is not False:
                missing.append("auth.historical_cookie_fallback=false")
            if auth.get("expiry_relogin_supported") is not True:
                missing.append("auth.expiry_relogin_supported=true")
            auth_refs = self._refs(auth.get("evidence_refs"))
            if not auth_refs:
                missing.append("auth.evidence_refs")
            elif not self._refs_are_current(auth_refs, record_refs=record_refs, mission_id=mission_id, attempt_id=attempt_id):
                missing.append("auth.evidence_refs_current_execution")

    def _verify_l5_e2e_payload(
        self,
        missing,
        evidence: Mapping[str, Any],
        record_refs: set,
        mission_id: str,
        attempt_id: str,
    ) -> None:
        if evidence.get("real_runtime_execution") is not True:
            missing.append("real_runtime_execution=true")
        if evidence.get("E2E_VERIFIED_REQUIRES_REAL_RUNTIME_EXECUTION") is not True:
            missing.append("E2E_VERIFIED_REQUIRES_REAL_RUNTIME_EXECUTION=true")
        chain = evidence.get("e2e_chain")
        if not isinstance(chain, dict):
            missing.append("e2e_chain")
            return
        for segment in self.E2E_REQUIRED_SEGMENTS:
            value = chain.get(segment)
            if value in (None, "", [], {}, ()):
                missing.append("e2e_chain.%s" % segment)
        refs = self._refs(chain.get("evidence_refs"))
        if not refs:
            missing.append("e2e_chain.evidence_refs")
        elif not self._refs_are_current(refs, record_refs=record_refs, mission_id=mission_id, attempt_id=attempt_id):
            missing.append("e2e_chain.evidence_refs_current_execution")

    def _verify_l6_performance_payload(
        self,
        missing,
        evidence: Mapping[str, Any],
        record_refs: set,
        mission_id: str,
        attempt_id: str,
    ) -> None:
        performance = evidence.get("performance")
        if not isinstance(performance, dict):
            missing.append("performance")
            return
        if str(performance.get("tool_name", "")).strip().lower() != "k6":
            missing.append("performance.tool_name=k6")
        if not str(performance.get("tool_version", "")).strip():
            missing.append("performance.tool_version")
        if not str(performance.get("script_sha256", "")).strip():
            missing.append("performance.script_sha256")
        if performance.get("exit_code") != 0:
            missing.append("performance.exit_code=0")
        for field in self.L6_REQUIRED_REFS:
            self._require_current_single_ref(
                missing,
                performance,
                field,
                prefix="performance",
                record_refs=record_refs,
                mission_id=mission_id,
                attempt_id=attempt_id,
            )
        refs = self._refs(performance.get("evidence_refs"))
        if not refs:
            missing.append("performance.evidence_refs")
        elif not self._refs_are_current(refs, record_refs=record_refs, mission_id=mission_id, attempt_id=attempt_id):
            missing.append("performance.evidence_refs_current_execution")

    def _verify_l7_security_payload(
        self,
        missing,
        evidence: Mapping[str, Any],
        record_refs: set,
        mission_id: str,
        attempt_id: str,
    ) -> None:
        security = evidence.get("security")
        if not isinstance(security, dict):
            missing.append("security")
            return
        if str(security.get("tool_name", "")).strip().lower() != "zap":
            missing.append("security.tool_name=zap")
        if not str(security.get("tool_version", "")).strip():
            missing.append("security.tool_version")
        if not str(security.get("target_ref", "")).strip():
            missing.append("security.target_ref")
        if security.get("exit_code") != 0:
            missing.append("security.exit_code=0")
        for field in self.L7_REQUIRED_REFS:
            self._require_current_single_ref(
                missing,
                security,
                field,
                prefix="security",
                record_refs=record_refs,
                mission_id=mission_id,
                attempt_id=attempt_id,
            )
        refs = self._refs(security.get("evidence_refs"))
        if not refs:
            missing.append("security.evidence_refs")
        elif not self._refs_are_current(refs, record_refs=record_refs, mission_id=mission_id, attempt_id=attempt_id):
            missing.append("security.evidence_refs_current_execution")

    @classmethod
    def _require_current_single_ref(
        cls,
        missing,
        payload: Mapping[str, Any],
        field: str,
        *,
        prefix: str,
        record_refs: set,
        mission_id: str,
        attempt_id: str,
    ) -> None:
        ref = str(payload.get(field, "")).strip()
        if not ref:
            missing.append("%s.%s" % (prefix, field))
            return
        if not cls._refs_are_current({ref}, record_refs=record_refs, mission_id=mission_id, attempt_id=attempt_id):
            missing.append("%s.%s_current_execution" % (prefix, field))

    @classmethod
    def _verify_assertions(
        cls,
        missing,
        assertions: Any,
        *,
        record_refs: set,
        mission_id: str,
        attempt_id: str,
    ) -> None:
        if not cls._nonempty_sequence(assertions):
            missing.append("assertions")
            return
        for index, assertion in enumerate(assertions):
            prefix = "assertions[%d]" % index
            if not isinstance(assertion, dict):
                missing.append(prefix)
                continue
            if not str(assertion.get("assertion_id", "")).strip():
                missing.append("%s.assertion_id" % prefix)
            if "expected" not in assertion:
                missing.append("%s.expected" % prefix)
            if "actual" not in assertion:
                missing.append("%s.actual" % prefix)
            if str(assertion.get("result", "")).upper() != "PASS":
                missing.append("%s.result=PASS" % prefix)
            refs = cls._refs(assertion.get("evidence_refs"))
            if not refs:
                missing.append("%s.evidence_refs" % prefix)
            elif not cls._refs_are_current(refs, record_refs=record_refs, mission_id=mission_id, attempt_id=attempt_id):
                missing.append("%s.evidence_refs_current_execution" % prefix)

    @staticmethod
    def _verify_receipt(missing, receipt: Any, record: ExecutionRecord) -> None:
        if not isinstance(receipt, dict):
            missing.append("execution_receipt")
            return
        expected = {"case_id": record.tc_id, "attempt_id": record.attempt_id, "target_id": record.target_id}
        for field, value in expected.items():
            if str(receipt.get(field, "")) != str(value):
                missing.append("execution_receipt.%s" % field)
        if not str(receipt.get("receipt_id", "")).strip():
            missing.append("execution_receipt.receipt_id")
        if str(receipt.get("status", "")).upper() not in {"PASS", "EXECUTED_PASS"}:
            missing.append("execution_receipt.status=PASS")

    @staticmethod
    def _require_equal(missing, evidence: Mapping[str, Any], field: str, expected: Any) -> None:
        if str(evidence.get(field, "")) != str(expected):
            missing.append(field)

    @staticmethod
    def _sequence(value: Any) -> Sequence[Any]:
        return value if isinstance(value, (list, tuple)) else ()

    @classmethod
    def _nonempty_sequence(cls, value: Any) -> bool:
        return bool(cls._sequence(value))

    @staticmethod
    def _refs(value: Any) -> set:
        if not isinstance(value, (list, tuple, set)):
            return set()
        return {str(item) for item in value if str(item)}

    @classmethod
    def _refs_are_current(
        cls,
        refs: set,
        *,
        record_refs: set,
        mission_id: str,
        attempt_id: str,
    ) -> bool:
        for ref in refs:
            if ref in record_refs:
                # A caller cannot satisfy the gate with only a self-claimed
                # canonical runtime Evidence id; file-backed proof must exist.
                if ref.startswith("EVD-EXEC-RUNTIME-"):
                    return False
                continue
            if not ref.startswith("file://"):
                return False
            path = Path(ref[len("file://"):]).expanduser().resolve()
            if not path.is_file():
                return False
            if cls._canonical_runtime_evidence_id(mission_id, attempt_id, ref) not in record_refs:
                return False
        return True

    @staticmethod
    def _canonical_runtime_evidence_id(mission_id: str, attempt_id: str, raw_ref: str) -> str:
        digest = ""
        if raw_ref.startswith("file://"):
            path = Path(raw_ref[len("file://"):]).expanduser().resolve()
            if path.is_file():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
        payload = "\x1f".join(str(part) for part in (mission_id, attempt_id, raw_ref, digest)).encode("utf-8")
        return "EVD-EXEC-RUNTIME-%s" % hashlib.sha256(payload).hexdigest()[:20]

    @staticmethod
    def _result(success_reason: str, missing: Iterable[str]) -> LayerEvidenceResult:
        normalized = tuple(sorted(set(str(item) for item in missing)))
        if normalized:
            return LayerEvidenceResult(False, "EVIDENCE_INCOMPLETE", normalized)
        return LayerEvidenceResult(True, success_reason, ())

    # Typed compatibility helpers preserve their historical public API while
    # following the canonical semantics represented by their type names.
    def verify_l4(self, evidence: L4UiEvidence) -> LayerEvidenceResult:
        missing = []
        if not evidence.trace_ref:
            missing.append("trace")
        if not evidence.har_ref:
            missing.append("network")
        if not evidence.screenshot_refs:
            missing.append("screenshots")
        if not evidence.oracle_ref:
            missing.append("oracle")
        if not evidence.actual_result_ref:
            missing.append("actual_result")
        return self._result("L4_COMPAT_EVIDENCE_COMPLETE", missing)

    def verify_l5(self, evidence: L5E2EEvidence) -> LayerEvidenceResult:
        missing = []
        if not evidence.stages:
            missing.append("stages")
        if not evidence.runtime_refs:
            missing.append("runtime_refs")
        if not evidence.oracle_ref:
            missing.append("oracle")
        if not evidence.actual_result_ref:
            missing.append("actual_result")
        return self._result("L5_COMPAT_EVIDENCE_COMPLETE", missing)

    def verify_l6(self, evidence: L6K6Evidence) -> LayerEvidenceResult:
        missing = []
        if str(evidence.tool_name).lower() != "k6":
            missing.append("tool_name=k6")
        for field in ("tool_version", "script_sha256", "scenario_ref", "threshold_ref", "summary_ref", "stdout_ref"):
            if not str(getattr(evidence, field)).strip():
                missing.append(field)
        if evidence.exit_code != 0:
            missing.append("exit_code=0")
        return self._result("L6_COMPAT_EVIDENCE_COMPLETE", missing)

    def verify_l7(self, evidence: L7ZapEvidence) -> LayerEvidenceResult:
        missing = []
        if str(evidence.tool_name).lower() != "zap":
            missing.append("tool_name=zap")
        for field in ("tool_version", "target_ref", "scan_config_ref", "spider_ref", "passive_scan_ref", "active_scan_ref", "html_report_ref", "json_report_ref"):
            if not str(getattr(evidence, field)).strip():
                missing.append(field)
        if evidence.exit_code != 0:
            missing.append("exit_code=0")
        return self._result("L7_COMPAT_EVIDENCE_COMPLETE", missing)
