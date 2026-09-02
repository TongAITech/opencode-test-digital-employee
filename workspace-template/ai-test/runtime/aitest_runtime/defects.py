from __future__ import annotations

import hashlib
from typing import Any

from .capability import invoke
from .common import new_id, now_iso, sha256_bytes
from .human import create_task
from .mission import create_mission
from .scheduler import create_campaign, materialize_campaign
from .storage import all_rows, jdump, jload, one, transaction

CLASSIFICATIONS = {
    "PRODUCT_DEFECT", "TEST_CASE_DEFECT", "TEST_DATA_ISSUE", "ENVIRONMENT_ISSUE", "AUTOMATION_DEFECT",
    "TOOL_DEFECT", "KNOWLEDGE_GAP", "EXPECTED_BEHAVIOR", "UNKNOWN",
}
DETERMINISTIC_PRODUCT_SIGNALS = {"ASSERTION_MISMATCH", "CONTRACT_MISMATCH", "COMPILATION_FAILURE", "UNIT_TEST_FAILURE", "UNHANDLED_EXCEPTION"}


def create_observation(
    *,
    mission_id: str | None,
    run_id: str | None,
    step_id: str | None,
    requirement_id: str | None,
    sst_id: str | None,
    test_layer: str | None,
    dimension: str | None,
    expected: dict[str, Any],
    actual: dict[str, Any],
    evidence: list[str] | None = None,
    build_ref: str | None = None,
    deployment_ref: str | None = None,
) -> dict[str, Any]:
    oid = new_id("OBS")
    signature_payload = {
        "requirement_id": requirement_id,
        "sst_id": sst_id,
        "dimension": dimension,
        "error_code": actual.get("error_code") or actual.get("exception") or actual.get("status"),
        "component": actual.get("component"),
    }
    signature = sha256_bytes(jdump(signature_payload).encode())[:24]
    with transaction() as conn:
        conn.execute(
            "INSERT INTO observations(observation_id,mission_id,run_id,step_id,requirement_id,sst_id,test_layer,dimension,expected_json,actual_json,evidence_json,build_ref,deployment_ref,status,correlation_signature,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (oid, mission_id, run_id, step_id, requirement_id, sst_id, test_layer, dimension, jdump(expected), jdump(actual), jdump(evidence or []), build_ref, deployment_ref, "OBSERVED", signature, now_iso()),
        )
    return observation(oid)


def observation(observation_id: str) -> dict[str, Any]:
    row = one("SELECT * FROM observations WHERE observation_id=?", (observation_id,))
    if not row:
        raise KeyError(observation_id)
    row["expected"] = jload(row.pop("expected_json"), {})
    row["actual"] = jload(row.pop("actual_json"), {})
    row["evidence"] = jload(row.pop("evidence_json"), [])
    return row


def diagnose_observation(
    observation_id: str,
    *,
    actor: str = "aitest-diagnosis",
    classification: str | None = None,
    confidence: str = "MEDIUM",
    root_component: str | None = None,
    root_cause: str | None = None,
    excluded: list[str] | None = None,
    cat_query: dict[str, Any] | None = None,
) -> dict[str, Any]:
    obs = observation(observation_id)
    cat_evidence = None
    cat_used = 0
    if cat_query:
        try:
            cat_evidence = invoke("cat.query", actor, cat_query, mission_id=obs.get("mission_id"), step_id=obs.get("step_id"))
            cat_used = 1
        except Exception as exc:
            cat_evidence = {"ok": False, "error": str(exc)}
            cat_used = 1
    actual = obs["actual"]
    if not classification:
        if actual.get("environment_error"):
            classification = "ENVIRONMENT_ISSUE"
        elif actual.get("test_data_error"):
            classification = "TEST_DATA_ISSUE"
        elif actual.get("stale_test_asset"):
            classification = "TEST_CASE_DEFECT"
        elif actual.get("tool_error"):
            classification = "TOOL_DEFECT"
        elif actual.get("expected_behavior"):
            classification = "EXPECTED_BEHAVIOR"
        elif actual.get("signal") in DETERMINISTIC_PRODUCT_SIGNALS or actual.get("exception"):
            classification = "PRODUCT_DEFECT"
            confidence = "HIGH" if cat_evidence and cat_evidence.get("ok") else confidence
        else:
            classification = "UNKNOWN"
    classification = classification.upper()
    if classification not in CLASSIFICATIONS:
        raise ValueError(classification)
    evidence = list(obs["evidence"])
    if cat_evidence:
        evidence.append({"channel": "CAT", "payload": cat_evidence})
    did = new_id("DIAG")
    with transaction() as conn:
        conn.execute(
            "INSERT INTO diagnoses(diagnosis_id,observation_id,classification,confidence,root_component,root_cause,excluded_json,evidence_json,cat_used,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (did, observation_id, classification, confidence.upper(), root_component or actual.get("component"), root_cause, jdump(excluded or []), jdump(evidence), cat_used, actor, now_iso()),
        )
        conn.execute("UPDATE observations SET status='DIAGNOSED' WHERE observation_id=?", (observation_id,))
    return diagnosis(did)


def diagnosis(diagnosis_id: str) -> dict[str, Any]:
    row = one("SELECT * FROM diagnoses WHERE diagnosis_id=?", (diagnosis_id,))
    if not row:
        raise KeyError(diagnosis_id)
    row["excluded"] = jload(row.pop("excluded_json"), [])
    row["evidence"] = jload(row.pop("evidence_json"), [])
    return row


def _confirmation_mode(classification: str, confidence: str, severity: str, dimension: str | None) -> str:
    if classification != "PRODUCT_DEFECT":
        return "NOT_APPLICABLE"
    if severity.upper() in {"S0", "S1"} or (dimension or "").upper() in {"SECURITY", "PERFORMANCE"} or confidence.upper() not in {"HIGH", "CERTAIN"}:
        return "HUMAN_CONFIRM"
    return "AUTO_CONFIRMED"


def correlate_defect(
    diagnosis_id: str,
    *,
    project_id: str,
    title: str,
    severity: str = "S2",
    actor: str = "aitest-diagnosis",
) -> dict[str, Any]:
    diag = diagnosis(diagnosis_id)
    obs = observation(diag["observation_id"])
    if diag["classification"] != "PRODUCT_DEFECT":
        return {"created": False, "classification": diag["classification"], "observation_id": obs["observation_id"]}
    existing = one(
        "SELECT d.* FROM defects d JOIN defect_observations x ON d.defect_id=x.defect_id JOIN observations o ON x.observation_id=o.observation_id WHERE o.correlation_signature=? AND d.status NOT IN ('CLOSED','NOT_A_DEFECT','DUPLICATE') LIMIT 1",
        (obs["correlation_signature"],),
    )
    if existing:
        defect_id = existing["defect_id"]
        with transaction() as conn:
            conn.execute("INSERT OR IGNORE INTO defect_observations(defect_id,observation_id) VALUES(?,?)", (defect_id, obs["observation_id"]))
            layers = set(jload(existing["detected_layers_json"], []))
            if obs.get("test_layer"):
                layers.add(obs["test_layer"])
            conn.execute("UPDATE defects SET detected_layers_json=?,updated_at=? WHERE defect_id=?", (jdump(sorted(layers)), now_iso(), defect_id))
        return {"created": False, "merged": True, "defect": get_defect(defect_id)}
    mode = _confirmation_mode(diag["classification"], diag["confidence"], severity, obs.get("dimension"))
    defect_id = new_id("DEF")
    now = now_iso()
    status = "CONFIRMED" if mode == "AUTO_CONFIRMED" else "TRIAGED"
    confirmed_by = actor if mode == "AUTO_CONFIRMED" else None
    confirmed_at = now if mode == "AUTO_CONFIRMED" else None
    layers = [obs["test_layer"]] if obs.get("test_layer") else []
    with transaction() as conn:
        conn.execute(
            "INSERT INTO defects(defect_id,project_id,requirement_id,primary_sst_id,title,severity,defect_type,status,first_detected_layer,detected_layers_json,root_component,root_cause,confirmation_mode,confirmed_by,confirmed_at,created_at,updated_at,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (defect_id, project_id, obs.get("requirement_id"), obs.get("sst_id"), title, severity.upper(), "PRODUCT_DEFECT", status, obs.get("test_layer"), jdump(layers), diag.get("root_component"), diag.get("root_cause"), mode, confirmed_by, confirmed_at, now, now, jdump({"diagnosis_id": diagnosis_id, "correlation_signature": obs["correlation_signature"]})),
        )
        conn.execute("INSERT INTO defect_observations(defect_id,observation_id) VALUES(?,?)", (defect_id, obs["observation_id"]))
    if mode == "HUMAN_CONFIRM" and obs.get("mission_id"):
        create_task(obs["mission_id"], "REVIEW", f"Confirm defect {defect_id}", "Review API/CAT/DB/Browser/Deployment evidence and confirm or reject the product defect candidate.", step_id=obs.get("step_id"))
    return {"created": True, "defect": get_defect(defect_id)}


def get_defect(defect_id: str) -> dict[str, Any]:
    row = one("SELECT * FROM defects WHERE defect_id=?", (defect_id,))
    if not row:
        raise KeyError(defect_id)
    row["detected_layers"] = jload(row.pop("detected_layers_json"), [])
    row["metadata"] = jload(row.pop("metadata_json"), {})
    row["observations"] = [r["observation_id"] for r in all_rows("SELECT observation_id FROM defect_observations WHERE defect_id=?", (defect_id,))]
    obligations = all_rows("SELECT * FROM verification_obligations WHERE defect_id=? ORDER BY test_layer,dimension", (defect_id,))
    for o in obligations:
        o["scope"] = jload(o.pop("scope_json"), {})
    row["verification_obligations"] = obligations
    return row


def list_defects(project_id: str, statuses: list[str] | None = None) -> list[dict[str, Any]]:
    sql = "SELECT defect_id FROM defects WHERE project_id=?"
    params: list[Any] = [project_id]
    if statuses:
        sql += " AND status IN (" + ",".join("?" for _ in statuses) + ")"
        params.extend(statuses)
    sql += " ORDER BY updated_at DESC"
    return [get_defect(r["defect_id"]) for r in all_rows(sql, params)]


def confirm_defect(defect_id: str, reviewer: str, decision: str, reason: str = "") -> dict[str, Any]:
    defect = get_defect(defect_id)
    decision = decision.upper()
    if decision not in {"CONFIRM", "NOT_A_DEFECT", "DUPLICATE"}:
        raise ValueError(decision)
    status = {"CONFIRM": "CONFIRMED", "NOT_A_DEFECT": "NOT_A_DEFECT", "DUPLICATE": "DUPLICATE"}[decision]
    metadata = {**defect.get('metadata', {}), 'confirmation_reason': reason}
    with transaction() as conn:
        conn.execute("UPDATE defects SET status=?,confirmed_by=?,confirmed_at=?,updated_at=?,metadata_json=? WHERE defect_id=?", (status, reviewer, now_iso(), now_iso(), jdump(metadata), defect_id))
    return get_defect(defect_id)


def register_fix(defect_id: str, commit: str, *, build: str | None = None, deployment: str | None = None, actor: str = "developer") -> dict[str, Any]:
    defect = get_defect(defect_id)
    if defect["status"] not in {"CONFIRMED", "ASSIGNED", "FIX_IN_PROGRESS", "REOPENED"}:
        raise ValueError(f"defect not fixable from {defect['status']}")
    status = "READY_FOR_RETEST" if deployment else "WAITING_DEPLOYMENT"
    with transaction() as conn:
        conn.execute("UPDATE defects SET fix_commit=?,fix_build=?,fix_deployment=?,status=?,updated_at=? WHERE defect_id=?", (commit, build, deployment, status, now_iso(), defect_id))
    if deployment:
        create_verification_obligations(defect_id)
    return get_defect(defect_id)


def create_verification_obligations(defect_id: str) -> list[dict[str, Any]]:
    defect = get_defect(defect_id)
    layers = set(defect["detected_layers"])
    first = defect.get("first_detected_layer")
    if first:
        layers.add(first)
    # Downstream layers are retested when a lower layer defect propagated upward.
    order = ["L1", "L2", "L3", "L4", "L5", "L6", "L7"]
    if first in order:
        start = order.index(first)
        propagated = [layer for layer in order[start:] if layer in layers or layer in {"L3", "L4", "L5"}]
        layers.update(propagated)
    observations = [observation(oid) for oid in defect["observations"]]
    dimensions = {o.get("dimension") or "FUNCTIONAL" for o in observations}
    created = []
    for layer in sorted(layers, key=lambda x: order.index(x) if x in order else 99):
        for dimension in dimensions:
            oid = f"VO-{defect_id}-{layer}-{dimension}"
            record = {
                "obligation_id": oid,
                "defect_id": defect_id,
                "test_layer": layer,
                "dimension": dimension,
                "scope_json": jdump({"requirement_id": defect.get("requirement_id"), "sst_id": defect.get("primary_sst_id"), "fix_commit": defect.get("fix_commit")}),
                "status": "PENDING",
                "retest_mission_id": None,
                "result_ref": None,
                "updated_at": now_iso(),
            }
            with transaction() as conn:
                conn.execute(
                    "INSERT INTO verification_obligations(obligation_id,defect_id,test_layer,dimension,scope_json,status,retest_mission_id,result_ref,updated_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(obligation_id) DO NOTHING",
                    tuple(record.values()),
                )
            created.append(record)
    return created


def dispatch_retest(defect_id: str, actor: str = "aitest-scheduler") -> dict[str, Any]:
    defect = get_defect(defect_id)
    if defect["status"] not in {"READY_FOR_RETEST", "RETESTING"}:
        raise ValueError(f"defect not ready for retest: {defect['status']}")
    project_id = defect["project_id"]
    req = one("SELECT * FROM requirements WHERE requirement_id=?", (defect.get("requirement_id"),))
    campaign = create_campaign(project_id, "DEFECT_RETEST", f"Retest {defect_id}", release_id=(req or {}).get("release_id"), requirement_id=defect.get("requirement_id"), metadata={"defect_id": defect_id})
    obligations = defect["verification_obligations"] or create_verification_obligations(defect_id)
    missions = []
    for ob in obligations:
        mission = create_mission(project_id, f"{defect_id} · {ob['test_layer']} {ob['dimension']}", actor, release_id=(req or {}).get("release_id"), requirement_id=defect.get("requirement_id"), campaign_id=campaign["campaign_id"], mission_type="RETEST", metadata={"defect_id": defect_id, "obligation_id": ob["obligation_id"], "sst_id": defect.get("primary_sst_id"), "layer_id": ob["test_layer"], "dimension": ob["dimension"]})
        with transaction() as conn:
            conn.execute("UPDATE verification_obligations SET status='DISPATCHED',retest_mission_id=?,updated_at=? WHERE obligation_id=?", (mission["mission_id"], now_iso(), ob["obligation_id"]))
        missions.append(mission)
    with transaction() as conn:
        conn.execute("UPDATE defects SET status='RETESTING',updated_at=? WHERE defect_id=?", (now_iso(), defect_id))
    return {"defect": get_defect(defect_id), "campaign": campaign, "missions": missions}


def record_retest_result(obligation_id: str, status: str, result_ref: str) -> dict[str, Any]:
    status = status.upper()
    if status not in {"PASS", "FAIL", "BLOCKED"}:
        raise ValueError(status)
    with transaction() as conn:
        conn.execute("UPDATE verification_obligations SET status=?,result_ref=?,updated_at=? WHERE obligation_id=?", (status, result_ref, now_iso(), obligation_id))
    row = one("SELECT defect_id FROM verification_obligations WHERE obligation_id=?", (obligation_id,))
    if not row:
        raise KeyError(obligation_id)
    defect_id = row["defect_id"]
    obligations = all_rows("SELECT status FROM verification_obligations WHERE defect_id=?", (defect_id,))
    if obligations and all(o["status"] == "PASS" for o in obligations):
        with transaction() as conn:
            conn.execute("UPDATE defects SET status='VERIFIED',updated_at=? WHERE defect_id=?", (now_iso(), defect_id))
    elif any(o["status"] == "FAIL" for o in obligations):
        with transaction() as conn:
            conn.execute("UPDATE defects SET status='REOPENED',updated_at=? WHERE defect_id=?", (now_iso(), defect_id))
    return get_defect(defect_id)


def close_defect(defect_id: str, reviewer: str) -> dict[str, Any]:
    defect = get_defect(defect_id)
    obligations = defect["verification_obligations"]
    if not obligations or not all(o["status"] == "PASS" for o in obligations):
        raise ValueError("VERIFICATION_OBLIGATIONS_NOT_SATISFIED")
    if defect["status"] != "VERIFIED":
        raise ValueError(f"defect must be VERIFIED before close, got {defect['status']}")
    metadata = {**defect.get('metadata', {}), 'closed_by': reviewer}
    with transaction() as conn:
        conn.execute("UPDATE defects SET status='CLOSED',updated_at=?,metadata_json=? WHERE defect_id=?", (now_iso(), jdump(metadata), defect_id))
    return get_defect(defect_id)
