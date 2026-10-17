"""One-SST RC7 Bank Field Qualification control entrypoint.

This module joins the already-frozen Bank Mission bootstrap, strict real-mission
qualification and Bank Final launcher without inventing a second runtime state
store.  It deliberately does *not* perform domain testing itself.  Requirement,
Code, Test Design, Script and Execution remain owned by their existing DSH/
Runtime authorities and all progress remains durable in the canonical R1 event
stream.

The control surface is intentionally small:

* ``start-sst`` creates or resumes one graph-v2 Bank Mission and durably binds
  the selected SST identifiers to the Requirement Analysis task.
* ``status`` reconstructs current field progress from R1 and exposes the exact
  strict blockers (including Case Coverage / Recovery / Oracle / Defect Review).
* ``finalize`` is fail-closed: it delegates to Bank Final only after the Mission
  is CONVERGED and strict real-mission qualification already passes.

No command here can mark a Mission sufficient or fabricate field evidence.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import rc6_runtime.agent_runtime  # noqa: F401 - register R1 projections
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.bank_mission import start_or_resume
from rc7_runtime.truth_overlay import install_rc7_truth_overlay

from .bank_field_launcher import resolve_context, run_bank_final
from .real_mission_qualification_strict import evaluate_real_mission_strict


SCHEMA_VERSION = "pfc.aitest.rc7.one-sst-field-qualification.v1"
_SST_PREFIX = "sst://"
_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_HUMAN_STATES = {"HUMAN_REQUIRED"}
_BLOCKED_STATES = {"BLOCKED", "FAILED", "STALE", "REPAIR_REQUIRED"}
_ACTIVE_STATES = {"READY", "LEASED", "RUNNING", "OUTPUT_PRODUCED", "EVALUATING", "REGISTERED"}
_OPEN_GAP_STATES = {"OPEN", "PLANNED", "REPAIRING", "EVIDENCE_PENDING", "HUMAN_REQUIRED", "BLOCKED"}


class OneSstFieldQualificationError(RuntimeError):
    pass


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(dict(payload), handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")


def _package_root(value: Optional[str]) -> Path:
    raw = value or os.environ.get("PFC_AITEST_HOME") or os.getcwd()
    root = Path(raw).expanduser().resolve()
    if not root.is_dir():
        raise OneSstFieldQualificationError("PACKAGE_ROOT_NOT_FOUND:%s" % root)
    return root


def _r1_path(root: Path, value: Optional[str]) -> Path:
    raw = value or os.environ.get("PFC_RC7_R1_PATH")
    if raw:
        path = Path(raw).expanduser().resolve()
    else:
        state_root = Path(
            os.environ.get("PFC_AITEST_STATE_DIR", str(root / "runtime-state"))
        ).expanduser().resolve()
        path = state_root / "r1" / "event-stream.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _source_commit(root: Path, value: Optional[str]) -> str:
    commit = str(value or os.environ.get("PFC_RC7_SOURCE_COMMIT") or "").strip()
    if not commit:
        marker = root / "SOURCE_COMMIT"
        if marker.is_file():
            commit = marker.read_text(encoding="utf-8").strip()
    if not _SHA_RE.fullmatch(commit):
        raise OneSstFieldQualificationError("VALID_SOURCE_COMMIT_REQUIRED")
    return commit.lower()


def _normalize_ssts(values: Iterable[str]) -> Tuple[str, ...]:
    rows: List[str] = []
    for raw in values:
        value = str(raw or "").strip()
        if not value:
            continue
        if value.lower().startswith(_SST_PREFIX):
            value = value[len(_SST_PREFIX):].strip()
        if not value:
            continue
        if value not in rows:
            rows.append(value)
    if not rows:
        raise OneSstFieldQualificationError("SST_ID_REQUIRED")
    return tuple(rows)


def _mission_row(truth: TruthRuntime, mission_id: str) -> Mapping[str, Any]:
    rows = truth.query("rc7_mission", mission_id=mission_id)
    if len(rows) != 1:
        raise OneSstFieldQualificationError("MISSION_NOT_FOUND_OR_NOT_UNIQUE:%s" % mission_id)
    return rows[0]


def _tasks(truth: TruthRuntime, mission_id: str) -> List[Mapping[str, Any]]:
    return sorted(
        truth.query("rc7_task", mission_id=mission_id),
        key=lambda row: (int(row.get("priority") or 0), str(row.get("task_id") or "")),
    )


def _bound_ssts(truth: TruthRuntime, mission_id: str) -> List[str]:
    requirement = [
        row for row in truth.query("rc7_task", mission_id=mission_id)
        if row.get("node") == "REQUIREMENT_ANALYSIS" and row.get("task_type") != "EVALUATE"
    ]
    if len(requirement) != 1:
        raise OneSstFieldQualificationError("REQUIREMENT_TASK_NOT_UNIQUE")
    rows = []
    for ref in requirement[0].get("input_artifact_refs", []):
        if not isinstance(ref, str) or not ref.lower().startswith(_SST_PREFIX):
            continue
        value = ref[len(_SST_PREFIX):].strip()
        if value and value not in rows:
            rows.append(value)
    return sorted(rows)


def _task_view(rows: Iterable[Mapping[str, Any]]) -> List[Dict[str, str]]:
    return [
        {
            "task_id": str(row.get("task_id") or ""),
            "node": str(row.get("node") or ""),
            "task_type": str(row.get("task_type") or ""),
            "state": str(row.get("state") or ""),
        }
        for row in rows
    ]


def _status_output(root: Path, mission_id: str, explicit: Optional[str]) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    state_root = Path(
        os.environ.get("PFC_AITEST_STATE_DIR", str(root / "runtime-state"))
    ).expanduser().resolve()
    return state_root / "rc7-bank-field" / mission_id / "field-qualification.json"


def start_one_sst(
    *,
    package_root: str,
    mission_id: str,
    release_id: str,
    sst_ids: Sequence[str],
    goal: Optional[str] = None,
    r1_path: Optional[str] = None,
) -> Dict[str, Any]:
    root = _package_root(package_root)
    r1 = _r1_path(root, r1_path)
    ssts = _normalize_ssts(sst_ids)
    mission_goal = str(goal or "Qualify Bank SST %s end-to-end" % ",".join(ssts)).strip()
    result = start_or_resume(
        r1_path=str(r1),
        mission_id=str(mission_id).strip(),
        release_id=str(release_id).strip(),
        goal=mission_goal,
        external_inputs={"REQUIREMENT_ANALYSIS": tuple(_SST_PREFIX + value for value in ssts)},
        graph_version="v2",
    )
    truth = TruthRuntime(r1)
    bound = _bound_ssts(truth, str(mission_id).strip())
    if bound != sorted(ssts):
        raise OneSstFieldQualificationError(
            "SST_BINDING_MISMATCH:expected=%s:actual=%s"
            % (",".join(sorted(ssts)), ",".join(bound))
        )
    payload = dict(result)
    payload.update(
        {
            "schema_version": SCHEMA_VERSION,
            "control_kind": "ONE_SST_BANK_FIELD",
            "sst_ids": bound,
            "r1_path": str(r1),
            "bank_field_pass": False,
            "real_mission_pass": False,
        }
    )
    return payload


def build_status(
    *,
    package_root: str,
    mission_id: str,
    source_commit: Optional[str] = None,
    r1_path: Optional[str] = None,
    target_id: Optional[str] = None,
    qualification_dir: Optional[str] = None,
) -> Dict[str, Any]:
    install_rc7_truth_overlay()
    root = _package_root(package_root)
    r1 = _r1_path(root, r1_path)
    commit = _source_commit(root, source_commit)
    truth = TruthRuntime(r1)
    mission = _mission_row(truth, mission_id)
    tasks = _tasks(truth, mission_id)
    gaps = truth.query("rc7_gap", mission_id=mission_id)

    ready = [row for row in tasks if row.get("state") == "READY"]
    human = [row for row in tasks if row.get("state") in _HUMAN_STATES]
    blocked = [row for row in tasks if row.get("state") in _BLOCKED_STATES]
    active = [row for row in tasks if row.get("state") in _ACTIVE_STATES]
    human_gaps = [row for row in gaps if row.get("state") == "HUMAN_REQUIRED"]
    blocked_gaps = [row for row in gaps if row.get("state") == "BLOCKED"]
    open_gaps = [row for row in gaps if row.get("state") in _OPEN_GAP_STATES]

    try:
        strict = evaluate_real_mission_strict(
            r1_path=str(r1),
            mission_id=mission_id,
            source_commit=commit,
            require_bank_field_conformance=True,
        )
    except Exception as exc:
        strict = {
            "status": "HOLD",
            "blocking_reasons": ["STRICT_QUALIFICATION_ERROR:%s" % str(exc)],
            "bank_field_conformance": {"status": "HOLD", "blocking_reasons": []},
        }

    mission_state = str(mission.get("state") or "UNKNOWN")
    if human or human_gaps or mission_state == "WAITING_HUMAN":
        stage, status, next_action = "HUMAN_REQUIRED", "HUMAN_REQUIRED", "SATISFY_HUMAN_GATE_AND_RESUME_SAME_R1"
    elif blocked or blocked_gaps or mission_state == "BLOCKED":
        stage, status, next_action = "BLOCKED", "HOLD", "REPAIR_OR_BIND_FIELD_DEPENDENCY_AND_RESUME_SAME_R1"
    elif mission_state == "CONVERGED" and strict.get("status") == "PASS":
        stage, status, next_action = "READY_FOR_BANK_FINAL", "PASS", "RUN_BANK_FINAL"
    elif mission_state == "CONVERGED":
        stage, status, next_action = "MISSION_CONVERGED_FIELD_HOLD", "HOLD", "RESOLVE_STRICT_FIELD_BLOCKERS"
    elif active or open_gaps:
        stage, status, next_action = "MISSION_IN_PROGRESS", "IN_PROGRESS", "CONTINUE_DSH_RUNTIME_FROM_SAME_R1"
    else:
        stage, status, next_action = "HOLD", "HOLD", "INSPECT_STRICT_BLOCKERS"

    bank_field = strict.get("bank_field_conformance")
    case_coverage = bank_field.get("case_coverage") if isinstance(bank_field, Mapping) else None
    payload: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "control_kind": "ONE_SST_BANK_FIELD",
        "status": status,
        "stage": stage,
        "next_action": next_action,
        "package_root": str(root),
        "r1_path": str(r1),
        "source_commit": commit,
        "mission_id": mission_id,
        "release_id": str(mission.get("release_id") or ""),
        "mission_state": mission_state,
        "sufficiency_state": str(mission.get("sufficiency_state") or ""),
        "sst_ids": _bound_ssts(truth, mission_id),
        "task_state_counts": {},
        "ready_tasks": _task_view(ready),
        "human_tasks": _task_view(human),
        "blocked_tasks": _task_view(blocked),
        "open_gap_count": len(open_gaps),
        "strict_qualification_status": str(strict.get("status") or "HOLD"),
        "strict_blocking_reasons": list(strict.get("blocking_reasons") or []),
        "case_coverage": case_coverage,
        "bank_field_pass": False,
        "real_mission_pass": False,
        "finalization_authority": "QUALIFY_BANK_FINAL_AFTER_CONVERGED_AND_STRICT_PASS",
    }
    counts: Dict[str, int] = {}
    for row in tasks:
        key = str(row.get("state") or "UNKNOWN")
        counts[key] = counts.get(key, 0) + 1
    payload["task_state_counts"] = dict(sorted(counts.items()))

    if stage == "READY_FOR_BANK_FINAL":
        payload["bank_final_context"] = resolve_context(
            package_root=str(root),
            r1_path=str(r1),
            mission_id=mission_id,
            target_id=target_id,
            qualification_dir=qualification_dir,
        )
    return payload


def finalize(
    *,
    package_root: str,
    mission_id: str,
    source_commit: Optional[str] = None,
    r1_path: Optional[str] = None,
    target_id: Optional[str] = None,
    qualification_dir: Optional[str] = None,
) -> Tuple[Dict[str, Any], int]:
    status = build_status(
        package_root=package_root,
        mission_id=mission_id,
        source_commit=source_commit,
        r1_path=r1_path,
        target_id=target_id,
        qualification_dir=qualification_dir,
    )
    if status["stage"] != "READY_FOR_BANK_FINAL":
        return status, 3 if status["stage"] == "HUMAN_REQUIRED" else 2

    context = status.get("bank_final_context")
    if not isinstance(context, Mapping) or context.get("status") != "PASS":
        payload = dict(status)
        payload["status"] = "HOLD"
        payload["stage"] = "BANK_FINAL_CONTEXT_NOT_READY"
        payload["next_action"] = "RESOLVE_BANK_FINAL_CONTEXT"
        return payload, 2

    rc = run_bank_final(context)
    payload = dict(status)
    payload["bank_final_exit_code"] = int(rc)
    if rc == 0:
        payload["status"] = "BANK_FINAL_PASS"
        payload["stage"] = "BANK_FIELD_QUALIFIED"
        payload["next_action"] = "FIELD_QUALIFICATION_COMPLETE"
        payload["bank_field_pass"] = True
        payload["real_mission_pass"] = True
    elif rc == 3:
        payload["status"] = "HUMAN_REQUIRED"
        payload["stage"] = "DB_WRITE_HUMAN_GATE"
        payload["next_action"] = "SATISFY_HUMAN_GATE_AND_RESUME_SAME_R1"
    else:
        payload["status"] = "HOLD"
        payload["stage"] = "BANK_FINAL_NOT_QUALIFIED"
        payload["next_action"] = "INSPECT_BANK_FINAL_BLOCKERS"
    return payload, int(rc)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m rc7_release.one_sst_field_qualification")
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start-sst")
    start.add_argument("--package-root", default=None)
    start.add_argument("--r1")
    start.add_argument("--mission-id", required=True)
    start.add_argument("--release-id", required=True)
    start.add_argument("--sst-id", action="append", required=True)
    start.add_argument("--goal")
    start.add_argument("--source-commit")
    start.add_argument("--output")

    for name in ("status", "finalize"):
        child = sub.add_parser(name)
        child.add_argument("--package-root", default=None)
        child.add_argument("--r1")
        child.add_argument("--mission-id", required=True)
        child.add_argument("--source-commit")
        child.add_argument("--target-id")
        child.add_argument("--qualification-dir")
        child.add_argument("--output")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    root = _package_root(args.package_root)
    output = _status_output(root, args.mission_id, args.output)
    try:
        if args.command == "start-sst":
            bootstrap = start_one_sst(
                package_root=str(root),
                mission_id=args.mission_id,
                release_id=args.release_id,
                sst_ids=args.sst_id,
                goal=args.goal,
                r1_path=args.r1,
            )
            status = build_status(
                package_root=str(root),
                mission_id=args.mission_id,
                source_commit=args.source_commit,
                r1_path=args.r1,
            )
            payload = dict(status)
            payload["bootstrap"] = bootstrap
            rc = 0
        elif args.command == "status":
            payload = build_status(
                package_root=str(root),
                mission_id=args.mission_id,
                source_commit=args.source_commit,
                r1_path=args.r1,
                target_id=args.target_id,
                qualification_dir=args.qualification_dir,
            )
            rc = 0 if payload["status"] in {"PASS", "IN_PROGRESS"} else (3 if payload["status"] == "HUMAN_REQUIRED" else 2)
        else:
            payload, rc = finalize(
                package_root=str(root),
                mission_id=args.mission_id,
                source_commit=args.source_commit,
                r1_path=args.r1,
                target_id=args.target_id,
                qualification_dir=args.qualification_dir,
            )
    except Exception as exc:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "status": "HOLD",
            "stage": "CONTROL_ERROR",
            "reason": str(exc),
            "mission_id": args.mission_id,
            "bank_field_pass": False,
            "real_mission_pass": False,
        }
        rc = 2

    _write_json(output, payload)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return int(rc)


if __name__ == "__main__":
    raise SystemExit(main())
