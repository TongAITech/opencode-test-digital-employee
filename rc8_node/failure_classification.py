"""Evidence-first failure ownership classification for RC8 L1 execution.

The classifier consumes only fresh JUnit XML from the current Maven attempt.
It automatically assigns ownership only for narrow, mechanically provable
runtime categories. Assertion mismatches and arbitrary application exceptions
remain UNKNOWN and require semantic adjudication; they are never promoted to a
PRODUCT defect merely because a test failed.
"""
from __future__ import annotations

import hashlib
import json
import os
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from rc8_runtime.governance import FailureOwnership


class FailureClassificationError(RuntimeError):
    pass


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _normalize(value: Optional[str]) -> str:
    return (value or "").strip()


@dataclass(frozen=True)
class FailureFact:
    testcase_ref: str
    outcome: str
    exception_type: str
    message: str
    detail_excerpt: str
    detail_sha256: str
    ownership: FailureOwnership
    reason_code: str
    confidence: str
    semantic_review_required: bool


@dataclass(frozen=True)
class FailureClassificationResult:
    facts: Tuple[FailureFact, ...]
    primary_ownership: FailureOwnership
    ownership_counts: Dict[str, int]
    result_path: str
    sha256: str
    classification: str = "JUNIT_FAILURE_OWNERSHIP_COLLECTED"

    @property
    def semantic_review_required(self) -> bool:
        return any(fact.semantic_review_required for fact in self.facts)


_STRONG_RULES: Tuple[Tuple[FailureOwnership, str, Tuple[str, ...]], ...] = (
    (
        FailureOwnership.DEPENDENCY,
        "DEPENDENCY_LINKAGE_FAILURE",
        (
            "classnotfoundexception",
            "noclassdeffounderror",
            "nosuchmethoderror",
            "nosuchfielderror",
            "unsupportedclassversionerror",
        ),
    ),
    (
        FailureOwnership.ENVIRONMENT,
        "EXECUTION_ENVIRONMENT_FAILURE",
        (
            "connection refused",
            "unknownhostexception",
            "no space left on device",
            "accessdeniedexception",
            "address already in use",
            "bindexception",
            "cannot assign requested address",
            "network is unreachable",
            "host is unreachable",
        ),
    ),
    (
        FailureOwnership.TOOL,
        "TEST_TOOL_RUNTIME_FAILURE",
        (
            "org.apache.maven.surefire.booter.surefirebooterforkexception",
            "forked vm terminated without properly saying goodbye",
            "surefire fork",
            "junit platform launcher",
        ),
    ),
)


def _classify(exception_type: str, message: str, detail: str) -> Tuple[FailureOwnership, str, str, bool]:
    haystack = "\n".join((exception_type, message, detail)).lower()
    for ownership, reason, markers in _STRONG_RULES:
        if any(marker in haystack for marker in markers):
            return ownership, reason, "HIGH", False

    assertion_markers = (
        "assertionerror",
        "org.opentest4j.assertionfailederror",
        "expected:",
        "expected <",
        "but was",
    )
    if any(marker in haystack for marker in assertion_markers):
        return (
            FailureOwnership.UNKNOWN,
            "ASSERTION_MISMATCH_REQUIRES_SEMANTIC_ADJUDICATION",
            "UNRESOLVED",
            True,
        )

    return (
        FailureOwnership.UNKNOWN,
        "UNCLASSIFIED_TEST_FAILURE_REQUIRES_SEMANTIC_ADJUDICATION",
        "UNRESOLVED",
        True,
    )


def _testcase_ref(classname: str, name: str) -> str:
    left = classname.strip() or "<unknown-class>"
    right = name.strip() or "<unknown-test>"
    return "%s#%s" % (left, right)


class JUnitFailureClassifier:
    capability_id = "junit-failure-classification"

    def __init__(self, evidence_dir: str) -> None:
        self.evidence_dir = Path(evidence_dir)

    @staticmethod
    def _facts_from_report(path: Path) -> List[FailureFact]:
        try:
            root = ET.parse(str(path)).getroot()
        except (OSError, ET.ParseError) as exc:
            raise FailureClassificationError("JUNIT_FAILURE_XML_INVALID:%s" % path.name) from exc

        facts: List[FailureFact] = []
        for testcase in root.iter():
            if _local_name(testcase.tag) != "testcase":
                continue
            classname = _normalize(testcase.attrib.get("classname"))
            name = _normalize(testcase.attrib.get("name"))
            ref = _testcase_ref(classname, name)
            for child in testcase:
                outcome = _local_name(child.tag)
                if outcome not in {"failure", "error"}:
                    continue
                exception_type = _normalize(child.attrib.get("type"))
                message = _normalize(child.attrib.get("message"))
                detail = _normalize(child.text)
                ownership, reason, confidence, review = _classify(exception_type, message, detail)
                facts.append(
                    FailureFact(
                        testcase_ref=ref,
                        outcome=outcome.upper(),
                        exception_type=exception_type,
                        message=message,
                        detail_excerpt=detail[:2000],
                        detail_sha256=_sha256_text(detail),
                        ownership=ownership,
                        reason_code=reason,
                        confidence=confidence,
                        semantic_review_required=review,
                    )
                )
        return facts

    @staticmethod
    def _primary(facts: Sequence[FailureFact]) -> FailureOwnership:
        if not facts:
            return FailureOwnership.UNKNOWN
        values = {fact.ownership for fact in facts}
        if len(values) == 1:
            return next(iter(values))
        return FailureOwnership.UNKNOWN

    def classify(self, reports: Iterable[str]) -> FailureClassificationResult:
        paths = [Path(value) for value in reports]
        if not paths:
            raise FailureClassificationError("JUNIT_FAILURE_REPORTS_REQUIRED")
        facts: List[FailureFact] = []
        for path in paths:
            if not path.is_file():
                raise FailureClassificationError("JUNIT_FAILURE_REPORT_MISSING:%s" % path)
            facts.extend(self._facts_from_report(path))

        if not facts:
            # The suite may report a failure count without a usable testcase
            # child. Preserve that uncertainty rather than inventing ownership.
            facts.append(
                FailureFact(
                    testcase_ref="junit-report:<unresolved>",
                    outcome="UNKNOWN_DETAIL",
                    exception_type="",
                    message="JUnit reported a failing attempt without testcase-level failure detail",
                    detail_excerpt="",
                    detail_sha256=_sha256_text(""),
                    ownership=FailureOwnership.UNKNOWN,
                    reason_code="JUNIT_FAILURE_DETAIL_MISSING",
                    confidence="UNRESOLVED",
                    semantic_review_required=True,
                )
            )

        counts: Dict[str, int] = {}
        for fact in facts:
            counts[fact.ownership.value] = counts.get(fact.ownership.value, 0) + 1
        primary = self._primary(facts)

        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "capability_id": self.capability_id,
            "classification": "JUNIT_FAILURE_OWNERSHIP_COLLECTED",
            "primary_ownership": primary.value,
            "ownership_counts": counts,
            "semantic_review_required": any(fact.semantic_review_required for fact in facts),
            "facts": [
                dict(asdict(fact), ownership=fact.ownership.value)
                for fact in facts
            ],
            "truth_note": (
                "Only fresh JUnit failure/error elements from the current attempt are classified; "
                "UNKNOWN is preserved whenever product/script/oracle ownership cannot be proven mechanically"
            ),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        result_path = self.evidence_dir / "junit-failure-classification.json"
        temp = result_path.with_suffix(".json.tmp")
        temp.write_bytes(encoded)
        os.replace(str(temp), str(result_path))
        return FailureClassificationResult(
            facts=tuple(facts),
            primary_ownership=primary,
            ownership_counts=counts,
            result_path=str(result_path),
            sha256=hashlib.sha256(encoded).hexdigest(),
        )
