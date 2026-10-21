"""Read model for the RC8 execution-node product surface."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from rc8_control.models import ExecutionNode, LeaseState


_STATUS_ZH = {
    "ONLINE": "在线",
    "IDLE": "空闲",
    "RUNNING": "执行中",
    "MAINTENANCE": "维护中",
    "ERROR": "异常",
    "OFFLINE": "离线",
}

_CAPABILITY_ZH = {
    "DISCOVERED": "已发现",
    "REGISTERED": "已注册",
    "EXECUTED": "已执行验证",
    "ASSERTED": "已断言",
    "EVIDENCE_PERSISTED": "证据已保存",
    "VERIFIED": "已验证",
    "ERROR": "异常",
    "UNAVAILABLE": "不可用",
}


class NodeReadModel:
    def __init__(self, center) -> None:
        self.center = center

    def list_nodes(
        self,
        status: Optional[str] = None,
        operator: Optional[str] = None,
        capability: Optional[str] = None,
        query: Optional[str] = None,
        now: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        rows = []
        for node in self.center.nodes.all_nodes(now=now):
            if status and node.status.value != status:
                continue
            if operator and node.operator != operator:
                continue
            if capability and capability not in node.capabilities:
                continue
            if query:
                haystack = " ".join(
                    [node.node_id, node.display_name, node.operator, node.platform, node.architecture]
                ).lower()
                if query.lower() not in haystack:
                    continue
            rows.append(self._summary(node, now=now))
        return rows

    def detail(self, node_id: str, now: Optional[int] = None) -> Dict[str, Any]:
        self.center.nodes.refresh_liveness(now=now)
        node = self.center.nodes.get(node_id)
        summary = self._summary(node, now=now)
        summary["capabilities"] = [
            {
                "name": name,
                "state": cap.state.value,
                "state_label": _CAPABILITY_ZH.get(cap.state.value, cap.state.value),
                "verified": cap.is_verified,
                "last_verified_at": cap.last_verified_at,
                "evidence_refs": list(cap.evidence_refs),
                "detail": cap.detail,
            }
            for name, cap in sorted(node.capabilities.items())
        ]
        summary["leases"] = self._leases_for_node(node.node_id, now=now)
        return summary

    def _summary(self, node: ExecutionNode, now: Optional[int] = None) -> Dict[str, Any]:
        verified = sum(1 for cap in node.capabilities.values() if cap.is_verified)
        current_leases = [item for item in self._leases_for_node(node.node_id, now=now) if item["state"] == LeaseState.ACTIVE.value]
        current_work_item = current_leases[0]["work_item_id"] if current_leases else None
        return {
            "node_id": node.node_id,
            "display_name": node.display_name,
            "operator": node.operator,
            "platform": node.platform,
            "architecture": node.architecture,
            "package_version": node.package_version,
            "status": node.status.value,
            "status_label": _STATUS_ZH.get(node.status.value, node.status.value),
            "heartbeat_at": node.heartbeat_at,
            "verified_capabilities": verified,
            "capability_total": len(node.capabilities),
            "current_work_item": current_work_item,
        }

    def _leases_for_node(self, node_id: str, now: Optional[int] = None) -> List[Dict[str, Any]]:
        return [
            {
                "lease_id": lease.lease_id,
                "work_item_id": lease.work_item_id,
                "state": lease.state.value,
                "issued_at": lease.issued_at,
                "expires_at": lease.expires_at,
                "required_capabilities": list(lease.required_capabilities),
            }
            for lease in self.center.nodes.leases_for_node(node_id, now=now)
        ]
