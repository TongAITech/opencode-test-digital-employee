from __future__ import annotations

import argparse
import json
import platform
import sys
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Sequence


SCHEMA = "pfc.aitest.rc7.2.platform-source-baseline.v1"


class QualificationKind(str, Enum):
    WINDOWS_ENGINEERING = "WINDOWS_ENGINEERING"
    LINUX_ENGINEERING_PROXY = "LINUX_ENGINEERING_PROXY"


def _required_text(name: str, value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("%s must not be blank" % name)
    return normalized


def build_source_platform_evidence(
    *,
    qualification_kind: QualificationKind,
    source_commit: str,
    platform_family: str,
    platform_release: str,
    architecture: str,
    python_version: str,
) -> Dict[str, object]:
    if not isinstance(qualification_kind, QualificationKind):
        qualification_kind = QualificationKind(str(qualification_kind))

    source_commit = _required_text("source_commit", source_commit)
    platform_family = _required_text("platform_family", platform_family)
    platform_release = _required_text("platform_release", platform_release)
    architecture = _required_text("architecture", architecture)
    python_version = _required_text("python_version", python_version)

    notes: List[str] = [
        "Q1 is a repository engineering portability gate only.",
        "Evidence is emitted only after the workflow contract/regression steps succeed.",
        "This evidence does not prove in-bank Field execution or BANK_FINAL readiness.",
    ]
    if qualification_kind is QualificationKind.LINUX_ENGINEERING_PROXY:
        notes.append("Linux GitHub runner is an engineering proxy only; it is not target Linux qualification.")
    else:
        notes.append("Windows GitHub runner is engineering evidence; bank-PC confirmation remains separate.")

    return {
        "schema": SCHEMA,
        "qualification_id": "Q1-%s-%s" % (qualification_kind.value, source_commit[:12]),
        "qualification_kind": qualification_kind.value,
        "source_commit": source_commit,
        "platform_family": platform_family,
        "platform_release": platform_release,
        "architecture": architecture,
        "python_version": python_version,
        "status": "PASS",
        "evidence_scope": "SOURCE_PLATFORM_POST_TEST_MARKER",
        "evidence_refs": [
            "rc72-platform-contracts.xml",
            "rc7-inherited-regression.xml",
        ],
        "field_verified": False,
        "target_linux_verified": False,
        "bank_final": False,
        "notes": notes,
    }


def _detect_runtime() -> Dict[str, str]:
    return {
        "platform_family": platform.system() or "UNKNOWN",
        "platform_release": platform.release() or "UNKNOWN",
        "architecture": platform.machine() or "UNKNOWN",
        "python_version": platform.python_version(),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit RC7.2 Q1 source-platform qualification evidence after tests pass."
    )
    parser.add_argument(
        "--qualification-kind",
        required=True,
        choices=[item.value for item in QualificationKind],
    )
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    runtime = _detect_runtime()
    evidence = build_source_platform_evidence(
        qualification_kind=QualificationKind(args.qualification_kind),
        source_commit=args.source_commit,
        platform_family=runtime["platform_family"],
        platform_release=runtime["platform_release"],
        architecture=runtime["architecture"],
        python_version=runtime["python_version"],
    )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
