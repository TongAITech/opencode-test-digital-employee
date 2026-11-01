"""Run RC7.2 qualification pytest files one-by-one with a hard timeout.

This runner intentionally uses only the Python standard library so the Windows
engineering qualification cannot hang indefinitely inside one opaque pytest
process. Each file gets its own JUnit report and an explicit start/pass/fail
marker, making the offending file visible in GitHub Actions diagnostics.
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Sequence


def _safe_stem(path: str) -> str:
    stem = Path(path).stem
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", stem).strip("-") or "pytest-file"


def discover(pattern: str) -> List[str]:
    return sorted(path for path in glob.glob(pattern) if os.path.isfile(path))


def run_files(
    files: Sequence[str],
    *,
    timeout_seconds: int,
    junit_dir: str,
    pytest_args: Sequence[str] = (),
) -> int:
    if timeout_seconds < 1:
        raise ValueError("timeout_seconds must be >= 1")
    if not files:
        raise ValueError("no pytest files supplied")

    os.makedirs(junit_dir, exist_ok=True)
    failures = 0
    for path in files:
        report = os.path.join(junit_dir, "%s.xml" % _safe_stem(path))
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--strict-markers",
            "--junitxml=%s" % report,
        ] + list(pytest_args) + [path]
        print(
            "RC72_BOUNDED_PYTEST_START::%s::timeout=%ss" % (path, timeout_seconds),
            flush=True,
        )
        try:
            completed = subprocess.run(command, timeout=timeout_seconds, check=False)
        except subprocess.TimeoutExpired:
            failures += 1
            print(
                "RC72_BOUNDED_PYTEST_TIMEOUT::%s::timeout=%ss" % (path, timeout_seconds),
                flush=True,
            )
            continue

        if completed.returncode != 0:
            failures += 1
            print(
                "RC72_BOUNDED_PYTEST_FAIL::%s::exit=%s"
                % (path, completed.returncode),
                flush=True,
            )
        else:
            print("RC72_BOUNDED_PYTEST_PASS::%s" % path, flush=True)

    if failures:
        print("RC72_BOUNDED_PYTEST_RESULT::FAIL::count=%s" % failures, flush=True)
        return 1
    print("RC72_BOUNDED_PYTEST_RESULT::PASS::count=%s" % len(files), flush=True)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pattern", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--junit-dir", required=True)
    args = parser.parse_args(argv)

    files = discover(args.pattern)
    if not files:
        print("RC72_BOUNDED_PYTEST_NO_FILES::%s" % args.pattern, file=sys.stderr)
        return 2
    return run_files(
        files,
        timeout_seconds=args.timeout_seconds,
        junit_dir=args.junit_dir,
    )


if __name__ == "__main__":
    raise SystemExit(main())
