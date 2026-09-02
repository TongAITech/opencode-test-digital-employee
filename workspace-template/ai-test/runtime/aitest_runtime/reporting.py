from __future__ import annotations

from typing import Any

from .defects import list_defects
from .mission import get_mission, list_missions
from .project import project_status
from .scheduler import campaign
from .storage import all_rows, jload


def project_report(project_id: str) -> dict[str, Any]:
    status = project_status(project_id)
    missions = list_missions(project_id)
    defects = list_defects(project_id)
    human = all_rows("SELECT ht.* FROM human_tasks ht JOIN missions m ON m.mission_id=ht.mission_id WHERE m.project_id=? ORDER BY ht.created_at DESC", (project_id,))
    campaigns = all_rows("SELECT * FROM campaigns WHERE project_id=? ORDER BY updated_at DESC", (project_id,))
    for item in campaigns:
        item["metadata"] = jload(item.pop("metadata_json"), {})
    return {
        "project": status,
        "missions": missions,
        "mission_counts": _counts(missions, "state"),
        "defects": defects,
        "defect_counts": _counts(defects, "status"),
        "human_tasks": human,
        "human_task_counts": _counts(human, "status"),
        "campaigns": campaigns,
        "campaign_counts": _counts(campaigns, "status"),
    }


def _counts(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in items:
        value = str(item.get(key) or "UNKNOWN")
        result[value] = result.get(value, 0) + 1
    return result
