"""Single-entry RC7 Bank Field Qualification launcher.

The launcher removes shell-side environment stitching without weakening identity
checks. It may auto-resolve R1, Mission and Target only when each identity is
unique. Ambiguity is a HOLD, never a "latest wins" guess.

Bank Final itself remains owned by the existing QUALIFY-BANK-FINAL entrypoints;
this module only resolves trusted context and invokes that frozen gate.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import rc6_runtime.agent_runtime  # noqa: F401 - R1 registrations
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.execution_recovery_conformance import contract_enabled as recovery_contract_enabled
from rc7_runtime.node_tool_conformance import contract_enabled as node_tool_contract_enabled
from rc7_runtime.truth_overlay import install_rc7_truth_overlay


SCHEMA_VERSION = "pfc.aitest.rc7.bank-field-launcher.v1"
GRAPH_KIND = "MISSION_GRAPH_CONTRACT"
FORMAL_EXECUTION_KIND = "RUNTIME_EXECUTION_RECORD"
FORMAL_EXECUTION_SOURCE = "runtime://formal-execution"
REQUIRED_QUALIFICATION_FILES = ("engineering.json", "admin.json", "delivery.json")


class BankFieldLauncherError(RuntimeError):
    pass


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _package_root(value: Optional[str]) -> Path:
    raw = value or os.environ.get("PFC_AITEST_HOME") or os.getcwd()
    root = Path(raw).expanduser().resolve()
    if not root.is_dir():
        raise BankFieldLauncherError("PACKAGE_ROOT_NOT_FOUND:%s" % root)
    return root


def _dedupe_paths(values: Iterable[Path]) -> List[Path]:
    rows: List[Path] = []
    seen = set()
    for value in values:
        path = value.expanduser().resolve()
        key = os.path.normcase(str(path))
        if key in seen:
            continue
        seen.add(key)
        rows.append(path)
    return rows


def _r1_candidates(root: Path, explicit: Optional[str]) -> List[Path]:
    if explicit:
        return [Path(explicit).expanduser().resolve()]
    env_value = os.environ.get("PFC_RC7_R1_PATH")
    if env_value:
        return [Path(env_value).expanduser().resolve()]
    rows = [
        root / "runtime-state" / "r1" / "event-stream.jsonl",
        root / "runtime-state" / "rc7-bank-final" / "r1" / "event-stream.jsonl",
    ]
    state_root = root / "runtime-state"
    if state_root.is_dir():
        rows.extend(state_root.rglob("event-stream.jsonl"))
    return [path for path in _dedupe_paths(rows) if path.is_file()]


def _graph_v2(truth: TruthRuntime, mission_id: str) -> bool:
    rows = [
        row for row in truth.query("rc7_evidence", mission_id=mission_id)
        if row.get("kind") == GRAPH_KIND
    ]
    if len(rows) != 1:
        return False
    source = str(rows[0].get("source_ref") or "").lower()
    return source.endswith("/v2")


def _mission_candidates(truth: TruthRuntime, requested: Optional[str]) -> List[Dict[str, Any]]:
    rows = truth.query("rc7_mission")
    candidates: List[Dict[str, Any]] = []
    for row in rows:
        mission_id = str(row.get("mission_id") or "")
        if not mission_id or (requested and mission_id != requested):
            continue
        graph_v2 = _graph_v2(truth, mission_id)
        node_contract = node_tool_contract_enabled(truth, mission_id)
        recovery_contract = recovery_contract_enabled(truth, mission_id)
        if not (graph_v2 and node_contract and recovery_contract):
            continue
        candidates.append(
            {
                "mission_id": mission_id,
                "release_id": str(row.get("release_id") or ""),
                "state": str(row.get("state") or ""),
                "sufficiency_state": str(row.get("sufficiency_state") or ""),
                "graph_version": "v2",
                "node_tool_contract": True,
                "execution_recovery_contract": True,
            }
        )
    return sorted(candidates, key=lambda row: row["mission_id"])


def _json_file(path: Path) -> Optional[Mapping[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _file_ref_path(content_ref: object) -> Optional[Path]:
    if not isinstance(content_ref, str) or not content_ref.startswith("file://"):
        return None
    raw = content_ref[len("file://"):]
    if not raw:
        return None
    return Path(raw).expanduser()


def _target_candidates(truth: TruthRuntime, mission_id: str) -> List[str]:
    targets = set()
    for row in truth.query("rc7_evidence", mission_id=mission_id):
        if row.get("kind") != FORMAL_EXECUTION_KIND or row.get("source_ref") != FORMAL_EXECUTION_SOURCE:
            continue
        path = _file_ref_path(row.get("content_ref"))
        payload = _json_file(path) if path and path.is_file() else None
        record = payload.get("record") if isinstance(payload, Mapping) else None
        target_id = record.get("target_id") if isinstance(record, Mapping) else None
        if isinstance(target_id, str) and target_id.strip():
            targets.add(target_id.strip())

    # Execution conclusions are a second, mission-scoped durable source. They
    # are useful when a package predates formal-execution evidence, but are
    # still read-only and never inferred from unscoped execution_attempt rows.
    for row in truth.query("rc7_artifact", mission_id=mission_id):
        if row.get("artifact_type") != "EXECUTION_CONCLUSION":
            continue
        path = _file_ref_path(row.get("content_ref"))
        payload = _json_file(path) if path and path.is_file() else None
        record = payload.get("record") if isinstance(payload, Mapping) else None
        target_id = record.get("target_id") if isinstance(record, Mapping) else None
        if isinstance(target_id, str) and target_id.strip():
            targets.add(target_id.strip())
    return sorted(targets)


def _qualification_dir(root: Path, explicit: Optional[str]) -> Tuple[Optional[Path], List[Dict[str, Any]]]:
    values: List[Path] = []
    if explicit:
        values.append(Path(explicit))
    elif os.environ.get("PFC_RC7_QUALIFICATION_DIR"):
        values.append(Path(os.environ["PFC_RC7_QUALIFICATION_DIR"]))
    else:
        values.extend((root / "qualification", root.parent / "qualification"))
    inspected = []
    for path in _dedupe_paths(values):
        missing = [name for name in REQUIRED_QUALIFICATION_FILES if not (path / name).is_file()]
        inspected.append({"path": str(path), "missing": missing})
        if path.is_dir() and not missing:
            return path, inspected
    return None, inspected


def resolve_context(
    *,
    package_root: str,
    r1_path: Optional[str] = None,
    mission_id: Optional[str] = None,
    target_id: Optional[str] = None,
    qualification_dir: Optional[str] = None,
) -> Dict[str, Any]:
    install_rc7_truth_overlay()
    root = _package_root(package_root)
    r1_paths = _r1_candidates(root, r1_path)
    requested_mission = mission_id or os.environ.get("PFC_RC7_MISSION_ID")
    requested_target = target_id or os.environ.get("PFC_RC7_BANK_TARGET_ID")

    contexts: List[Dict[str, Any]] = []
    unreadable: List[str] = []
    for path in r1_paths:
        if not path.is_file():
            unreadable.append(str(path))
            continue
        try:
            truth = TruthRuntime(path)
            missions = _mission_candidates(truth, requested_mission)
        except Exception:
            unreadable.append(str(path))
            continue
        for mission in missions:
            contexts.append(
                {
                    "r1_path": str(path),
                    "mission": mission,
                    "target_candidates": _target_candidates(truth, mission["mission_id"]),
                }
            )

    if not contexts:
        reason = "REQUESTED_BANK_MISSION_NOT_FOUND" if requested_mission else "BANK_GRAPH_V2_MISSION_NOT_FOUND"
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "FIELD_REQUIRED",
            "reason": reason,
            "package_root": str(root),
            "r1_candidates": [str(path) for path in r1_paths],
            "unreadable_r1": unreadable,
        }
    if len(contexts) != 1:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "HOLD",
            "reason": "BANK_MISSION_CONTEXT_AMBIGUOUS",
            "package_root": str(root),
            "candidates": contexts,
        }

    selected = contexts[0]
    targets = list(selected["target_candidates"])
    if requested_target:
        if targets and requested_target not in targets:
            return {
                "schema_version": SCHEMA_VERSION,
                "status": "HOLD",
                "reason": "BANK_TARGET_NOT_PROVEN_BY_MISSION_EXECUTION",
                "requested_target_id": requested_target,
                "target_candidates": targets,
                "mission_id": selected["mission"]["mission_id"],
                "r1_path": selected["r1_path"],
            }
        resolved_target = requested_target
    elif len(targets) == 1:
        resolved_target = targets[0]
    elif not targets:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "FIELD_REQUIRED",
            "reason": "BANK_TARGET_ID_REQUIRED_NO_FORMAL_EXECUTION_TARGET",
            "mission_id": selected["mission"]["mission_id"],
            "r1_path": selected["r1_path"],
        }
    else:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "HOLD",
            "reason": "BANK_TARGET_AMBIGUOUS",
            "mission_id": selected["mission"]["mission_id"],
            "r1_path": selected["r1_path"],
            "target_candidates": targets,
        }

    qual, inspected = _qualification_dir(root, qualification_dir)
    if qual is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "FIELD_REQUIRED",
            "reason": "DELIVERY_QUALIFICATION_DIRECTORY_NOT_READY",
            "mission_id": selected["mission"]["mission_id"],
            "bank_target_id": resolved_target,
            "r1_path": selected["r1_path"],
            "qualification_candidates": inspected,
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "stage": "READY_FOR_BANK_FINAL",
        "package_root": str(root),
        "r1_path": selected["r1_path"],
        "mission_id": selected["mission"]["mission_id"],
        "release_id": selected["mission"]["release_id"],
        "mission_state": selected["mission"]["state"],
        "sufficiency_state": selected["mission"]["sufficiency_state"],
        "bank_target_id": resolved_target,
        "target_proven_by_formal_execution": resolved_target in targets,
        "qualification_dir": str(qual),
        "selection_policy": "UNIQUE_ONLY_NEVER_LATEST_WINS",
    }


def _launcher_output(root: Path) -> Path:
    state = Path(os.environ.get("PFC_AITEST_STATE_DIR", str(root / "runtime-state" / "rc7-bank-final"))).expanduser().resolve()
    return state / "rc7-bank-field-launcher.json"


def run_bank_final(context: Mapping[str, Any]) -> int:
    root = Path(str(context["package_root"])).resolve()
    env = dict(os.environ)
    env["PFC_AITEST_HOME"] = str(root)
    env["PFC_RC7_R1_PATH"] = str(context["r1_path"])
    env["PFC_RC7_MISSION_ID"] = str(context["mission_id"])
    env["PFC_RC7_BANK_TARGET_ID"] = str(context["bank_target_id"])
    env["PFC_RC7_QUALIFICATION_DIR"] = str(context["qualification_dir"])
    env.setdefault("PFC_AITEST_STATE_DIR", str(root / "runtime-state" / "rc7-bank-final"))

    if os.name == "nt":
        script = root / "packaging" / "rc7" / "QUALIFY-BANK-FINAL.cmd"
        if not script.is_file():
            raise BankFieldLauncherError("BANK_FINAL_CMD_NOT_FOUND:%s" % script)
        proc = subprocess.run(["cmd.exe", "/d", "/s", "/c", '"%s"' % script], env=env, check=False)
    else:
        script = root / "packaging" / "rc7" / "QUALIFY-BANK-FINAL.sh"
        if not script.is_file():
            raise BankFieldLauncherError("BANK_FINAL_SH_NOT_FOUND:%s" % script)
        proc = subprocess.run(["bash", str(script)], env=env, check=False)
    return int(proc.returncode)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m rc7_release.bank_field_launcher")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("discover", "run"):
        child = sub.add_parser(name)
        child.add_argument("--package-root", default=None)
        child.add_argument("--r1")
        child.add_argument("--mission-id")
        child.add_argument("--target-id")
        child.add_argument("--qualification-dir")
        child.add_argument("--output")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = _package_root(args.package_root)
        resolved = resolve_context(
            package_root=str(root),
            r1_path=args.r1,
            mission_id=args.mission_id,
            target_id=args.target_id,
            qualification_dir=args.qualification_dir,
        )
    except Exception as exc:
        resolved = {
            "schema_version": SCHEMA_VERSION,
            "status": "HOLD",
            "reason": str(exc),
        }
        root = Path(args.package_root or os.environ.get("PFC_AITEST_HOME") or os.getcwd()).expanduser().resolve()

    output = Path(args.output).expanduser().resolve() if args.output else _launcher_output(root)
    _write_json(output, resolved)
    print(json.dumps(resolved, ensure_ascii=False, sort_keys=True))
    if resolved.get("status") != "PASS":
        return 2
    if args.command == "discover":
        return 0

    rc = run_bank_final(resolved)
    final = dict(resolved)
    final["bank_final_exit_code"] = rc
    if rc == 0:
        final["status"] = "BANK_FINAL_PASS"
        final["stage"] = "BANK_FIELD_QUALIFIED"
    elif rc == 3:
        final["status"] = "HUMAN_REQUIRED"
        final["stage"] = "DB_WRITE_HUMAN_GATE"
    else:
        final["status"] = "HOLD"
        final["stage"] = "BANK_FINAL_NOT_QUALIFIED"
    _write_json(output, final)
    print(json.dumps(final, ensure_ascii=False, sort_keys=True))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
