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


def qualify(package_root: Path, *, bank_field=False, bank_pip_field_config=None, archive=None,
            pip_evidence_root=None, bridge_user_config=False) -> Dict[str, object]:
    requested_field=bool(bank_field or bank_pip_field_config or archive or pip_evidence_root or bridge_user_config)
    if requested_field and not all((bank_pip_field_config,archive,pip_evidence_root)):
        return dict(status='FAIL',qualification=QUALIFICATION_NAME,release_family=RELEASE_FAMILY,
            reason='BANK_PC_PIP_MIRROR_GATE_CONFIGURATION_REQUIRED',
            bank_pc_pip_mirror_gate=dict(status='NOT_RUN'),field_verified=False,bank_final=False)
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
    if requested_field:
        from .bank_pc_pip_mirror_probe import qualify as qualify_mirror
        if result.get('status')!='PASS':
            result['bank_pc_pip_mirror_gate']=dict(status='NOT_RUN',reason='CLEAN_PACKAGE_NOT_PASS')
            return result
        mirror=qualify_mirror(package_root,archive,json.loads(Path(bank_pip_field_config).read_text(encoding='utf-8')),
            pip_evidence_root,bridge=bridge_user_config)
        result['bank_pc_pip_mirror_gate']=mirror
        if mirror.get('status')!='PASS' or mirror.get('bank_pc_mirror_field_fact') is not True:
            result.update(status='FAIL',reason='BANK_PC_PIP_MIRROR_GATE_NOT_FIELD_PASS')
        result['qualification_scope']='Q2B_WINDOWS_CLEAN_PLUS_BANK_PC_PIP_MIRROR_FACT'
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Qualify RC7.2 clean Windows package R1/session continuity")
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--output")
    parser.add_argument("--require-pass", action="store_true")
    parser.add_argument('--bank-field',action='store_true')
    parser.add_argument('--bank-pip-field-config')
    parser.add_argument('--archive')
    parser.add_argument('--pip-evidence-root')
    parser.add_argument('--bridge-user-config',action='store_true')
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        result = qualify(Path(args.package_root),bank_field=args.bank_field,bank_pip_field_config=args.bank_pip_field_config,
            archive=args.archive,pip_evidence_root=args.pip_evidence_root,bridge_user_config=args.bridge_user_config)
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
