from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = "pfc.aitest.rc6.workspace-install.v1"
PROFILE_SCHEMA_VERSION = "pfc.aitest.rc6.agent-profile.v1"
PROFILE_DIR = Path(".dsh") / "rc6"
MANIFEST_NAME = "INSTALL_MANIFEST.json"
AGENT_PROFILE_NAME = "AGENT_PROFILE.json"
BACKUP_DIR = ".aitest-backup"

# RC6 professional agents are fresh DSH Worker sessions. Their reusable role
# instructions are project-scoped DSH Skills installed into D:\\PFC\\.dsh\\skills.
# The runtime agent_id and Skill name are intentionally identical so routing and
# provenance are auditable without inventing an unsupported .dsh/agents format.
ROLE_DESCRIPTIONS = {
    "pfc-requirement-analysis": "Analyze BR/SR/TR and atomic testable requirements with rules, roles, paths, boundaries, states, data, dependencies, side effects and trace evidence.",
    "pfc-requirement-sufficiency": "Independently review requirement analysis for completeness and evidence; return explicit gaps and never self-repair the analyzed artifact.",
    "pfc-code-analysis": "Analyze exact revision and change impact using admitted CodeGraph/Git/source evidence; map requirements to symbols, call paths, routes, data and risk.",
    "pfc-code-sufficiency": "Independently review code-analysis reachability, requirement mapping, changed-symbol coverage, call paths and evidence; return gaps only.",
    "pfc-test-fusion": "Fuse requirement and code truth into Test Intents/Test Conditions and evidence-backed L1-L7 applicability before layer design.",
    "pfc-l1-test-design": "Design code/unit cases with method, branch, boundary, exception and deterministic oracle coverage; never mix layers.",
    "pfc-l2-test-design": "Design DB/component/internal-integration cases with SQL, transaction, state, consistency and cleanup oracles; never mix layers.",
    "pfc-l3-test-design": "Design API/service-integration cases with authoritative route, schema, auth, business/error, negative and boundary oracles; never guess endpoints.",
    "pfc-l4-test-design": "Design browser/UI cases with page, control, state and network evidence plus real 4A prerequisites; never mix layers.",
    "pfc-l5-test-design": "Design cross-system E2E journeys with handoff, state consistency, recovery and end-state oracles; never mix layers.",
    "pfc-l6-test-design": "Design performance/workload cases with workload model, SLO, latency/error/resource oracles and admitted tooling.",
    "pfc-l7-test-design": "Design bounded security cases from attack surface and controls with authorized probes and evidence-backed oracles.",
    "pfc-automation-engineer": "Resolve reusable automation first, then build deterministic pytest/JUnit automation from frozen executable specs; generated is not ready until validation passes.",
    "pfc-test-data": "Construct and verify preconditions, test data and cleanup for one PreparedAttempt using authoritative DB/API/runtime facts.",
    "pfc-l1-test-execution": "Execute validated L1 automation with real admitted runner and persist actual/oracle/evidence; no simulated success.",
    "pfc-l2-test-execution": "Execute validated L2 DB/component cases against the bound target and PreparedAttempt; persist transaction/state/SQL evidence and cleanup.",
    "pfc-l3-test-execution": "Execute validated L3 API cases against authoritative route/auth target; persist request/response/business/oracle evidence and CAT correlation when applicable.",
    "pfc-l4-test-execution": "Execute validated L4 browser/UI cases using admitted browser automation and real 4A state; persist page/network/oracle evidence.",
    "pfc-l5-test-execution": "Execute bound E2E journeys across systems, preserving correlation/state evidence and end-state oracle.",
    "pfc-l6-test-execution": "Execute admitted workload/performance run and persist workload identity, samples, thresholds, SLO result and evidence.",
    "pfc-l7-test-execution": "Execute authorized bounded security probes and persist request/control/result evidence; stop on authorization ambiguity.",
    "pfc-failure-diagnosis": "Classify failure ownership with stable FailureSignature, CAT/runner evidence and CodeGraph/Git/requirement context; assertion failure alone is never PRODUCT.",
    "pfc-recovery": "Execute only runtime-selected recovery, verify side effects, append a fresh Attempt and obey retry budgets; never silently change an oracle.",
    "pfc-defect-review": "Confirm PRODUCT only after competing script/spec/oracle/data/auth/route/tool/environment/dependency causes are proven correct; create stable defect evidence.",
    "pfc-report": "Derive status/report only from R1 truth and canonical evidence; reconcile identities/counts and never promote engineering proof to BANK_FINAL.",
}

ACTIVE_SKILL_ROOTS = (Path(".dsh") / "skills", Path(".agents") / "skills")
LEGACY_OBSERVATION_ROOTS = (Path(".opencode") / "skills", Path(".opencode") / "agents")


class WorkspaceInstallError(RuntimeError):
    pass


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _render_role_skill(name: str, description: str) -> str:
    return """---\nname: {name}\ndescription: RC6 professional Worker role. {description}\n---\n\n# RC6 {name}\n\nThis is an RC6 governed professional Worker, not the Coordinator.\n\n- Use only runtime-issued Mission/Worker/Lease scope and admitted tools.\n- R1 Event Stream and R1-backed artifact refs are the only durable test truth.\n- Read routes/revisions/DB/auth/4A/CAT/tool readiness from Bank Reality/Capability Broker; never guess.\n- Produce evidence-backed structured handoff output; missing evidence fails closed.\n- Stay in this role and route gaps through Runtime; never impersonate another role.\n- Release status remains ENGINEERING_CANDIDATE_NOT_BANK_FINAL until real bank gates pass.\n\nProfessional responsibility: {description}\n""".format(name=name, description=description)


def _payload(package_root: Path) -> Dict[str, str]:
    full = package_root / ".dsh" / "skills" / "pfc-full-chain-test" / "SKILL.md"
    if not full.is_file():
        raise WorkspaceInstallError("RC6_COORDINATOR_SKILL_PAYLOAD_MISSING")
    result = {name: _render_role_skill(name, desc) for name, desc in ROLE_DESCRIPTIONS.items()}
    result["pfc-full-chain-test"] = full.read_text(encoding="utf-8")
    return result


def _source_commit(package_root: Path) -> str:
    path = package_root / "SOURCE_COMMIT"
    if not path.is_file():
        raise WorkspaceInstallError("SOURCE_COMMIT_MISSING")
    value = path.read_text(encoding="utf-8").strip()
    if len(value) < 12:
        raise WorkspaceInstallError("SOURCE_COMMIT_INVALID")
    return value


def _managed_entries(root: Path) -> List[Path]:
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.name.startswith("pfc-") and (p.is_dir() or p.is_file()))


def _read_manifest(workspace: Path) -> Optional[Dict[str, Any]]:
    path = workspace / PROFILE_DIR / MANIFEST_NAME
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _has_history(workspace: Path) -> bool:
    roots = ACTIVE_SKILL_ROOTS + LEGACY_OBSERVATION_ROOTS
    return any(_managed_entries(workspace / rel) for rel in roots) or (workspace / PROFILE_DIR / MANIFEST_NAME).is_file()


def _mode(workspace: Path, source_commit: str) -> str:
    manifest = _read_manifest(workspace)
    if manifest and manifest.get("schema_version") == SCHEMA_VERSION:
        return "RC6_REPAIR" if manifest.get("source_commit") == source_commit else "UPGRADE_FROM_RC6"
    return "UPGRADE_FROM_LEGACY" if _has_history(workspace) else "FRESH_INSTALL"


def _copy(src: Path, dst: Path) -> None:
    if src.is_dir():
        shutil.copytree(str(src), str(dst))
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))


def _backup(workspace: Path) -> Optional[Path]:
    items: List[Tuple[Path, Path]] = []
    for rel in ACTIVE_SKILL_ROOTS + LEGACY_OBSERVATION_ROOTS:
        for item in _managed_entries(workspace / rel):
            items.append((item, rel / item.name))
    profile = workspace / PROFILE_DIR
    if profile.is_dir():
        items.append((profile, PROFILE_DIR))
    if not items:
        return None
    out = workspace / BACKUP_DIR / ("rc6-install-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
    for src, rel in items:
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        _copy(src, dst)
    return out


def _clear_active(workspace: Path) -> None:
    for rel in ACTIVE_SKILL_ROOTS:
        for item in _managed_entries(workspace / rel):
            shutil.rmtree(str(item)) if item.is_dir() else item.unlink()
    profile = workspace / PROFILE_DIR
    if profile.is_dir():
        shutil.rmtree(str(profile))


def _restore(workspace: Path, backup: Optional[Path]) -> None:
    _clear_active(workspace)
    if not backup or not backup.is_dir():
        return
    for rel in ACTIVE_SKILL_ROOTS + (PROFILE_DIR,):
        src = backup / rel
        if not src.exists():
            continue
        dst = workspace / rel
        if rel == PROFILE_DIR:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(str(src), str(dst))
        else:
            dst.mkdir(parents=True, exist_ok=True)
            for item in src.iterdir():
                _copy(item, dst / item.name)


def _write_json(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(value, fh, ensure_ascii=False, sort_keys=True, indent=2)
        fh.write("\n")


def verify_workspace(package_root: str | Path, workspace: str | Path) -> Dict[str, Any]:
    package, work = Path(package_root).resolve(), Path(workspace).resolve()
    source_commit, payload = _source_commit(package), _payload(package)
    root = work / ".dsh" / "skills"
    active = {p.name for p in _managed_entries(root)}
    if active != set(payload):
        raise WorkspaceInstallError("RC6_ACTIVE_SKILL_SET_MISMATCH")
    for name, text in payload.items():
        path = root / name / "SKILL.md"
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != _sha_text(text):
            raise WorkspaceInstallError("RC6_SKILL_HASH_MISMATCH:%s" % name)
    if _managed_entries(work / ".agents" / "skills"):
        raise WorkspaceInstallError("LEGACY_PFC_PROJECT_AGENT_SKILLS_STILL_ACTIVE")
    manifest = _read_manifest(work)
    if not manifest or manifest.get("source_commit") != source_commit:
        raise WorkspaceInstallError("RC6_INSTALL_MANIFEST_INVALID")
    profile_path = work / PROFILE_DIR / AGENT_PROFILE_NAME
    if not profile_path.is_file():
        raise WorkspaceInstallError("RC6_AGENT_PROFILE_MISSING")
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    agents = {x.get("agent_id") for x in profile.get("agents", []) if isinstance(x, dict)}
    if agents != set(ROLE_DESCRIPTIONS):
        raise WorkspaceInstallError("RC6_AGENT_PROFILE_BINDING_MISMATCH")
    return {
        "status": "PASS",
        "workspace": str(work),
        "source_commit": source_commit,
        "install_mode": manifest.get("install_mode"),
        "skill_count": len(payload),
        "agent_count": len(agents),
        "rc6_agent_install": "PASS",
        "rc6_skill_install": "PASS",
        "legacy_rc5_pfc_active": False,
        "rc6_profile_active": "PASS",
    }


def install_workspace(package_root: str | Path, workspace: str | Path) -> Dict[str, Any]:
    package, work = Path(package_root).resolve(), Path(workspace).resolve()
    work.mkdir(parents=True, exist_ok=True)
    source_commit, payload = _source_commit(package), _payload(package)
    mode, backup = _mode(work, source_commit), _backup(work)
    try:
        _clear_active(work)
        root = work / ".dsh" / "skills"
        root.mkdir(parents=True, exist_ok=True)
        hashes: Dict[str, str] = {}
        for name, text in payload.items():
            path = root / name / "SKILL.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
            hashes[name] = _sha_text(text)
        _write_json(
            work / PROFILE_DIR / AGENT_PROFILE_NAME,
            {
                "schema_version": PROFILE_SCHEMA_VERSION,
                "source_commit": source_commit,
                "agent_runtime": "DSH_HEADLESS_FRESH_AGENT",
                "worker_skill_binding_required": True,
                "coordinator_skill": "pfc-full-chain-test",
                "agents": [
                    {"agent_id": name, "skill": name, "source": "workspace-project-dsh"}
                    for name in ROLE_DESCRIPTIONS
                ],
            },
        )
        _write_json(
            work / PROFILE_DIR / MANIFEST_NAME,
            {
                "schema_version": SCHEMA_VERSION,
                "source_commit": source_commit,
                "install_mode": mode,
                "installed_at_epoch": int(time.time()),
                "workspace": str(work),
                "active_skill_root": str(root),
                "skill_hashes": hashes,
                "backup_path": str(backup) if backup else None,
                "release_status": "ENGINEERING_CANDIDATE_NOT_BANK_FINAL",
            },
        )
        result = verify_workspace(package, work)
        result["backup_path"] = str(backup) if backup else None
        return result
    except Exception:
        _restore(work, backup)
        raise


def rollback_workspace(workspace: str | Path, backup: Optional[str] = None) -> Dict[str, Any]:
    work = Path(workspace).resolve()
    chosen = Path(backup).resolve() if backup else None
    if chosen is None:
        root = work / BACKUP_DIR
        choices = sorted((p for p in root.iterdir() if p.is_dir()), reverse=True) if root.is_dir() else []
        chosen = choices[0] if choices else None
    if chosen is None or not chosen.is_dir():
        raise WorkspaceInstallError("ROLLBACK_BACKUP_NOT_FOUND")
    _restore(work, chosen)
    return {"status": "PASS", "workspace": str(work), "restored_from": str(chosen)}


def _default_workspace() -> str:
    return os.environ.get("PFC_WORKSPACE") or (r"D:\PFC" if os.name == "nt" else "/d/PFC")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m rc6_release.workspace_install")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("install", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--package-root", required=True)
        p.add_argument("--workspace", default=_default_workspace())
    rb = sub.add_parser("rollback")
    rb.add_argument("--workspace", default=_default_workspace())
    rb.add_argument("--backup")
    args = parser.parse_args(argv)
    if args.command == "install":
        result = install_workspace(args.package_root, args.workspace)
    elif args.command == "verify":
        result = verify_workspace(args.package_root, args.workspace)
    else:
        result = rollback_workspace(args.workspace, args.backup)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
