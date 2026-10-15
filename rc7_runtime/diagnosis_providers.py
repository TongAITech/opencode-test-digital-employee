from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class DiagnosticSignal:
    provider: str
    failure_class: str
    confidence: float
    rationale: str
    matched_pattern: str
    evidence_excerpt: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "provider": self.provider,
            "failure_class": self.failure_class,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "matched_pattern": self.matched_pattern,
            "evidence_excerpt": self.evidence_excerpt,
        }


class LogDiagnosisProvider:
    name = "generic"
    PATTERNS: Tuple[Tuple[str, str, float, str], ...] = ()

    def analyze(self, text: str) -> Tuple[DiagnosticSignal, ...]:
        raw = str(text or "")
        signals: List[DiagnosticSignal] = []
        for expression, failure_class, confidence, rationale in self.PATTERNS:
            match = re.search(expression, raw, re.IGNORECASE | re.MULTILINE)
            if not match:
                continue
            start = max(0, match.start() - 120)
            end = min(len(raw), match.end() + 220)
            excerpt = re.sub(r"\s+", " ", raw[start:end]).strip()
            signals.append(DiagnosticSignal(
                provider=self.name,
                failure_class=failure_class,
                confidence=float(confidence),
                rationale=rationale,
                matched_pattern=expression,
                evidence_excerpt=excerpt[:500],
            ))
        return tuple(signals)


class MavenDiagnosisProvider(LogDiagnosisProvider):
    name = "maven"
    PATTERNS = (
        (r"could not resolve dependencies|failure to find .* in .* repository|non-resolvable parent pom",
         "DEPENDENCY", 0.98, "Maven dependency resolution failed"),
        (r"compilation failure|cannot find symbol|package .* does not exist",
         "SCRIPT", 0.92, "Compilation or generated-script source is invalid"),
        (r"there are test failures|tests run: .* failures: [1-9]",
         "SPEC", 0.72, "Tests executed and assertion/spec failures were reported"),
        (r"connection timed out|read timed out|connection refused",
         "ENVIRONMENT", 0.86, "Build/runtime dependency endpoint is unavailable"),
    )


class JUnitDiagnosisProvider(LogDiagnosisProvider):
    name = "junit"
    PATTERNS = (
        (r"assertion(?:failed|error)|expected:.*but was:|org\.opentest4j\.assertionfailederror",
         "SPEC", 0.82, "JUnit assertion failed; ownership still requires oracle/spec verification"),
        (r"classnotfoundexception|noclassdeffounderror",
         "DEPENDENCY", 0.95, "Required test/runtime class is missing"),
        (r"beforeeach|beforeall|setup.*failed",
         "PRECONDITION", 0.80, "JUnit setup/precondition failed"),
    )


class PytestDiagnosisProvider(LogDiagnosisProvider):
    name = "pytest"
    PATTERNS = (
        (r"fixture .* not found|fixturelookuperror",
         "PRECONDITION", 0.94, "Pytest fixture/precondition is unavailable"),
        (r"modulenotfounderror|importerror:",
         "DEPENDENCY", 0.94, "Python runtime dependency is unavailable"),
        (r"assert .*|assertionerror",
         "SPEC", 0.80, "Pytest assertion failed; ownership still requires competing-cause exclusion"),
        (r"timeout(?:error)?|timed out",
         "TRANSIENT", 0.62, "Pytest timed out and needs bounded retry/environment evidence"),
    )


class PlaywrightDiagnosisProvider(LogDiagnosisProvider):
    name = "playwright"
    PATTERNS = (
        (r"401 unauthorized|403 forbidden|login|authentication|session expired",
         "AUTH", 0.90, "Browser flow is blocked by authentication/session state"),
        (r"404 not found|net::err_name_not_resolved|cannot (?:get|post|put|delete) /",
         "ROUTE", 0.88, "Observed browser/network route cannot be resolved"),
        (r"strict mode violation|locator .* resolved to .* elements|element is not attached",
         "SCRIPT", 0.91, "Playwright locator/script binding is invalid"),
        (r"waiting for .* exceeded|timeout .* locator|page\.goto: timeout",
         "TOOL", 0.64, "Browser automation timed out; additional network/environment evidence is required"),
        (r"browser has been closed|target page, context or browser has been closed",
         "TOOL", 0.90, "Controlled browser process/context terminated unexpectedly"),
    )


class ApiDiagnosisProvider(LogDiagnosisProvider):
    name = "api"
    PATTERNS = (
        (r"\b401\b|\b403\b|unauthorized|forbidden",
         "AUTH", 0.94, "HTTP authentication/authorization rejected the request"),
        (r"\b404\b|no route|route not found|endpoint not found",
         "ROUTE", 0.92, "HTTP route binding is missing or incorrect"),
        (r"connection refused|connect timeout|read timeout|gateway timeout|\b504\b",
         "ENVIRONMENT", 0.84, "API dependency or target environment is unavailable"),
        (r"\b429\b|too many requests|rate limit",
         "TRANSIENT", 0.90, "API request is throttled"),
        (r"\b502\b|\b503\b|bad gateway|service unavailable",
         "DEPENDENCY", 0.82, "Upstream/downstream service dependency is unavailable"),
        (r"\b500\b|internal server error",
         "UNKNOWN", 0.55, "Server-side failure observed; CAT/RCA is required before PRODUCT ownership"),
    )


class DatabaseDiagnosisProvider(LogDiagnosisProvider):
    name = "database"
    PATTERNS = (
        (r"access denied|authentication failed|invalid username|invalid password",
         "AUTH", 0.94, "Database authentication failed"),
        (r"deadlock|lock wait timeout",
         "TRANSIENT", 0.78, "Database concurrency failure may be retryable under policy"),
        (r"connection refused|connection reset|communications link failure|connection timed out",
         "ENVIRONMENT", 0.90, "Database endpoint is unavailable"),
        (r"table .* doesn't exist|unknown column|invalid identifier",
         "SPEC", 0.78, "SQL/schema expectation does not match the target"),
        (r"duplicate entry|unique constraint|constraint violation",
         "DATA", 0.84, "Prepared test data violates a database constraint"),
    )


DEFAULT_PROVIDERS = (
    MavenDiagnosisProvider(),
    JUnitDiagnosisProvider(),
    PytestDiagnosisProvider(),
    PlaywrightDiagnosisProvider(),
    ApiDiagnosisProvider(),
    DatabaseDiagnosisProvider(),
)


class MultiToolLogDiagnoser:
    """Aggregate deterministic signals without prematurely declaring PRODUCT."""

    def __init__(self, providers=DEFAULT_PROVIDERS) -> None:
        self.providers = tuple(providers)

    def analyze(self, text: str, provider_names: Optional[Iterable[str]] = None) -> Dict[str, object]:
        selected = {str(name).lower() for name in provider_names or ()}
        signals: List[DiagnosticSignal] = []
        for provider in self.providers:
            if selected and provider.name.lower() not in selected:
                continue
            signals.extend(provider.analyze(text))
        signals.sort(key=lambda item: (-item.confidence, item.provider, item.failure_class))
        best = signals[0] if signals else None
        return {
            "failure_class": best.failure_class if best else "UNKNOWN",
            "confidence": best.confidence if best else 0.0,
            "rationale": best.rationale if best else "No deterministic signature matched; fail closed to UNKNOWN",
            "provider": best.provider if best else None,
            "signals": [item.to_dict() for item in signals],
        }


class DiagnosisClassifierAdapter:
    """Callable adapter for rc6_runtime.diagnosis.DiagnosisRuntime."""

    def __init__(self, diagnoser: Optional[MultiToolLogDiagnoser] = None) -> None:
        self.diagnoser = diagnoser or MultiToolLogDiagnoser()

    def __call__(self, context, signals: Dict[str, object]) -> Dict[str, object]:
        sources = signals.get("sources", {}) if isinstance(signals, dict) else {}
        chunks: List[str] = []
        if isinstance(sources, dict):
            for value in sources.values():
                chunks.append(str(value))
        for ref in getattr(context, "runner_log_refs", ()) or ():
            chunks.append(str(ref))
        summary = self.diagnoser.analyze("\n".join(chunks))
        failure_class = str(summary["failure_class"])
        if failure_class == "UNKNOWN" and getattr(context, "product_ownership_proven", lambda: False)():
            failure_class = "UNKNOWN"
        return {
            "failure_class": failure_class,
            "classifier_ref": "rc7:multi-tool-log-diagnoser:v1",
            "rationale": str(summary["rationale"]),
            "evidence_refs": list(getattr(context, "execution_evidence_refs", ()) or ()),
            "diagnostic_summary": summary,
        }
