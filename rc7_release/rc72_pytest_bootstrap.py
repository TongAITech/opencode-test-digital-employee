"""Deterministically bootstrap the RC7.2 qualification pytest dependency.

The platform qualification must not hang indefinitely on a package download.
Reuse the pinned pytest version when already available; otherwise install the
pinned requirement with bounded pip network/retry settings and a process-level
hard timeout.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence


def _requirement(path: str) -> str:
    values = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            values.append(line)
    if len(values) != 1 or not values[0].startswith("pytest=="):
        raise ValueError("RC72_PYTEST_BOOTSTRAP_REQUIREMENT_INVALID")
    return values[0]


def _installed_version() -> Optional[str]:
    try:
        import pytest  # type: ignore
    except ImportError:
        return None
    return str(getattr(pytest, "__version__", "") or "").strip() or None


def ensure_pytest(requirements: str, *, timeout_seconds: int = 120) -> int:
    if timeout_seconds < 1:
        raise ValueError("timeout_seconds must be >= 1")
    requirement = _requirement(requirements)
    expected = requirement.split("==", 1)[1]
    installed = _installed_version()
    if installed == expected:
        print("RC72_PYTEST_BOOTSTRAP_REUSE::pytest==%s" % installed, flush=True)
        return 0

    print(
        "RC72_PYTEST_BOOTSTRAP_INSTALL::%s::current=%s::timeout=%ss"
        % (requirement, installed or "missing", timeout_seconds),
        flush=True,
    )
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        "--retries",
        "1",
        "--timeout",
        "20",
        requirement,
    ]
    try:
        completed = subprocess.run(command, check=False, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        print(
            "RC72_PYTEST_BOOTSTRAP_TIMEOUT::%s::timeout=%ss"
            % (requirement, timeout_seconds),
            flush=True,
        )
        return 124
    if completed.returncode != 0:
        print(
            "RC72_PYTEST_BOOTSTRAP_FAIL::%s::exit=%s"
            % (requirement, completed.returncode),
            flush=True,
        )
        return completed.returncode or 1

    installed = _installed_version()
    if installed != expected:
        print(
            "RC72_PYTEST_BOOTSTRAP_VERSION_MISMATCH::expected=%s::actual=%s"
            % (expected, installed or "missing"),
            flush=True,
        )
        return 2
    print("RC72_PYTEST_BOOTSTRAP_READY::pytest==%s" % installed, flush=True)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirements", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    args = parser.parse_args(argv)
    return ensure_pytest(
        args.requirements,
        timeout_seconds=args.timeout_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
