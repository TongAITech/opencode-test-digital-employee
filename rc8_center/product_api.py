"""RC8 product API overlay for truthful TestRun projections."""
from __future__ import annotations

from typing import Any, Dict, Optional

from .governance_projection import GovernanceProjectionService
from .http_server import CenterHttpApplication


class CenterProductApplication:
    """Compose product read APIs over the existing Node/Artifact protocol API.

    The wrapper deliberately exposes the same control/artifact-store handles as
    the base application so the canonical Center launcher and bank smoke path do
    not fork into a separate server implementation.
    """

    def __init__(
        self,
        base_application: CenterHttpApplication,
        governance_projection: GovernanceProjectionService,
        governance_ingestor: Optional[object] = None,
    ) -> None:
        self.base_application = base_application
        self.governance_projection = governance_projection
        self.governance_ingestor = governance_ingestor

    @property
    def control(self):
        return self.base_application.control

    @property
    def artifact_store(self):
        return self.base_application.artifact_store

    def _replay(self) -> Optional[Dict[str, Any]]:
        if self.governance_ingestor is None:
            return None
        replay = getattr(self.governance_ingestor, "replay", None)
        if replay is None:
            raise TypeError("GOVERNANCE_INGESTOR_REPLAY_INVALID")
        result = replay()
        if not isinstance(result, dict):
            raise TypeError("GOVERNANCE_REPLAY_RESULT_INVALID")
        return result

    def get(self, path: str) -> Dict[str, Any]:
        clean = path.strip("/")
        parts = clean.split("/")
        if len(parts) == 5 and parts[:3] == ["api", "v1", "test-runs"] and parts[4] == "governance":
            replay = self._replay()
            test_run_id = parts[3]
            result: Dict[str, Any] = {"test_run": self.governance_projection.test_run(test_run_id)}
            if replay is not None:
                result["projection_replay"] = replay
            return result
        return self.base_application.get(path)

    def post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        # Runtime truth must be persisted to R1 first. Projection is strictly a
        # consequence of an accepted runtime event, never a parallel write path.
        response = self.base_application.post(path, body)
        if path.strip("/") == "api/v1/runtime-events" and self.governance_ingestor is not None:
            ingest = getattr(self.governance_ingestor, "ingest", None)
            if ingest is None:
                raise TypeError("GOVERNANCE_INGESTOR_INVALID")
            result = ingest(body)
            if not isinstance(result, dict):
                raise TypeError("GOVERNANCE_INGEST_RESULT_INVALID")
            response["governance_projection"] = result
        return response

    def put(self, path: str, query: Dict[str, Any], data: bytes) -> Dict[str, Any]:
        return self.base_application.put(path, query, data)
