"""RC8 product API overlay for truthful TestRun projections."""
from __future__ import annotations

from typing import Any, Dict

from .governance_projection import GovernanceProjectionService
from .http_server import CenterHttpApplication


class CenterProductApplication:
    """Compose product read APIs over the existing Node/Artifact protocol API."""

    def __init__(
        self,
        base_application: CenterHttpApplication,
        governance_projection: GovernanceProjectionService,
    ) -> None:
        self.base_application = base_application
        self.governance_projection = governance_projection

    def get(self, path: str) -> Dict[str, Any]:
        clean = path.strip("/")
        parts = clean.split("/")
        if len(parts) == 5 and parts[:3] == ["api", "v1", "test-runs"] and parts[4] == "governance":
            test_run_id = parts[3]
            return {"test_run": self.governance_projection.test_run(test_run_id)}
        return self.base_application.get(path)

    def post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        return self.base_application.post(path, body)

    def put(self, path: str, query: Dict[str, Any], data: bytes) -> Dict[str, Any]:
        return self.base_application.put(path, query, data)
