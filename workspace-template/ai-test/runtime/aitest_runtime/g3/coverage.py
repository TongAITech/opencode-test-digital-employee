from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from aitest_runtime.durable_core import RuntimeError, canonical_sha256
from .contracts import validate_coverage_snapshot

COVERAGE_PROVIDER_STATES = frozenset({"AVAILABLE", "PARTIAL", "AUTH_REQUIRED", "SOURCE_UNAVAILABLE"})
COVERAGE_LEVELS = frozenset({"AGGREGATE", "FILE", "CLASS", "LINE"})
COVERAGE_QUERY_MODES = ("API", "PAGE", "EXPORT")

@dataclass(frozen=True)
class CoverageProviderResult:
    status: str
    capabilities: tuple[str, ...]
    snapshot: Mapping[str, Any] | None = None
    warnings: tuple[str, ...] = ()
    human_action: Mapping[str, Any] | None = None
    def __post_init__(self) -> None:
        if self.status not in COVERAGE_PROVIDER_STATES: raise RuntimeError("G3_COVERAGE_PROVIDER_STATUS_INVALID", self.status)
        if any(c not in COVERAGE_LEVELS for c in self.capabilities): raise RuntimeError("G3_COVERAGE_LEVEL_INVALID", str(self.capabilities))
        if self.status in {"AVAILABLE", "PARTIAL"} and self.snapshot is None: raise RuntimeError("G3_COVERAGE_SNAPSHOT_REQUIRED", self.status)
        if self.snapshot is not None: object.__setattr__(self, "snapshot", validate_coverage_snapshot(self.snapshot))
    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "capabilities": list(self.capabilities), "snapshot": dict(self.snapshot) if self.snapshot else None, "warnings": list(self.warnings), "human_action": dict(self.human_action) if self.human_action else None}

class CoveragePlatformProvider(Protocol):
    def acquire(self, profile: Mapping[str, Any], query: Mapping[str, Any]) -> CoverageProviderResult: ...

class MappingCoveragePlatformProvider:
    """Deterministic construction/approved adapter. It never fabricates missing actual coverage."""
    def __init__(self, result: CoverageProviderResult | Mapping[str, Any]) -> None:
        if isinstance(result, CoverageProviderResult): self.result = result
        else: self.result = CoverageProviderResult(status=str(result["status"]), capabilities=tuple(result.get("capabilities") or ()), snapshot=result.get("snapshot"), warnings=tuple(result.get("warnings") or ()), human_action=result.get("human_action"))
    def acquire(self, profile: Mapping[str, Any], query: Mapping[str, Any]) -> CoverageProviderResult:
        return self.result

class BankCoveragePlatformProvider:
    """Fail-closed provider with API -> PAGE -> EXPORT adapter priority.

    Real bank selectors/endpoints/parsers remain Field Validation truth.  A
    transport may be one callable (legacy/construction adapter) or a mapping of
    explicit mode -> callable.  Merely having a browser or binary never creates
    Actual Coverage.
    """
    def __init__(self, transport: Any | None = None) -> None:
        self.transport = transport

    @staticmethod
    def _result(raw: Any) -> CoverageProviderResult:
        if isinstance(raw, CoverageProviderResult):
            return raw
        if not isinstance(raw, Mapping):
            raise RuntimeError("G3_COVERAGE_PROVIDER_INVALID", "transport result must be object")
        return CoverageProviderResult(
            status=str(raw["status"]), capabilities=tuple(raw.get("capabilities") or ()),
            snapshot=raw.get("snapshot"), warnings=tuple(raw.get("warnings") or ()),
            human_action=raw.get("human_action"),
        )

    @staticmethod
    def _mode_order(profile: Mapping[str, Any]) -> tuple[str, ...]:
        preferred = str(profile.get("preferred_query_method") or profile.get("method") or "API").upper()
        if preferred not in COVERAGE_QUERY_MODES:
            raise RuntimeError("G3_COVERAGE_QUERY_MODE_INVALID", preferred)
        return tuple(dict.fromkeys((preferred, *COVERAGE_QUERY_MODES)))

    def acquire(self, profile: Mapping[str, Any], query: Mapping[str, Any]) -> CoverageProviderResult:
        if not profile.get("authenticated_context_ref"):
            return CoverageProviderResult(
                "AUTH_REQUIRED", (),
                human_action={"gate_kind": "COVERAGE_PLATFORM_AUTH", "login_url": profile.get("login_url"), "profile_id": profile.get("platform_profile_id")},
            )
        if self.transport is None:
            return CoverageProviderResult("SOURCE_UNAVAILABLE", (), warnings=("BANK_COVERAGE_TRANSPORT_NOT_FIELD_BOUND",))

        # Backward-compatible single adapter: the adapter owns its exact mode.
        if callable(self.transport):
            return self._result(self.transport(profile, query))

        if not isinstance(self.transport, Mapping):
            raise RuntimeError("G3_COVERAGE_PROVIDER_INVALID", "transport must be callable or mode mapping")

        attempts: list[str] = []
        for mode in self._mode_order(profile):
            adapter = self.transport.get(mode)
            if not callable(adapter):
                attempts.append(f"{mode}:UNAVAILABLE")
                continue
            result = self._result(adapter(profile, query))
            if result.status == "SOURCE_UNAVAILABLE":
                attempts.append(f"{mode}:SOURCE_UNAVAILABLE")
                continue
            warnings = tuple(dict.fromkeys((*attempts, f"SOURCE_MODE:{mode}", *result.warnings)))
            return CoverageProviderResult(result.status, result.capabilities, snapshot=result.snapshot, warnings=warnings, human_action=result.human_action)
        return CoverageProviderResult("SOURCE_UNAVAILABLE", (), warnings=tuple(attempts or ("BANK_COVERAGE_MODE_ADAPTER_UNAVAILABLE",)))


def reconcile_coverage(change_analyses: list[Mapping[str, Any]], snapshot: Mapping[str, Any]) -> dict[str, Any]:
    snap = validate_coverage_snapshot(snapshot)
    target_application = str(snap["application_id"])
    target_analyses = [
        analysis for analysis in change_analyses
        if str(analysis.get("application_id") or analysis.get("repository_id") or "") == target_application
    ]
    base_result = {
        "reconciliation_id": "coverage-reconciliation:" + canonical_sha256({"snapshot": snap["snapshot_id"], "changes": change_analyses})[:20],
        "snapshot_id": snap["snapshot_id"],
        "application_id": target_application,
        "baseline_identity_status": snap["baseline_identity_status"],
        "cross_time_comparison": "PROHIBITED_WITHOUT_PINNED_BASELINE" if snap["baseline_identity_status"] == "MASTER_ALIAS_ONLY" else "ALLOWED_SAME_IDENTITY_ONLY",
    }
    if not target_analyses:
        return {
            **base_result,
            "state": "SOURCE_IDENTITY_MISMATCH",
            "matched": [], "static_only": [], "platform_only": [], "coverage_gaps": [],
            "static_applications": sorted({str(a.get("application_id") or a.get("repository_id") or "") for a in change_analyses}),
            "reason": "coverage snapshot application has no matching static change analysis",
        }

    platform_lines: dict[tuple[str, int], Mapping[str, Any]] = {}
    for detail in snap.get("details") or []:
        path = str(detail.get("file_path") or "").replace("\\", "/").lstrip("./")
        if not path:
            continue
        if str(detail.get("level")).upper() == "LINE" and isinstance(detail.get("line_number"), int):
            platform_lines[(path, int(detail["line_number"]))] = detail

    matches: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    static_only: list[dict[str, Any]] = []
    static_keys: set[tuple[str, int]] = set()
    for analysis in target_analyses:
        app = str(analysis.get("application_id") or analysis.get("repository_id") or "")
        for file in analysis.get("changed_files") or []:
            path = str(file.get("file_path") or "").replace("\\", "/").lstrip("./")
            for ref in file.get("diff_hunk_refs") or []:
                try:
                    line_no = int(str(ref).rsplit("L", 1)[1])
                except (ValueError, IndexError):
                    continue
                key = (path, line_no)
                static_keys.add(key)
                detail = platform_lines.get(key)
                if detail is None:
                    static_only.append({"application_id": app, "file_path": path, "line_number": line_no, "state": "STATIC_ONLY"})
                    continue
                item = {"application_id": app, "file_path": path, "line_number": line_no, "covered": detail.get("covered"), "state": "MATCHED"}
                matches.append(item)
                if detail.get("covered") is False:
                    gaps.append({**item, "gap_id": "gap:" + canonical_sha256(item)[:20], "priority": "HIGH", "source": "BANK_PLATFORM_ACTUAL"})

    platform_only = [
        {"application_id": target_application, "file_path": p, "line_number": ln, "state": "PLATFORM_ONLY"}
        for (p, ln) in platform_lines if (p, ln) not in static_keys
    ]
    state = "MATCHED"
    if static_only and platform_only:
        state = "AMBIGUOUS"
    elif static_only:
        state = "STATIC_ONLY"
    elif platform_only:
        state = "PLATFORM_ONLY"
    return {
        **base_result,
        "state": state,
        "matched": matches, "static_only": static_only, "platform_only": platform_only, "coverage_gaps": gaps,
    }
