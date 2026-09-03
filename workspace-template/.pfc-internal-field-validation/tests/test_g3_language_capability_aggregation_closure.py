from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
WORKSPACE = HERE.parents[2]
RUNTIME = WORKSPACE / "ai-test" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from aitest_runtime.g3.code_intelligence import analyze_repository


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, encoding="utf-8")
    return proc.stdout.strip()


def make_repo(root: Path, files: dict[str, tuple[str, str]]) -> tuple[Path, str, str]:
    repo = root / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-b", "master")
    git(repo, "config", "user.email", "closure@example.invalid")
    git(repo, "config", "user.name", "Closure Test")
    for rel, (before, _after) in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(before, encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")
    for rel, (_before, after) in files.items():
        (repo / rel).write_text(after, encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "head")
    head = git(repo, "rev-parse", "HEAD")
    return repo, base, head


def main() -> int:
    checks: dict[str, bool] = {}
    files = {
        # Partial files sort before available-only files so the old last-file-wins
        # implementation incorrectly ended each language at AVAILABLE.
        "src/a_partial.java": (
            "class A {\n  int apply(int x) { return x + 1; }\n}\n",
            "class A {\n  public int apply(int x) { return x + 2; }\n}\n",
        ),
        "src/z_available.java": (
            "class Z {\n  // before\n}\n",
            "class Z {\n  // after\n}\n",
        ),
        "src/a_partial.ts": (
            "function apply(x: number) { return x + 1 }\n",
            "export function apply(x: number) { return x + 2 }\n",
        ),
        "src/z_available.ts": (
            "// before\nexport const stable = 1\n",
            "// after\nexport const stable = 1\n",
        ),
        "src/a_partial.vue": (
            "<script setup lang=\"ts\">\nfunction apply(x: number) { return x + 1 }\n</script>\n<template><div>same</div></template>\n",
            "<script setup lang=\"ts\">\nexport function apply(x: number) { return x + 2 }\n</script>\n<template><div>same</div></template>\n",
        ),
        "src/z_available.vue": (
            "<script setup lang=\"ts\">\nconst stable = 1\n</script>\n<template><div>before</div></template>\n",
            "<script setup lang=\"ts\">\nconst stable = 1\n</script>\n<template><div>after</div></template>\n",
        ),
    }
    with tempfile.TemporaryDirectory(prefix="g3-closure-lang-") as td:
        repo, base, head = make_repo(Path(td), files)
        _request, envelope, metadata = analyze_repository({
            "repository_id": "closure-lang",
            "repository_path": str(repo),
            "base_ref": base,
            "head_ref": head,
        })
        caps = metadata["provider_capabilities"]
        checks["java_partial_not_overwritten_by_later_available"] = caps.get("JAVA") == "PARTIAL"
        checks["typescript_partial_not_overwritten_by_later_available"] = caps.get("TYPESCRIPT") == "PARTIAL"
        checks["vue_partial_not_overwritten_by_later_available"] = caps.get("VUE") == "PARTIAL"
        checks["repository_structural_status_remains_partial"] = envelope.code_intelligence_status == "PARTIAL" and metadata["status"] == "PARTIAL"
        checks["git_change_truth_still_contains_all_six_files"] = len(envelope.changed_files) == 6

    failed = [key for key, value in checks.items() if not value]
    print(json.dumps({"status": "PASS" if not failed else "FAIL", "passed": sum(checks.values()), "total": len(checks), "failed": failed, "checks": checks}, indent=2, sort_keys=True))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
