"""Deterministic L4-L7 execution evidence contracts for RC7.1.

The presence of an evidence reference is not enough.  This module validates
that each layer carries the concrete runtime artifacts required by the field
acceptance contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple


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
    REQUIRED_L5_STAGES = (
        "IDENTITY",
        "PRECONDITION",
        "TEST_DATA",
        "BUSINESS_ENTRY",
        "SERVICE_CHAIN",
        "PERSISTENCE",
        "STATE_TRANSITION",
        "SIDE_EFFECT",
        "FINAL_BUSINESS_RESULT",
        "REVERSE_VERIFICATION",
    )

    def verify_l4(self, evidence: L4UiEvidence) -> LayerEvidenceResult:
        missing = []
        if not evidence.video_ref.lower().endswith((".webm", ".mp4")):
            missing.append("video")
        if not evidence.trace_ref.lower().endswith(".zip"):
            missing.append("trace")
        if not evidence.har_ref.lower().endswith(".har"):
            missing.append("har")
        if not evidence.screenshot_refs:
            missing.append("screenshots")
        if not evidence.oracle_ref:
            missing.append("oracle")
        if not evidence.actual_result_ref:
            missing.append("actual_result")
        return self._result("L4_UI_EVIDENCE_COMPLETE", missing)

    def verify_l5(self, evidence: L5E2EEvidence) -> LayerEvidenceResult:
        stages = {str(item).upper() for item in evidence.stages}
        missing = [stage for stage in self.REQUIRED_L5_STAGES if stage not in stages]
        if not evidence.runtime_refs:
            missing.append("runtime_refs")
        if not evidence.oracle_ref:
            missing.append("oracle")
        if not evidence.actual_result_ref:
            missing.append("actual_result")
        return self._result("L5_FULL_E2E_COMPLETE", missing)

    def verify_l6(self, evidence: L6K6Evidence) -> LayerEvidenceResult:
        missing = []
        if evidence.tool_name.strip().lower() != "k6":
            missing.append("tool=k6")
        if not evidence.tool_version:
            missing.append("tool_version")
        if len(evidence.script_sha256) != 64:
            missing.append("script_sha256")
        if not evidence.scenario_ref:
            missing.append("scenario")
        if not evidence.threshold_ref:
            missing.append("threshold")
        if not evidence.summary_ref:
            missing.append("summary")
        if not evidence.stdout_ref:
            missing.append("stdout")
        if evidence.exit_code != 0:
            missing.append("exit_code=0")
        return self._result("L6_K6_EVIDENCE_COMPLETE", missing)

    def verify_l7(self, evidence: L7ZapEvidence) -> LayerEvidenceResult:
        missing = []
        if evidence.tool_name.strip().lower() not in {"zap", "owasp-zap", "owasp zap"}:
            missing.append("tool=zap")
        if not evidence.tool_version:
            missing.append("tool_version")
        for field_name, value in (
            ("target", evidence.target_ref),
            ("scan_config", evidence.scan_config_ref),
            ("spider", evidence.spider_ref),
            ("passive_scan", evidence.passive_scan_ref),
            ("active_scan", evidence.active_scan_ref),
            ("html_report", evidence.html_report_ref),
            ("json_report", evidence.json_report_ref),
        ):
            if not value:
                missing.append(field_name)
        if evidence.exit_code != 0:
            missing.append("exit_code=0")
        return self._result("L7_ZAP_EVIDENCE_COMPLETE", missing)

    @staticmethod
    def _result(success_reason: str, missing) -> LayerEvidenceResult:
        normalized = tuple(sorted(set(str(item) for item in missing)))
        if normalized:
            return LayerEvidenceResult(False, "EVIDENCE_INCOMPLETE", normalized)
        return LayerEvidenceResult(True, success_reason, ())
