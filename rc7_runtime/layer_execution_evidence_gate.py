"""RC7.1 deterministic L4-L7 production evidence contract.

This gate is deliberately independent from model judgement. A generic
ExecutionRecord may be integrity-valid, but L4-L7 are not allowed to become a
terminal PASS until the layer-specific runtime proof is carried by the current
execution record.

RC7.1 layer semantics:
* L4 - real browser/UI execution, including governed fresh 4A authentication
  when the case requires 4A.
* L5 - real API execution using a route captured from controlled browser
  network traffic. Endpoint guessing is never evidence.
* L6 - declared execution capability/tool proof. Missing capability is a
  blocker/human-required outcome, never a degraded PASS.
* L7 - real cross-layer E2E execution. E2E verification requires real runtime
  execution and a complete entry -> business-result -> oracle chain.

For production service records, layer evidence must point to current-run
file-backed proof. The service hashes those files into canonical R1 Evidence
IDs. A script-emitted URI or a self-claimed canonical ID is not enough to prove
that screenshot/network/API/capability/E2E evidence actually exists.
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


# Compatibility DTOs for field adapters that imported the first RC7.1 draft.
# Production verification is performed by verify_record().
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
    E2E_REQUIRED_SEGMENTS = (
        "entry",
        "frontend",
        "api",
        "service",
        "data_or_state",
        "business_result",
        "oracle",
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
            self._verify_l5_payload(missing, evidence, record_refs, mission_id, record.attempt_id)
        elif layer == "L6":
            self._verify_l6_payload(missing, evidence, record_refs, mission_id, record.attempt_id)
        else:
            self._verify_l7_payload(missing, evidence, record_refs, mission_id, record.attempt_id)

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
        for required in ("screenshot", "dom", "trace", "network"):
            if required not in types:
                missing.append("browser.evidence_type:%s" % required)
        browser_refs = self._refs(browser.get("evidence_refs"))
        if not browser_refs:
            missing.append("browser.evidence_refs")
        elif not self._refs_are_current(
            browser_refs,
            record_refs=record_refs,
            mission_id=mission_id,
            attempt_id=attempt_id,
        ):
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

    def _verify_l5_payload(
        self,
        missing,
        evidence: Mapping[str, Any],
        record_refs: set,
        mission_id: str,
        attempt_id: str,
    ) -> None:
        calls = evidence.get("api_calls")
        if not self._nonempty_sequence(calls):
            missing.append("api_calls")
            return
        for index, call in enumerate(calls):
            prefix = "api_calls[%d]" % index
            if not isinstance(call, dict):
                missing.append(prefix)
                continue
            for field in ("url", "method", "request", "response", "status_code", "business_code"):
                if field not in call or call.get(field) is None or call.get(field) == "":
                    missing.append("%s.%s" % (prefix, field))
            if str(call.get("route_source", "")).lower() != "browser_network_capture":
                missing.append("%s.route_source=browser_network_capture" % prefix)
            if call.get("endpoint_guessed") is not False:
                missing.append("%s.endpoint_guessed=false" % prefix)
            refs = self._refs(call.get("evidence_refs"))
            if not refs:
                missing.append("%s.evidence_refs" % prefix)
            elif not self._refs_are_current(
                refs,
                record_refs=record_refs,
                mission_id=mission_id,
                attempt_id=attempt_id,
            ):
                missing.append("%s.evidence_refs_current_execution" % prefix)

    def _verify_l6_payload(
        self,
        missing,
        evidence: Mapping[str, Any],
        record_refs: set,
        mission_id: str,
        attempt_id: str,
    ) -> None:
        capability = evidence.get("capability")
        if not isinstance(capability, dict):
            missing.append("capability")
            return
        status = str(capability.get("status", "")).upper()
        if status != "AVAILABLE":
            if status in {"BLOCKED_ENVIRONMENT", "HUMAN_REQUIRED"}:
                missing.append("capability.status_not_passable:%s" % status)
            else:
                missing.append("capability.status=AVAILABLE")
        if not str(capability.get("tool_name", "")).strip():
            missing.append("capability.tool_name")
        refs = self._refs(capability.get("evidence_refs"))
        if not refs:
            missing.append("capability.evidence_refs")
        elif not self._refs_are_current(
            refs,
            record_refs=record_refs,
            mission_id=mission_id,
            attempt_id=attempt_id,
        ):
            missing.append("capability.evidence_refs_current_execution")

    def _verify_l7_payload(
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
        elif not self._refs_are_current(
            refs,
            record_refs=record_refs,
            mission_id=mission_id,
            attempt_id=attempt_id,
        ):
            missing.append("e2e_chain.evidence_refs_current_execution")

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
            elif not cls._refs_are_current(
                refs,
                record_refs=record_refs,
                mission_id=mission_id,
                attempt_id=attempt_id,
            ):
                missing.append("%s.evidence_refs_current_execution" % prefix)

    @staticmethod
    def _verify_receipt(missing, receipt: Any, record: ExecutionRecord) -> None:
        if not isinstance(receipt, dict):
            missing.append("execution_receipt")
            return
        expected = {
            "case_id": record.tc_id,
            "attempt_id": record.attempt_id,
            "target_id": record.target_id,
        }
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
        if isinstance(value, (list, tuple)):
            return value
        return ()

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
            # Direct non-runtime evidence IDs are retained for compatibility
            # with deterministic unit/conformance adapters. Production formal
            # execution records contain EVD-EXEC-RUNTIME-* IDs, so a layer
            # payload cannot self-claim one of those IDs as proof.
            if ref in record_refs:
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
        payload = "\x1f".join(
            str(part) for part in (mission_id, attempt_id, raw_ref, digest)
        ).encode("utf-8")
        return "EVD-EXEC-RUNTIME-%s" % hashlib.sha256(payload).hexdigest()[:20]

    @staticmethod
    def _result(success_reason: str, missing: Iterable[str]) -> LayerEvidenceResult:
        normalized = tuple(sorted(set(str(item) for item in missing)))
        if normalized:
            return LayerEvidenceResult(False, "EVIDENCE_INCOMPLETE", normalized)
        return LayerEvidenceResult(True, success_reason, ())

    # Legacy validation entry points retained for compatibility. They no longer
    # define RC7.1 production semantics and are not used by the runtime.
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
        if not evidence.runtime_refs:
            missing.append("runtime_refs")
        if not evidence.oracle_ref:
            missing.append("oracle")
        if not evidence.actual_result_ref:
            missing.append("actual_result")
        return self._result("L5_COMPAT_EVIDENCE_COMPLETE", missing)

    def verify_l6(self, evidence: L6K6Evidence) -> LayerEvidenceResult:
        missing = []
        if not evidence.tool_name:
            missing.append("tool_name")
        if evidence.exit_code != 0:
            missing.append("exit_code=0")
        return self._result("L6_COMPAT_EVIDENCE_COMPLETE", missing)

    def verify_l7(self, evidence: L7ZapEvidence) -> LayerEvidenceResult:
        missing = []
        if not evidence.tool_name:
            missing.append("tool_name")
        if evidence.exit_code != 0:
            missing.append("exit_code=0")
        return self._result("L7_COMPAT_EVIDENCE_COMPLETE", missing)
