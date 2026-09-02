from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from aitest_runtime.durable_core import RuntimeError, RuntimeService, canonical_sha256

from .contracts import REPORT_SCHEMA_VERSION, R1_5_CONTRACT_VERSION, ValidationReport, redact, utc_now


@dataclass(frozen=True)
class HealthReport:
    status: str
    checks: tuple[Mapping[str, Any], ...]
    observed_at: str
    as_of_seq: int | None
    freshness: str
    report_schema_version: str = REPORT_SCHEMA_VERSION
    contract_version: str = R1_5_CONTRACT_VERSION

    @property
    def healthy(self) -> bool:
        return self.status == "HEALTHY"

    def to_dict(self) -> dict[str, Any]:
        result = {
            "report_schema_version": self.report_schema_version,
            "contract_version": self.contract_version,
            "status": self.status,
            "checks": [redact(dict(item)) for item in self.checks],
            "observed_at": self.observed_at,
            "as_of_seq": self.as_of_seq,
            "freshness": self.freshness,
            "canonical": False,
            "truth_source": "EVENT_STREAM" if self.as_of_seq is not None else None,
        }
        result["digest"] = canonical_sha256(result)
        return result


def assess_health(runtime: RuntimeService, validation: ValidationReport, *, mission_id: str | None = None) -> HealthReport:
    checks: list[Mapping[str, Any]] = [
        {"check_id": "startup.validation", "status": "PASS" if validation.valid else "FAIL"},
        {"check_id": "runtime.database", "status": "PASS" if Path(runtime.db_path).is_file() else "FAIL"},
    ]
    as_of_seq: int | None = None
    freshness = "NOT_APPLICABLE"
    if mission_id:
        try:
            as_of_seq = runtime.get_head_seq(mission_id)
            projection = runtime.verify_projection(mission_id)
            projection_ok = bool(projection.get("ok"))
            checks.append({"check_id": "runtime.projection", "status": "PASS" if projection_ok else "FAIL", "mission_id": mission_id})
            freshness = "CURRENT" if projection_ok else "STALE"
        except RuntimeError as exc:
            checks.append({"check_id": "runtime.mission", "status": "FAIL", "mission_id": mission_id, "code": exc.code})
            freshness = "UNKNOWN"
    status = "HEALTHY" if all(item["status"] == "PASS" for item in checks) else "UNHEALTHY"
    return HealthReport(status, tuple(checks), utc_now(), as_of_seq, freshness)
