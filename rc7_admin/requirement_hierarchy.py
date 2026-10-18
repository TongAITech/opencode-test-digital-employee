from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from rc6_runtime.truth import TruthRuntime
from .projection import AdminProjection


class RequirementHierarchyView:
    def __init__(self, truth: TruthRuntime) -> None:
        self.truth = truth
        self.base = AdminProjection(truth)

    def list(self, *, page: int = 1, page_size: int = 20, filters: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
        self.base.refresh(); rows: List[Dict[str, Any]] = []; seen = set()
        for analysis in self.truth.query("requirement_analysis"):
            source_id = str(analysis.get("id") or analysis.get("requirement_id") or "REQ")
            release_id = analysis.get("release_id") or analysis.get("version") or analysis.get("release")
            requirement_id = analysis.get("requirement_id") or analysis.get("requirement") or source_id
            for level, node, parent_id, path in self._iter_nodes(analysis):
                node_id = self._node_id(level, node, source_id, path); key = (level, node_id, str(parent_id or ""), source_id)
                if key in seen: continue
                seen.add(key)
                rows.append({
                    "id": "%s:%s" % (level, node_id), "level": level, "node_id": node_id, "parent_id": parent_id,
                    "release_id": release_id, "requirement_id": requirement_id, "title": self._title(node),
                    "status": str(node.get("status") or node.get("state") or analysis.get("status") or analysis.get("state") or ""),
                    "source_analysis_id": source_id, "artifact_version": analysis.get("artifact_version"),
                    "updated_at": analysis.get("updated_at") or analysis.get("created_at"), "detail": dict(node),
                })
        return self.base.paginate_rows("requirement-hierarchy", rows, page=page, page_size=page_size, filters=filters)

    @classmethod
    def _iter_nodes(cls, value: Any, parent_id: Optional[str] = None, path: Tuple[str, ...] = ()) -> Iterable[Tuple[str, Mapping[str, Any], Optional[str], Tuple[str, ...]]]:
        aliases = {
            "BR": {"br", "brs", "business_requirement", "business_requirements", "businessrequirements", "br_refs"},
            "SR": {"sr", "srs", "system_requirement", "system_requirements", "systemrequirements", "sr_refs"},
            "TR": {"tr", "trs", "technical_requirement", "technical_requirements", "technicalrequirements", "tr_refs"},
        }
        if isinstance(value, Mapping):
            declared = str(value.get("level") or value.get("type") or value.get("kind") or "").upper(); current_parent = parent_id
            if declared in {"BR", "SR", "TR"}:
                node = dict(value); node_id = cls._node_id(declared, node, "NODE", path); yield declared, node, parent_id, path; current_parent = node_id
            for key, child in value.items():
                key_norm = str(key).replace("-", "_").lower(); matched = next((level for level, names in aliases.items() if key_norm in names), None)
                if matched:
                    children = child if isinstance(child, list) else [child]
                    for index, item in enumerate(children):
                        node = dict(item) if isinstance(item, Mapping) else {"id": str(item), "title": str(item)}; node_path = path + (str(key), str(index)); node_id = cls._node_id(matched, node, "NODE", node_path)
                        yield matched, node, current_parent, node_path
                        for nested in cls._iter_nodes(node, node_id, node_path): yield nested
                elif isinstance(child, (Mapping, list)):
                    for nested in cls._iter_nodes(child, current_parent, path + (str(key),)): yield nested
        elif isinstance(value, list):
            for index, child in enumerate(value):
                for nested in cls._iter_nodes(child, parent_id, path + (str(index),)): yield nested

    @staticmethod
    def _node_id(level: str, node: Mapping[str, Any], source_id: str, path: Tuple[str, ...]) -> str:
        for key in ("id", "%s_id" % level.lower(), "requirement_id", "code", "ref", "key"):
            raw = node.get(key)
            if raw not in (None, ""): return str(raw)
        return "%s-%s-%s" % (source_id, level, ".".join(path) or "0")

    @staticmethod
    def _title(node: Mapping[str, Any]) -> str:
        for key in ("title", "name", "summary", "objective", "description", "text"):
            raw = node.get(key)
            if raw not in (None, ""): return str(raw)
        return ""
