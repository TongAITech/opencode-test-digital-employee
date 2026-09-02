from __future__ import annotations

from typing import Any

from .common import new_id, now_iso
from .storage import all_rows, jdump, jload, one, transaction

RESULT_STATUSES = {
    "PLANNED", "SELECTED", "NOT_SELECTED", "BLOCKED", "SKIPPED", "NOT_APPLICABLE",
    "EXECUTED_PASS", "EXECUTED_FAIL", "ABORTED", "NEEDS_HUMAN",
}


def create_run(mission_id: str, requirement_id: str | None, environment_id: str | None, baseline_fingerprint: str | None) -> dict[str, Any]:
    rid = new_id("RUN")
    with transaction() as conn:
        conn.execute(
            "INSERT INTO test_runs(run_id,mission_id,requirement_id,environment_id,status,baseline_fingerprint,started_at,completed_at,summary_json) VALUES(?,?,?,?,?,?,?,?,?)",
            (rid, mission_id, requirement_id, environment_id, "RUNNING", baseline_fingerprint, now_iso(), None, "{}"),
        )
    return get_run(rid)


def get_run(run_id: str) -> dict[str, Any]:
    row = one("SELECT * FROM test_runs WHERE run_id=?", (run_id,))
    if not row:
        raise KeyError(run_id)
    row["summary"] = jload(row.pop("summary_json"), {})
    row["results"] = results(run_id)
    return row


def record(run_id: str, case_id: str, status: str, result: dict[str, Any] | None = None) -> dict[str, Any]:
    status = status.upper()
    if status not in RESULT_STATUSES:
        raise ValueError(status)
    with transaction() as conn:
        conn.execute(
            "INSERT INTO run_results(run_id,case_id,status,result_json) VALUES(?,?,?,?) ON CONFLICT(run_id,case_id) DO UPDATE SET status=excluded.status,result_json=excluded.result_json",
            (run_id, case_id, status, jdump(result or {})),
        )
    return {"run_id": run_id, "case_id": case_id, "status": status, "result": result or {}}


def results(run_id: str) -> list[dict[str, Any]]:
    rows = all_rows("SELECT * FROM run_results WHERE run_id=? ORDER BY case_id", (run_id,))
    for row in rows:
        row["result"] = jload(row.pop("result_json"), {})
    return rows


def summarize(run_id: str, *, designed_total: int | None = None) -> dict[str, Any]:
    rows = results(run_id)
    counts = {status: 0 for status in sorted(RESULT_STATUSES)}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    current_scope = sum(counts[s] for s in ["SELECTED", "BLOCKED", "SKIPPED", "EXECUTED_PASS", "EXECUTED_FAIL", "ABORTED", "NEEDS_HUMAN"])
    executed = counts["EXECUTED_PASS"] + counts["EXECUTED_FAIL"]
    not_selected = counts["NOT_SELECTED"]
    total = designed_total if designed_total is not None else len(rows)
    scope_conserved = total == current_scope + not_selected + counts["NOT_APPLICABLE"] + counts["PLANNED"]
    execution_conserved = current_scope == counts["SELECTED"] + counts["BLOCKED"] + counts["SKIPPED"] + executed + counts["ABORTED"] + counts["NEEDS_HUMAN"]
    summary = {
        "designed_total": total,
        "current_scope": current_scope,
        "executed": executed,
        "counts": counts,
        "scope_conserved": scope_conserved,
        "execution_conserved": execution_conserved,
        "ok": scope_conserved and execution_conserved,
    }
    with transaction() as conn:
        conn.execute("UPDATE test_runs SET summary_json=? WHERE run_id=?", (jdump(summary), run_id))
    return summary


def complete(run_id: str, *, designed_total: int | None = None) -> dict[str, Any]:
    summary = summarize(run_id, designed_total=designed_total)
    if not summary["ok"]:
        raise ValueError("EXECUTION_ACCOUNTING_GATE_FAILED")
    status = "PASS" if summary["counts"]["EXECUTED_FAIL"] == 0 and summary["counts"]["BLOCKED"] == 0 else "FAIL"
    with transaction() as conn:
        conn.execute("UPDATE test_runs SET status=?,completed_at=?,summary_json=? WHERE run_id=?", (status, now_iso(), jdump(summary), run_id))
    return get_run(run_id)
