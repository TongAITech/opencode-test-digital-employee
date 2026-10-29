from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Optional, Sequence

from rc7_release.rc72_package import verify_package as verify_rc72_package
from rc7_release.windows_clean_qualification import qualify_with_contract


QUALIFICATION_NAME = "RC72_WINDOWS_CLEAN_PACKAGE"
RELEASE_FAMILY = "RC7.2"
BUSINESS_ROOT = "RELEASE_BATCH"
MISSION_PREFIX = "RC72-WINDOWS-CLEAN"
RELEASE_PREFIX = "RC72-CLEAN-TRANSPORT"
GOAL = "Qualify freshly extracted RC7.2 Windows package R1 durability and Session A-B-C continuity"


def qualify(package_root: Path) -> Dict[str, object]:
    result = dict(
        qualify_with_contract(
            Path(package_root),
            package_verifier=verify_rc72_package,
            qualification_name=QUALIFICATION_NAME,
            mission_prefix=MISSION_PREFIX,
            release_prefix=RELEASE_PREFIX,
            goal=GOAL,
        )
    )
    result.update(
        {
            "qualification": QUALIFICATION_NAME,
            "release_family": RELEASE_FAMILY,
            "business_root": BUSINESS_ROOT,
            "runtime_control_backbone": "N1_N10_MISSION_GRAPH",
            "qualification_scope": "Q2B_WINDOWS_CLEAN_R1_SESSION_CONTINUITY",
            "field_verified": False,
            "target_linux_verified": False,
            "bank_final": False,
            "real_mission_pass": False,
            "bank_field_pass": False,
        }
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Qualify RC7.2 clean Windows package R1/session continuity")
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--output")
    parser.add_argument("--require-pass", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        result = qualify(Path(args.package_root))
    except Exception as exc:
        result = {
            "status": "FAIL",
            "qualification": QUALIFICATION_NAME,
            "release_family": RELEASE_FAMILY,
            "business_root": BUSINESS_ROOT,
            "reason": str(exc),
            "field_verified": False,
            "target_linux_verified": False,
            "bank_final": False,
        }
    text = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)
    if args.output:
        output = Path(args.output)
        if not output.is_absolute():
            output = Path(args.package_root).resolve() / output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if args.require_pass and result.get("status") != "PASS":
        return 2
    return 0 if result.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
