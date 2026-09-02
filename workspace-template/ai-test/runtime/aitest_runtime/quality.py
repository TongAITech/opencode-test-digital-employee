from __future__ import annotations

import json
from typing import Any

from .capability import invoke, registry
from .common import new_id, now_iso, redact, sha256_bytes
from .defects import create_observation
from .human import create_task
from .mission import current_step, get_mission, role_for_actor, transition
from .storage import all_rows, jdump, jload, one, transaction, upsert
from .truth import gate_set, gate_status, reconcile_baseline


def register_test_case(
    requirement_id: str,
    case_id: str,
    title: str,
    layer_id: str,
    dimension: str,
    contract: dict[str, Any],
    *,
    sst_id: str | None = None,
) -> dict[str, Any]:
    raw = jdump(contract)
    now = now_iso()
    record = {
        "case_id": case_id,
        "requirement_id": requirement_id,
        "sst_id": sst_id,
        "layer_id": layer_id,
        "dimension": dimension.upper(),
        "title": title,
        "status": "ACTIVE",
        "contract_json": raw,
        "asset_hash": sha256_bytes(raw.encode()),
        "created_at": now,
        "updated_at": now,
    }
    existing = one("SELECT created_at FROM test_cases WHERE case_id=?", (case_id,))
    if existing:
        record["created_at"] = existing["created_at"]
    upsert("test_cases", ["case_id"], record)
    return test_case(case_id)


def test_case(case_id: str) -> dict[str, Any]:
    row = one("SELECT * FROM test_cases WHERE case_id=?", (case_id,))
    if not row:
        raise KeyError(case_id)
    row["contract"] = jload(row.pop("contract_json"), {})
    return row


def review_gate(
    project_id: str,
    gate_type: str,
    requirement_id: str,
    reviewer: str,
    decision: str,
    *,
    release_id: str | None = None,
    sst_id: str | None = None,
    evidence: list[str] | None = None,
    reason: str = "",
) -> dict[str, Any]:
    decision = decision.upper()
    if decision not in {"APPROVE", "REWORK", "REJECT", "ACCEPT_RISK"}:
        raise ValueError(decision)
    status = "PASS" if decision in {"APPROVE", "ACCEPT_RISK"} else "FAIL"
    return gate_set(project_id, gate_type, status, release_id=release_id, requirement_id=requirement_id, sst_id=sst_id, decision=decision, reviewer=reviewer, evidence=evidence, reason=reason)


def _plain_secret(value: Any, key: str = "") -> bool:
    import re
    sensitive = re.compile(r"(?i)(password|passwd|pwd|token|authorization|cookie|secret|otp|mfa)")
    if key and sensitive.search(key):
        return not (isinstance(value, str) and value.startswith(("secret://", "profile://", "env://")))
    if isinstance(value, dict):
        return any(_plain_secret(v, str(k)) for k, v in value.items())
    if isinstance(value, list):
        return any(_plain_secret(v) for v in value)
    return False


def evaluate_preflight(mission_id: str, environment_id: str) -> dict[str, Any]:
    mission = get_mission(mission_id)
    blockers: list[str] = []
    req = mission.get("requirement_id")
    release = mission.get("release_id")
    if not req or not release:
        blockers.append("MISSION_SCOPE_INCOMPLETE")
        baseline = {"ok": False, "blockers": [{"code": "MISSION_SCOPE_INCOMPLETE"}]}
    else:
        baseline = reconcile_baseline(mission["project_id"], release, req, environment_id)
        if not baseline["ok"]:
            blockers.append("BASELINE_NOT_READY")
    if req and release:
        # L1-L5 must have an explicit automatic decision; L6-L7 must have an
        # explicit per-SST risk selected/not-selected decision.  Missing truth
        # is a blocker, never an implicit NOT_APPLICABLE.
        from .scheduler import compute_applicability, unresolved_applicability
        existing_applicability = all_rows("SELECT * FROM applicability WHERE requirement_id=?", (req,))
        if not existing_applicability:
            existing_applicability = compute_applicability(mission["project_id"], release, req, source_ref=f"preflight:{mission_id}")
        unresolved = unresolved_applicability(req)
        if unresolved:
            blockers.append("TEST_APPLICABILITY_UNRESOLVED")
    else:
        unresolved = []
    h1 = gate_status(req, "H1") if req else None
    h2 = gate_status(req, "H2") if req else None
    if not h1 or h1.get("status") != "PASS":
        blockers.append("H1_NOT_PASS")
    showcase_required = bool(mission.get("metadata", {}).get("showcase_required"))
    if showcase_required and (not h2 or h2.get("status") != "PASS"):
        blockers.append("H2_SHOWCASE_NOT_PASS")
    capabilities = registry()
    missing_caps = []
    for step in mission.get("steps") or []:
        cap = step.get("capability_id")
        if cap and cap not in capabilities:
            missing_caps.append(cap)
        if _plain_secret(step.get("input") or {}):
            blockers.append(f"PLAINTEXT_SECRET:{step['step_id']}")
    if missing_caps:
        blockers.append("UNREGISTERED_CAPABILITIES:" + ",".join(sorted(set(missing_caps))))
    result = {
        "ok": not blockers,
        "mission_id": mission_id,
        "requirement_id": req,
        "environment_id": environment_id,
        "baseline": baseline,
        "baseline_fingerprint": baseline.get("fingerprint"),
        "blockers": blockers,
        "unresolved_applicability": unresolved,
        "checked_at": now_iso(),
    }
    with transaction() as conn:
        conn.execute("UPDATE missions SET state=?,blocker=?,updated_at=?,metadata_json=? WHERE mission_id=?", (
            "WAITING_H3" if result["ok"] else "BLOCKED",
            None if result["ok"] else ";".join(blockers),
            now_iso(),
            jdump({**mission.get("metadata", {}), "environment_id": environment_id, "preflight": result}),
            mission_id,
        ))
    return result


def authorize_execution(mission_id: str, reviewer: str, decision: str, reason: str = "") -> dict[str, Any]:
    mission = get_mission(mission_id, include_steps=False)
    req = mission.get("requirement_id")
    env = mission.get("metadata", {}).get("environment_id")
    gate = review_gate(mission["project_id"], "H3", req, reviewer, decision, release_id=mission.get("release_id"), evidence=[f"mission:{mission_id}", f"environment:{env}"], reason=reason)
    if gate["status"] == "PASS":
        transition(mission_id, "EXECUTING", reviewer, reason="H3_APPROVED")
    return {"gate": gate, "mission": get_mission(mission_id)}


def _store_evidence(mission_id: str, step_id: str, channel: str, status: str, payload: Any, source_ref: str | None = None) -> str:
    evidence_id = new_id("EVD")
    raw = jdump(redact(payload))
    with transaction() as conn:
        conn.execute(
            "INSERT INTO evidence(evidence_id,mission_id,run_id,step_id,channel,status,source_ref,payload_json,sha256,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (evidence_id, mission_id, None, step_id, channel, status, source_ref, raw, sha256_bytes(raw.encode()), now_iso()),
        )
    return evidence_id


def execute_current_step(mission_id: str, actor: str) -> dict[str, Any]:
    if role_for_actor(actor) != "EXECUTOR":
        raise PermissionError("only EXECUTOR may execute steps")
    mission = get_mission(mission_id)
    if mission["state"] != "EXECUTING":
        raise ValueError(f"mission is not executing: {mission['state']}")
    preflight = mission.get("metadata", {}).get("preflight") or {}
    environment_id = mission.get("metadata", {}).get("environment_id")
    if mission.get("requirement_id") and mission.get("release_id") and environment_id and preflight.get("baseline_fingerprint"):
        current_baseline = reconcile_baseline(mission["project_id"], mission["release_id"], mission["requirement_id"], environment_id)
        if current_baseline.get("fingerprint") != preflight.get("baseline_fingerprint") or not current_baseline.get("ok"):
            gate_set(mission["project_id"], "H3", "FAIL", release_id=mission.get("release_id"), requirement_id=mission.get("requirement_id"), decision="REWORK", reviewer="system", evidence=[f"mission:{mission_id}"], reason="BASELINE_CHANGED_AFTER_PREFLIGHT")
            with transaction() as conn:
                conn.execute("UPDATE missions SET state='BLOCKED',blocker='BASELINE_CHANGED_AFTER_PREFLIGHT',updated_at=? WHERE mission_id=?", (now_iso(), mission_id))
            return {"status": "BLOCKED", "blocker": "BASELINE_CHANGED_AFTER_PREFLIGHT", "preflight_fingerprint": preflight.get("baseline_fingerprint"), "current_baseline": current_baseline, "mission": get_mission(mission_id)}
    step = current_step(mission_id)
    if not step:
        transition(mission_id, "WAITING_H4", actor, reason="NO_PENDING_STEPS")
        return {"status": "NO_PENDING_STEP", "mission": get_mission(mission_id)}
    with transaction() as conn:
        conn.execute("UPDATE mission_steps SET status='RUNNING',started_at=? WHERE step_id=?", (now_iso(), step["step_id"]))
    try:
        result = invoke(step["capability_id"], actor, step.get("input") or {}, mission_id=mission_id, step_id=step["step_id"])
    except PermissionError:
        raise
    except FileNotFoundError as exc:
        task = create_task(mission_id, "DATA_INPUT", f"Configure capability for {step['title']}", str(exc), step_id=step["step_id"])
        with transaction() as conn:
            conn.execute("UPDATE mission_steps SET status='WAITING_HUMAN',blocker=? WHERE step_id=?", (str(exc), step["step_id"]))
        return {"status": "WAITING_HUMAN", "human_task": task, "mission": get_mission(mission_id)}
    evidence_id = _store_evidence(mission_id, step["step_id"], "CAPABILITY", "COLLECTED", result)
    with transaction() as conn:
        conn.execute("UPDATE mission_steps SET status='EXECUTED',output_json=?,evidence_json=?,completed_at=? WHERE step_id=?", (jdump(result), jdump([evidence_id]), now_iso(), step["step_id"]))
        conn.execute("UPDATE missions SET state='VERIFYING',updated_at=? WHERE mission_id=?", (now_iso(), mission_id))
    return {"status": "EXECUTED", "step_id": step["step_id"], "result": result, "evidence_id": evidence_id, "mission": get_mission(mission_id)}


def _match(expected: Any, actual: Any) -> bool:
    if expected in ({}, None):
        return bool(actual.get("ok", True)) if isinstance(actual, dict) else True
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key, value in expected.items():
            if key not in actual or not _match(value, actual[key]):
                return False
        return True
    if isinstance(expected, list) and isinstance(actual, list):
        return all(any(_match(e, a) for a in actual) for e in expected)
    return expected == actual


def evaluate_current_step(mission_id: str, actor: str, *, override_status: str | None = None, reason: str = "") -> dict[str, Any]:
    if role_for_actor(actor) != "EVALUATOR":
        raise PermissionError("only EVALUATOR may evaluate step outcomes")
    mission = get_mission(mission_id)
    if mission["state"] != "VERIFYING":
        raise ValueError(f"mission is not verifying: {mission['state']}")
    step = current_step(mission_id)
    if not step:
        transition(mission_id, "WAITING_H4", actor, reason="ALL_STEPS_EVALUATED")
        return {"status": "NO_PENDING_STEP", "mission": get_mission(mission_id)}
    raw = one("SELECT * FROM mission_steps WHERE step_id=?", (step["step_id"],))
    actual = jload(raw.get("output_json"), {})
    expected = jload(raw.get("expected_json"), {})
    passed = _match(expected, actual)
    status = (override_status or ("PASS" if passed else "FAIL")).upper()
    if status not in {"PASS", "FAIL", "BLOCKED"}:
        raise ValueError(status)
    evidence = jload(raw.get("evidence_json"), [])
    with transaction() as conn:
        conn.execute("UPDATE mission_steps SET status=?,blocker=? WHERE step_id=?", (status, reason or None, step["step_id"]))
        if status == "PASS":
            nxt = conn.execute("SELECT step_id FROM mission_steps WHERE mission_id=? AND plan_version=? AND ordinal>? ORDER BY ordinal LIMIT 1", (mission_id, raw["plan_version"], raw["ordinal"])).fetchone()
            if nxt:
                conn.execute("UPDATE missions SET state='EXECUTING',current_step_id=?,updated_at=? WHERE mission_id=?", (nxt["step_id"], now_iso(), mission_id))
            else:
                conn.execute("UPDATE missions SET state='WAITING_H4',current_step_id=NULL,updated_at=? WHERE mission_id=?", (now_iso(), mission_id))
        elif status == "FAIL":
            conn.execute("UPDATE missions SET state='BLOCKED',blocker='STEP_ASSERTION_FAILED',updated_at=? WHERE mission_id=?", (now_iso(), mission_id))
        else:
            conn.execute("UPDATE missions SET state='BLOCKED',blocker=?,updated_at=? WHERE mission_id=?", (reason or "EVALUATION_BLOCKED", now_iso(), mission_id))
    observation = None
    if status == "FAIL":
        meta = mission.get("metadata", {})
        observation = create_observation(
            mission_id=mission_id,
            run_id=None,
            step_id=step["step_id"],
            requirement_id=mission.get("requirement_id"),
            sst_id=meta.get("sst_id"),
            test_layer=meta.get("layer_id"),
            dimension=meta.get("dimension"),
            expected=expected,
            actual=actual if isinstance(actual, dict) else {"actual": actual},
            evidence=evidence,
            build_ref=meta.get("build_ref"),
            deployment_ref=meta.get("deployment_ref"),
        )
    return {"status": status, "passed": passed, "step_id": step["step_id"], "observation": observation, "mission": get_mission(mission_id)}


def finalize_mission(mission_id: str, reviewer: str, decision: str, reason: str = "") -> dict[str, Any]:
    mission = get_mission(mission_id)
    if mission["state"] != "WAITING_H4":
        raise ValueError(f"mission not waiting H4: {mission['state']}")
    gate = review_gate(mission["project_id"], "H4", mission.get("requirement_id"), reviewer, decision, release_id=mission.get("release_id"), evidence=[f"mission:{mission_id}"], reason=reason)
    if gate["status"] == "PASS":
        transition(mission_id, "COMPLETED", reviewer, reason="H4_APPROVED")
    else:
        transition(mission_id, "BLOCKED", reviewer, reason="H4_REWORK", blocker="H4_REWORK")
    return {"gate": gate, "mission": get_mission(mission_id)}
