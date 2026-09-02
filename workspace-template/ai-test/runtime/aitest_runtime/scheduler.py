from __future__ import annotations

from typing import Any

from .common import AI_ROOT, load_json, new_id, now_iso
from .mission import create_mission
from .storage import all_rows, jdump, jload, one, transaction, upsert

LAYER_CONFIG = AI_ROOT / "config" / "test-layers.json"
UNRESOLVED_APPLICABILITY = {"ASSESSMENT_REQUIRED", "RISK_ASSESSMENT_REQUIRED"}
SELECTED_APPLICABILITY = {"REQUIRED", "IMPACTED"}


def seed_layers() -> list[dict[str, Any]]:
    data = load_json(LAYER_CONFIG, {"layers": []})
    for item in data.get("layers") or []:
        upsert("test_layers", ["layer_id"], {
            "layer_id": item["id"],
            "name": item["name"],
            "ordinal": int(item["ordinal"]),
            "config_json": jdump(item),
        })
    return layer_definitions()


def layer_definitions() -> list[dict[str, Any]]:
    rows = all_rows("SELECT * FROM test_layers ORDER BY ordinal")
    for row in rows:
        row["config"] = jload(row.pop("config_json"), {})
    return rows


def ingest_event(project_id: str, event_type: str, *, release_id: str | None = None, requirement_id: str | None = None, sst_id: str | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    event = {
        "scheduler_event_id": new_id("SEV"),
        "project_id": project_id,
        "release_id": release_id,
        "requirement_id": requirement_id,
        "sst_id": sst_id,
        "event_type": event_type.upper(),
        "payload_json": jdump(payload or {}),
        "status": "PENDING",
        "created_at": now_iso(),
        "processed_at": None,
    }
    with transaction() as conn:
        conn.execute(
            "INSERT INTO scheduler_events(scheduler_event_id,project_id,release_id,requirement_id,sst_id,event_type,payload_json,status,created_at,processed_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            tuple(event.values()),
        )
    return {**event, "payload": payload or {}}


def _optional_bool(meta: dict[str, Any], key: str) -> bool | None:
    """Return an explicit applicability fact without manufacturing a default.

    V1.9.x showed that a missing fact must not silently become either selected or
    not applicable.  Values may be native booleans, 0/1, or common textual
    representations imported from enterprise truth systems.
    """
    if key not in meta or meta[key] is None:
        return None
    value = meta[key]
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().upper()
        if normalized in {"TRUE", "YES", "Y", "1", "REQUIRED", "SELECTED"}:
            return True
        if normalized in {"FALSE", "NO", "N", "0", "NOT_REQUIRED", "NOT_SELECTED", "N/A", "NA"}:
            return False
    return None


def _sst_characteristics(requirement_id: str, sst_id: str) -> dict[str, Any]:
    sst = one("SELECT * FROM requirement_ssts WHERE requirement_id=? AND sst_id=?", (requirement_id, sst_id)) or {}
    quality = one("SELECT * FROM sst_quality_scope WHERE requirement_id=? AND sst_id=?", (requirement_id, sst_id))
    meta = jload(sst.get("metadata_json"), {})
    return {
        "sst": sst,
        "quality": quality,
        "has_code_change": _optional_bool(meta, "has_code_change"),
        "has_component": _optional_bool(meta, "has_component"),
        "has_api": _optional_bool(meta, "has_api"),
        "has_ui": _optional_bool(meta, "has_ui"),
        "cross_system": _optional_bool(meta, "cross_system"),
    }


def _automatic_scope(value: bool | None, positive: str, negative: str) -> tuple[str, str]:
    if value is True:
        return "REQUIRED", positive
    if value is False:
        return "NOT_APPLICABLE", negative
    return "ASSESSMENT_REQUIRED", f"Automatic L1-L5 scope decision is unresolved: {positive}"


def _performance_scope(quality: dict[str, Any] | None) -> tuple[str, str]:
    if not quality:
        return "RISK_ASSESSMENT_REQUIRED", "No per-SST performance risk assessment was imported"
    if bool(quality.get("performance_required")):
        return "REQUIRED", "Performance testing was selected for this SST"
    status = str(quality.get("performance_status") or "").upper()
    if status in {"NOT_REQUIRED", "NOT_SELECTED", "N/A", "NA"}:
        return "NOT_SELECTED", "Performance risk was assessed and this SST was not selected"
    return "RISK_ASSESSMENT_REQUIRED", "Performance risk assessment has no explicit selected/not-selected decision"


def _security_scope(quality: dict[str, Any] | None) -> tuple[str, str]:
    if not quality:
        return "RISK_ASSESSMENT_REQUIRED", "No per-SST security risk assessment was imported"
    if bool(quality.get("security_test_required") or quality.get("security_requirement_identified")):
        return "REQUIRED", "Security testing was selected for this SST"
    statuses = {
        str(quality.get("security_design_review_status") or "").upper(),
        str(quality.get("security_test_review_status") or "").upper(),
    }
    if statuses and statuses <= {"NOT_REQUIRED", "NOT_SELECTED", "N/A", "NA"}:
        return "NOT_SELECTED", "Security risk was assessed and this SST was not selected"
    return "RISK_ASSESSMENT_REQUIRED", "Security risk assessment has no explicit selected/not-selected decision"


def compute_applicability(project_id: str, release_id: str, requirement_id: str, *, source_ref: str = "RUNTIME_RULES") -> list[dict[str, Any]]:
    """Build the L1-L7 applicability matrix without guessing.

    L1-L5 require an automatic explicit decision for every SST.  Missing inputs
    remain ASSESSMENT_REQUIRED.  L6-L7 require a per-SST risk decision and use
    RISK_ASSESSMENT_REQUIRED until selected or explicitly not selected.
    """
    seed_layers()
    ssts = all_rows("SELECT * FROM requirement_ssts WHERE requirement_id=? AND status='ACTIVE' ORDER BY sst_id", (requirement_id,))
    rows: list[dict[str, Any]] = []
    for sst in ssts:
        c = _sst_characteristics(requirement_id, sst["sst_id"])
        decisions = {
            "L1": _automatic_scope(c["has_code_change"], "Changed code or rules require unit/code-logic coverage", "No code/rule change is in this SST scope"),
            "L2": _automatic_scope(c["has_component"], "Component or module collaboration is in scope", "No component/module integration boundary is in scope"),
            "L3": _automatic_scope(c["has_api"], "API/service integration boundary is in scope", "No API/service integration boundary is in scope"),
            "L4": _automatic_scope(c["has_ui"], "A user-facing page or controlled-browser interaction is in scope", "No UI/browser interaction is in scope"),
            "L5": _automatic_scope(c["cross_system"], "A cross-system business journey is in scope", "No cross-system business journey is in scope"),
            "L6": _performance_scope(c["quality"]),
            "L7": _security_scope(c["quality"]),
        }
        for layer in layer_definitions():
            status, rationale = decisions[layer["layer_id"]]
            dims = layer["config"].get("default_dimensions") or ["FUNCTIONAL"]
            for dimension in dims:
                record = {
                    "applicability_id": f"APP-{requirement_id}-{sst['sst_id']}-{layer['layer_id']}-{dimension}",
                    "project_id": project_id,
                    "release_id": release_id,
                    "requirement_id": requirement_id,
                    "sst_id": sst["sst_id"],
                    "layer_id": layer["layer_id"],
                    "dimension": dimension,
                    "status": status,
                    "rationale": rationale,
                    "source_ref": source_ref,
                    "updated_at": now_iso(),
                }
                upsert("applicability", ["applicability_id"], record)
                rows.append(record)
    return rows


def unresolved_applicability(requirement_id: str) -> list[dict[str, Any]]:
    return all_rows(
        "SELECT * FROM applicability WHERE requirement_id=? AND status IN ('ASSESSMENT_REQUIRED','RISK_ASSESSMENT_REQUIRED') ORDER BY sst_id,layer_id,dimension",
        (requirement_id,),
    )


def create_campaign(project_id: str, campaign_type: str, title: str, *, release_id: str | None = None, requirement_id: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    cid = new_id("CAMPAIGN")
    now = now_iso()
    with transaction() as conn:
        conn.execute(
            "INSERT INTO campaigns(campaign_id,project_id,release_id,requirement_id,campaign_type,status,title,created_at,updated_at,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (cid, project_id, release_id, requirement_id, campaign_type.upper(), "DRAFT", title, now, now, jdump(metadata or {})),
        )
    return campaign(cid)


def campaign(campaign_id: str) -> dict[str, Any]:
    row = one("SELECT * FROM campaigns WHERE campaign_id=?", (campaign_id,))
    if not row:
        raise KeyError(campaign_id)
    row["metadata"] = jload(row.pop("metadata_json"), {})
    items = all_rows("SELECT * FROM campaign_items WHERE campaign_id=? ORDER BY layer_id,sst_id,dimension", (campaign_id,))
    for item in items:
        item["depends_on"] = jload(item.pop("depends_on_json"), [])
    row["items"] = items
    return row


def _dependency_map(applicability: list[dict[str, Any]], campaign_id: str) -> dict[str, list[str]]:
    ids = {
        (a["sst_id"], a["layer_id"], a["dimension"]): f"CI-{campaign_id}-{a['sst_id']}-{a['layer_id']}-{a['dimension']}"
        for a in applicability
    }
    by_sst_layer: dict[tuple[str, str], list[str]] = {}
    all_prejourney: list[str] = []
    for (sst_id, layer_id, _), item_id in ids.items():
        by_sst_layer.setdefault((sst_id, layer_id), []).append(item_id)
        if layer_id in {"L1", "L2", "L3", "L4"}:
            all_prejourney.append(item_id)
    dependencies: dict[str, list[str]] = {}
    for (sst_id, layer_id, dimension), item_id in ids.items():
        deps: list[str] = []
        # L1/L2/L3 are deliberately parallel. L4 waits only for the same SST's
        # service/API integration evidence. L5 is a requirement-level journey
        # and waits for every applicable L1-L4 item across the requirement.
        if layer_id == "L4":
            deps.extend(by_sst_layer.get((sst_id, "L3"), []))
        elif layer_id == "L5":
            deps.extend(x for x in all_prejourney if x != item_id)
        # Risk-selected L6/L7 are orthogonal campaigns and may run in parallel
        # once their own truth/gates are ready.
        dependencies[item_id] = sorted(set(deps))
    return dependencies


def materialize_campaign(campaign_id: str, actor: str = "aitest-scheduler") -> dict[str, Any]:
    camp = campaign(campaign_id)
    if not camp.get("requirement_id"):
        raise ValueError("release campaigns require explicit scope import before materialization")
    applicability = all_rows(
        "SELECT * FROM applicability WHERE requirement_id=? ORDER BY layer_id,sst_id,dimension",
        (camp["requirement_id"],),
    )
    if not applicability:
        applicability = compute_applicability(camp["project_id"], camp["release_id"], camp["requirement_id"])
    unresolved = [r for r in applicability if r["status"] in UNRESOLVED_APPLICABILITY]
    if unresolved:
        raise ValueError(f"applicability unresolved for {len(unresolved)} layer/dimension rows")
    selected = [r for r in applicability if r["status"] in SELECTED_APPLICABILITY]
    dependencies = _dependency_map(selected, campaign_id)
    created = []
    for app in selected:
        item_id = f"CI-{campaign_id}-{app['sst_id']}-{app['layer_id']}-{app['dimension']}"
        deps = dependencies[item_id]
        item = {
            "item_id": item_id,
            "campaign_id": campaign_id,
            "sst_id": app["sst_id"],
            "layer_id": app["layer_id"],
            "dimension": app["dimension"],
            "status": "WAITING_DEPENDENCY" if deps else "READY",
            "depends_on_json": jdump(deps),
            "mission_id": None,
            "rationale": app["rationale"],
            "updated_at": now_iso(),
        }
        upsert("campaign_items", ["item_id"], item)
        created.append(item)
    with transaction() as conn:
        conn.execute("UPDATE campaigns SET status='READY',updated_at=? WHERE campaign_id=?", (now_iso(), campaign_id))
    return {"campaign": campaign(campaign_id), "created_items": len(created)}


def refresh_campaign_dependencies(campaign_id: str) -> dict[str, Any]:
    """Project mission completion back into the campaign DAG and release nodes."""
    camp = campaign(campaign_id)
    items = {item["item_id"]: item for item in camp["items"]}
    changed = 0
    completed_states = {"COMPLETED"}
    terminal_failure_states = {"ABORTED"}
    for item in list(items.values()):
        mission_id = item.get("mission_id")
        if not mission_id:
            continue
        mission_row = one("SELECT state FROM missions WHERE mission_id=?", (mission_id,))
        state = (mission_row or {}).get("state")
        new_status = None
        if state in completed_states and item["status"] != "COMPLETED":
            new_status = "COMPLETED"
        elif state in terminal_failure_states and item["status"] != "FAILED":
            new_status = "FAILED"
        if new_status:
            with transaction() as conn:
                conn.execute("UPDATE campaign_items SET status=?,updated_at=? WHERE item_id=?", (new_status, now_iso(), item["item_id"]))
            item["status"] = new_status
            changed += 1
    completed = {i["item_id"] for i in items.values() if i["status"] == "COMPLETED"}
    failed = {i["item_id"] for i in items.values() if i["status"] == "FAILED"}
    for item in items.values():
        if item["status"] != "WAITING_DEPENDENCY":
            continue
        deps = set(item.get("depends_on") or [])
        if deps & failed:
            new_status = "BLOCKED_DEPENDENCY"
        elif deps <= completed:
            new_status = "READY"
        else:
            continue
        with transaction() as conn:
            conn.execute("UPDATE campaign_items SET status=?,updated_at=? WHERE item_id=?", (new_status, now_iso(), item["item_id"]))
        changed += 1
    latest = campaign(campaign_id)
    statuses = {i["status"] for i in latest["items"]}
    campaign_status = latest["status"]
    if latest["items"] and statuses <= {"COMPLETED"}:
        campaign_status = "COMPLETED"
    elif "FAILED" in statuses or "BLOCKED_DEPENDENCY" in statuses:
        campaign_status = "BLOCKED"
    elif "DISPATCHED" in statuses or "READY" in statuses or "WAITING_DEPENDENCY" in statuses:
        campaign_status = "RUNNING"
    if campaign_status != latest["status"]:
        with transaction() as conn:
            conn.execute("UPDATE campaigns SET status=?,updated_at=? WHERE campaign_id=?", (campaign_status, now_iso(), campaign_id))
    return {"campaign": campaign(campaign_id), "changed": changed}


def dispatch_ready(campaign_id: str, actor: str = "aitest-scheduler") -> dict[str, Any]:
    camp = refresh_campaign_dependencies(campaign_id)["campaign"]
    items = [i for i in camp["items"] if i["status"] == "READY"]
    missions = []
    for item in items:
        mission = create_mission(
            camp["project_id"],
            f"{camp['title']} · {item['sst_id']} · {item['layer_id']} {item['dimension']}",
            actor,
            release_id=camp.get("release_id"),
            requirement_id=camp.get("requirement_id"),
            campaign_id=campaign_id,
            mission_type="RETEST" if camp["campaign_type"] == "DEFECT_RETEST" else "TEST",
            metadata={"sst_id": item["sst_id"], "layer_id": item["layer_id"], "dimension": item["dimension"], "campaign_item_id": item["item_id"]},
        )
        with transaction() as conn:
            conn.execute("UPDATE campaign_items SET status='DISPATCHED',mission_id=?,updated_at=? WHERE item_id=?", (mission["mission_id"], now_iso(), item["item_id"]))
        missions.append(mission)
    if missions:
        with transaction() as conn:
            conn.execute("UPDATE campaigns SET status='RUNNING',updated_at=? WHERE campaign_id=?", (now_iso(), campaign_id))
    return {"campaign_id": campaign_id, "missions": missions, "count": len(missions)}


def process_events(project_id: str, limit: int = 100) -> dict[str, Any]:
    events = all_rows("SELECT * FROM scheduler_events WHERE project_id=? AND status='PENDING' ORDER BY created_at LIMIT ?", (project_id, limit))
    processed = []
    for event in events:
        payload = jload(event["payload_json"], {})
        event_type = event["event_type"]
        action: dict[str, Any] = {"event": event_type, "action": "NOOP"}
        req = event.get("requirement_id")
        if event_type in {"REQUIREMENT_CREATED", "SST_CHANGED", "CODE_COMMITTED", "CODE_MERGED", "DEPLOYMENT_COMPLETED", "SHOWCASE_COMPLETED", "H3_APPROVED", "SECURITY_DESIGN_REVIEW_APPROVED", "PERFORMANCE_SCOPE_APPROVED"} and req:
            compute_applicability(project_id, event.get("release_id") or payload.get("release_id"), req, source_ref=event["scheduler_event_id"])
            action = {"event": event_type, "action": "APPLICABILITY_RECOMPUTED", "requirement_id": req}
        if event_type == "DEFECT_FIXED" and payload.get("defect_id"):
            action = {"event": event_type, "action": "RETEST_PENDING", "defect_id": payload["defect_id"]}
        with transaction() as conn:
            conn.execute("UPDATE scheduler_events SET status='PROCESSED',processed_at=? WHERE scheduler_event_id=?", (now_iso(), event["scheduler_event_id"]))
        processed.append(action)
    return {"processed": processed, "count": len(processed)}
