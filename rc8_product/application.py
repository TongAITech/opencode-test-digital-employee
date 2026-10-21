"""Product API application facade for RC8.

This surface intentionally projects control/runtime truth; it does not own a
second business store.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from rc8_center.node_view import NodeReadModel
from rc8_control.node_registry import NodeRegistryError


class ProductError(RuntimeError):
    pass


class ProductApplication:
    def __init__(self, center) -> None:
        self.center = center
        self.nodes = NodeReadModel(center)

    def list_nodes(self, params: Optional[Dict[str, str]] = None, now: Optional[int] = None) -> Dict[str, Any]:
        params = params or {}
        items = self.nodes.list_nodes(
            status=params.get("status") or None,
            operator=params.get("operator") or None,
            capability=params.get("capability") or None,
            query=params.get("q") or None,
            now=now,
        )
        return {"items": items, "total": len(items)}

    def node_detail(self, node_id: str, now: Optional[int] = None) -> Dict[str, Any]:
        try:
            return self.nodes.detail(node_id, now=now)
        except NodeRegistryError as exc:
            raise ProductError(str(exc))

    def health(self) -> Dict[str, Any]:
        return {
            "status": "UP",
            "product": "RC8",
            "runtime_truth": "R1_EVENT_STREAM",
        }
