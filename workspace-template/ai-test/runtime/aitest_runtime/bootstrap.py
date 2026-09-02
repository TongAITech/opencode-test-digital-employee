from __future__ import annotations

from typing import Any

from .defects import list_defects
from .doctor import run as doctor_run
from .human import list_tasks
from .mission import list_missions
from .project import get_project, list_projects, project_status
from .scheduler import seed_layers
from .storage import all_rows, initialize


def start(project_id: str | None = None) -> dict[str, Any]:
    initialize()
    seed_layers()
    projects = list_projects()
    if not project_id and len(projects) == 1:
        project_id = projects[0]["project_id"]
    if not project_id:
        return {
            "action": "CREATE_OR_SELECT_PROJECT",
            "projects": projects,
            "doctor": doctor_run(),
            "next_commands": ["aitest project init", "aitest project list"],
        }
    project = get_project(project_id)
    missions = list_missions(project_id, states=["DRAFT", "DISCOVERING", "TRUTH_SYNC", "SCOPING", "WAITING_H1", "PLANNING", "WAITING_H2", "PREFLIGHT", "WAITING_H3", "EXECUTING", "WAITING_HUMAN", "VERIFYING", "WAITING_H4", "BLOCKED"])
    human_tasks = list_tasks(project_id, statuses=["WAITING", "CLAIMED"])
    defects = list_defects(project_id, statuses=["OBSERVED", "TRIAGED", "CONFIRMED", "ASSIGNED", "FIX_IN_PROGRESS", "FIXED", "WAITING_DEPLOYMENT", "READY_FOR_RETEST", "RETESTING", "REOPENED"])
    releases = all_rows("SELECT * FROM releases WHERE project_id=? ORDER BY updated_at DESC", (project_id,))
    return {
        "action": "RESUME_ACTIVE_MISSION" if missions else "PROJECT_READY_FOR_WORK",
        "project": project,
        "project_status": project_status(project_id),
        "active_missions": missions,
        "pending_human_tasks": human_tasks,
        "open_defects": defects,
        "releases": releases,
        "doctor": doctor_run(project_id),
        "next": (
            {"command": "mission continue", "mission_id": missions[0]["mission_id"]}
            if missions else {"command": "release/requirement bootstrap"}
        ),
    }
