"""One-command exact-HEAD real semantic proof handoff.

This runs only on a host that already has a real OpenCode provider/model/auth
binding. It never copies credentials. The generated proof is validated locally,
uploaded to the existing draft release, then the Windows qualification is
workflow-dispatched with the exact semantic asset identity.

The helper deliberately refuses dirty/unpushed/drifted source. Conversation is
not project truth; the Git HEAD used by the real model must be the same HEAD the
Windows workflow checks out.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


def run(command, *, cwd: Path, timeout: int = 120, capture: bool = False) -> str:
    process = subprocess.run(
        [str(item) for item in command],
        cwd=str(cwd),
        text=True,
        capture_output=capture,
        timeout=timeout,
    )
    if process.returncode:
        detail = (process.stderr or process.stdout or "").strip() if capture else ""
        raise RuntimeError(f"COMMAND_FAILED[{process.returncode}]: {' '.join(map(str, command))}" + (f"\n{detail}" if detail else ""))
    return (process.stdout or "").strip() if capture else ""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def repository_slug(remote: str) -> str:
    value = remote.strip()
    patterns = (
        r"^https://github\.com/(?P<slug>[^/]+/[^/]+?)(?:\.git)?$",
        r"^git@github\.com:(?P<slug>[^/]+/[^/]+?)(?:\.git)?$",
        r"^ssh://git@github\.com/(?P<slug>[^/]+/[^/]+?)(?:\.git)?$",
    )
    for pattern in patterns:
        match = re.match(pattern, value)
        if match:
            return match.group("slug")
    raise ValueError("GITHUB_ORIGIN_REQUIRED")


def semantic_asset_name(source_head: str, digest: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", source_head):
        raise ValueError("INVALID_SOURCE_HEAD")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("INVALID_SEMANTIC_SHA256")
    return f"REC3-REAL-SEMANTIC-{source_head[:12]}-{digest[:12]}.json"


def workflow_dispatch_command(repository: str, branch: str, config: dict, asset: str, digest: str) -> list[str]:
    required = ("draft_release_tag", "asset_name", "expected_sha256")
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise ValueError("CI_PACKAGE_CONFIG_MISSING:" + ",".join(missing))
    return [
        "gh", "workflow", "run", "recovery-windows.yml",
        "--repo", repository,
        "--ref", branch,
        "-f", f"draft_release_tag={config['draft_release_tag']}",
        "-f", f"asset_name={config['asset_name']}",
        "-f", f"expected_sha256={config['expected_sha256']}",
        "-f", f"semantic_asset={asset}",
        "-f", f"semantic_sha256={digest}",
    ]


def payload_candidate_ok(path: Path) -> bool:
    if not (path / ".opencode" / "node_modules").is_dir():
        return False
    if os.name == "nt" and not ((path / "runtime" / "python" / "python.exe").is_file()):
        return False
    return True


def resolve_payload_workspace(repo: Path, explicit: Path | None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(explicit)
    for key in ("AITEST_INSTALLED", "AITEST_WORKSPACE_ROOT"):
        if os.environ.get(key):
            candidates.append(Path(os.environ[key]))
    candidates.extend((repo / "workspace-template", Path.cwd()))
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if payload_candidate_ok(resolved):
            return resolved
    raise RuntimeError("REAL_MODEL_PAYLOAD_WORKSPACE_NOT_FOUND: need .opencode/node_modules from the qualified payload")


def exact_git_identity(repo: Path) -> tuple[str, str, str]:
    head = run(["git", "rev-parse", "HEAD"], cwd=repo, capture=True)
    branch = run(["git", "branch", "--show-current"], cwd=repo, capture=True)
    dirty = run(["git", "status", "--porcelain"], cwd=repo, capture=True)
    if dirty:
        raise RuntimeError("SEMANTIC_SOURCE_MUST_BE_CLEAN")
    if not branch:
        raise RuntimeError("SEMANTIC_SOURCE_BRANCH_REQUIRED")
    remote = run(["git", "config", "--get", "remote.origin.url"], cwd=repo, capture=True)
    slug = repository_slug(remote)
    remote_line = run(["git", "ls-remote", "origin", f"refs/heads/{branch}"], cwd=repo, capture=True)
    remote_head = remote_line.split()[0] if remote_line else ""
    if remote_head != head:
        raise RuntimeError(f"SEMANTIC_SOURCE_NOT_PUSHED_EXACTLY: local={head} remote={remote_head or 'MISSING'}")
    return head, branch, slug


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate, upload and dispatch exact-HEAD REC3 real semantic proof")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--payload-workspace", type=Path)
    parser.add_argument("--host-opencode", type=Path)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--no-dispatch", action="store_true", help="Generate and upload proof but do not dispatch Windows qualification")
    args = parser.parse_args()

    repo = args.repo.resolve()
    head, branch, slug = exact_git_identity(repo)
    config = json.loads((repo / "tools" / "recovery" / "ci-package.json").read_text(encoding="utf-8"))
    payload = resolve_payload_workspace(repo, args.payload_workspace)
    host = args.host_opencode.expanduser().resolve() if args.host_opencode else None
    if host is None:
        found = shutil.which("opencode") or shutil.which("opencode.exe")
        host = Path(found).resolve() if found else None
    if host is None or not host.is_file():
        raise RuntimeError("REAL_HOST_OPENCODE_NOT_FOUND")

    gh = shutil.which("gh") or shutil.which("gh.exe")
    if not gh:
        raise RuntimeError("GH_CLI_REQUIRED")
    run([gh, "auth", "status", "--hostname", "github.com"], cwd=repo, timeout=30)

    with tempfile.TemporaryDirectory(prefix=f"rec3-real-semantic-{head[:12]}-") as directory:
        work = Path(directory)
        proof_run = work / "run"
        harness = repo / "tools" / "recovery" / "qualify_real_model.py"
        run(
            [
                sys.executable, harness,
                "--repo", repo,
                "--payload-workspace", payload,
                "--output", proof_run,
                "--host-opencode", host,
                "--timeout", str(args.timeout),
            ],
            cwd=repo,
            timeout=args.timeout + 180,
        )
        proof = proof_run / "result.json"
        if not proof.is_file():
            raise RuntimeError("REAL_SEMANTIC_PROOF_MISSING")

        # Validate the same identity contract Windows qualification will enforce.
        sys.path.insert(0, str(repo / "tools" / "recovery"))
        from semantic_evidence import admit_semantic_report
        admitted = admit_semantic_report(proof, head, harness)
        digest = admitted["sha256"]
        asset_name = semantic_asset_name(head, digest)
        asset = work / asset_name
        shutil.copy2(proof, asset)

        # Recheck source and remote branch after the model run. A proof is invalid
        # if source moved while semantic planning was in flight.
        head_after, branch_after, slug_after = exact_git_identity(repo)
        if (head_after, branch_after, slug_after) != (head, branch, slug):
            raise RuntimeError("SEMANTIC_SOURCE_DRIFT_DURING_PROOF")

        release_tag = str(config.get("draft_release_tag") or "")
        if not release_tag:
            raise RuntimeError("DRAFT_RELEASE_TAG_REQUIRED")
        run([gh, "release", "upload", release_tag, str(asset), "--clobber", "--repo", slug], cwd=repo, timeout=180)

        dispatch = workflow_dispatch_command(slug, branch, config, asset_name, digest)
        if not args.no_dispatch:
            run([gh, *dispatch[1:]], cwd=repo, timeout=60)

        print(json.dumps({
            "status": "PASS",
            "source_head": head,
            "source_branch": branch,
            "semantic_asset": asset_name,
            "semantic_sha256": digest,
            "release_tag": release_tag,
            "windows_dispatch": "SUBMITTED" if not args.no_dispatch else "SKIPPED",
            "bank_field_validation_required": True,
            "credential_copy": False,
        }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
