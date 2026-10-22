"""Durable Center repository for provenance-bound coverage observations."""
from __future__ import annotations

from typing import Any, Dict, List

from rc8_runtime.coverage import CoverageObservation
from rc8_runtime.governance import CoverageDimension, CoverageMetric

from .json_repository import DurableRepositoryError, _AtomicJsonFile, _jsonable


class JsonFileCoverageRepository:
    def __init__(self, path: str) -> None:
        self._file = _AtomicJsonFile(path, {"schema_version": 1, "observations": {}})

    def append(self, observation: CoverageObservation) -> None:
        def apply(data: Dict[str, Any]) -> None:
            rows = data.setdefault("observations", {})
            if not isinstance(rows, dict):
                raise DurableRepositoryError("COVERAGE_OBSERVATIONS_INVALID")
            if observation.observation_id in rows:
                raise DurableRepositoryError("COVERAGE_OBSERVATION_APPEND_ONLY:%s" % observation.observation_id)
            rows[observation.observation_id] = _jsonable(observation)
        self._file.mutate(apply)

    def list_for_test_run(self, test_run_id: str) -> List[CoverageObservation]:
        rows = self._file.read().get("observations", {})
        if not isinstance(rows, dict):
            raise DurableRepositoryError("COVERAGE_OBSERVATIONS_INVALID")
        values = [
            self._from_raw(raw)
            for raw in rows.values()
            if isinstance(raw, dict) and raw.get("test_run_id") == test_run_id
        ]
        return sorted(values, key=lambda item: (item.observed_at, item.observation_id))

    def list_for_attempt(self, test_run_id: str, attempt_id: str) -> List[CoverageObservation]:
        return [item for item in self.list_for_test_run(test_run_id) if item.attempt_id == attempt_id]

    @staticmethod
    def _from_raw(raw: Dict[str, Any]) -> CoverageObservation:
        metric_raw = raw.get("metric")
        if not isinstance(metric_raw, dict):
            raise DurableRepositoryError("COVERAGE_METRIC_INVALID")
        metric = CoverageMetric(
            metric_id=str(metric_raw.get("metric_id") or ""),
            dimension=CoverageDimension(str(metric_raw.get("dimension"))),
            covered=int(metric_raw.get("covered") or 0),
            total=int(metric_raw.get("total") or 0),
            threshold=float(metric_raw.get("threshold") or 0.0),
            evidence_refs=tuple(metric_raw.get("evidence_refs") or []),
            critical=bool(metric_raw.get("critical", False)),
        )
        return CoverageObservation(
            observation_id=str(raw.get("observation_id") or ""),
            test_run_id=str(raw.get("test_run_id") or ""),
            stage_instance_id=str(raw.get("stage_instance_id") or ""),
            subject_ref=str(raw.get("subject_ref") or ""),
            source_snapshot_ref=str(raw.get("source_snapshot_ref") or ""),
            metric=metric,
            attempt_id=str(raw["attempt_id"]) if raw.get("attempt_id") is not None else None,
            case_id=str(raw["case_id"]) if raw.get("case_id") is not None else None,
            source_tool=str(raw["source_tool"]) if raw.get("source_tool") is not None else None,
            artifact_refs=tuple(raw.get("artifact_refs") or []),
            observed_at=int(raw.get("observed_at") or 0),
        )
