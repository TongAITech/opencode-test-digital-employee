"""Product-facing governance projection for one TestRun.

The projection never invents PASS from counts.  It exposes the recorded mission,
coverage, gap, invalidation and release facts that the product UI must explain.
"""
from __future__ import annotations

from typing import Any, Dict

from .coverage_repository import JsonFileCoverageRepository
from .governance_repository import JsonFileGovernanceRepository
from .json_repository import _jsonable


class GovernanceProjectionService:
    def __init__(
        self,
        governance_repository: JsonFileGovernanceRepository,
        coverage_repository: JsonFileCoverageRepository,
    ) -> None:
        self.governance_repository = governance_repository
        self.coverage_repository = coverage_repository

    def test_run(self, test_run_id: str) -> Dict[str, Any]:
        base = self.governance_repository.test_run_projection(test_run_id)
        observations = self.coverage_repository.list_for_test_run(test_run_id)
        base["coverage_observations"] = [_jsonable(item) for item in observations]
        base["coverage_observation_count"] = len(observations)
        base["projection_contract"] = {
            "status_is_recorded_not_derived": True,
            "attempt_history_append_only": True,
            "coverage_is_snapshot_bound": True,
            "invalidated_results_remain_visible": True,
            "release_is_separate_from_test_sufficiency": True,
        }
        return base
