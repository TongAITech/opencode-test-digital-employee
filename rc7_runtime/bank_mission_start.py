"""RC7.1 production BANK Mission start/resume + Autopilot entry.

This is intentionally a thin compatibility layer. The historical BANK Mission
launcher accepted graph/input bootstrap arguments and then stopped after R1
bootstrap. RC7.1 must preserve those exact bootstrap semantics and immediately
hand the same durable Mission to ``BankMissionAutopilot`` so users never need to
send a follow-up "continue" instruction.

No Mission/Target/Autonomous-Run identity is guessed. The legacy bank-target
environment name is accepted only as an alias; conflicting aliases are a HOLD.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Optional, Sequence

from .bank_mission import BankMissionError, MissionTaskGraphCompiler, _parse_inputs, start_or_resume
from .bank_mission_autopilot import (
    BankMissionAutopilot,
    BankMissionAutopilotError,
    discover_config,
)
from .mission_autonomous_driver import MissionAutonomousDriverError


class BankMissionStartError(RuntimeError):
    pass


def _target_id(cli_value: Optional[str]) -> Optional[str]:
    explicit = str(cli_value or "").strip()
    modern = str(os.environ.get("PFC_RC7_TARGET_ID") or "").strip()
    legacy = str(os.environ.get("PFC_RC7_BANK_TARGET_ID") or "").strip()
    if modern and legacy and modern != legacy:
        raise BankMissionStartError(
            "AUTOPILOT_TARGET_ID_ENV_CONFLICT:%s:%s" % (modern, legacy)
        )
    if explicit:
        for env_value in (modern, legacy):
            if env_value and env_value != explicit:
                raise BankMissionStartError(
                    "AUTOPILOT_TARGET_ID_CLI_ENV_CONFLICT:%s:%s" % (explicit, env_value)
                )
        return explicit
    return modern or legacy or None


def _case_provider_config(
    *,
    r1_path: str,
    package_root: Optional[str],
    cli_value: Optional[str],
) -> Optional[str]:
    """Resolve one real CasePreparation provider config without guessing.

    Precedence is explicit CLI, environment, then the canonical packaged field
    binding at ``state/bank-field-providers.json``. The example template is
    never executable authority. Invalid explicit bindings fail before Mission
    bootstrap so a configuration mistake cannot leave a half-started Mission.
    """
    r1 = Path(str(r1_path or "").strip()).expanduser().resolve()
    root = (
        Path(package_root).expanduser().resolve()
        if package_root
        else r1.parent.parent.parent.resolve()
    )
    explicit = str(cli_value or "").strip()
    environment = str(os.environ.get("PFC_RC7_CASE_PROVIDER_CONFIG") or "").strip()

    def resolved(raw: str) -> Path:
        return Path(raw).expanduser().resolve()

    if explicit and environment and resolved(explicit) != resolved(environment):
        raise BankMissionStartError(
            "AUTOPILOT_CASE_PROVIDER_CONFIG_CLI_ENV_CONFLICT:%s:%s"
            % (resolved(explicit), resolved(environment))
        )

    selected_raw = explicit or environment
    if selected_raw:
        selected = resolved(selected_raw)
        example = (root / "packaging" / "rc7" / "bank-field-providers.example.json").resolve()
        if selected == example:
            raise BankMissionStartError(
                "AUTOPILOT_CASE_PROVIDER_EXAMPLE_FORBIDDEN:%s" % selected
            )
        if not selected.is_file():
            raise BankMissionStartError(
                "AUTOPILOT_CASE_PROVIDER_CONFIG_NOT_FOUND:%s" % selected
            )
        os.environ["PFC_RC7_CASE_PROVIDER_CONFIG"] = str(selected)
        return str(selected)

    canonical = (root / "state" / "bank-field-providers.json").resolve()
    if canonical.is_file():
        os.environ["PFC_RC7_CASE_PROVIDER_CONFIG"] = str(canonical)
        return str(canonical)
    return None


def _failure_status(exc: Exception) -> str:
    reason = str(exc).upper()
    if "HUMAN_REQUIRED" in reason:
        return "HUMAN_REQUIRED"
    if "REQUIRED" in reason or "NOT_FOUND" in reason:
        return "FIELD_REQUIRED"
    return "HOLD"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Start/resume one durable RC7.1 BANK Mission and immediately drive Autopilot"
    )
    parser.add_argument("--r1", required=True)
    parser.add_argument("--mission-id", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--goal", required=True)
    parser.add_argument("--run-id")
    parser.add_argument(
        "--graph-version",
        choices=MissionTaskGraphCompiler.SUPPORTED_GRAPH_VERSIONS,
        default=None,
    )
    parser.add_argument("--input", action="append", default=[], metavar="NODE=REF")
    parser.add_argument("--package-root")
    parser.add_argument("--state-root")
    parser.add_argument("--evidence-root")
    parser.add_argument("--dsh-bin")
    parser.add_argument("--patch")
    parser.add_argument("--target-id")
    parser.add_argument("--source-revision")
    parser.add_argument("--repository-ref")
    parser.add_argument("--runtime-profile")
    parser.add_argument("--execution-capability-snapshot")
    parser.add_argument("--case-provider-config")
    parser.add_argument("--max-steps", type=int, default=100)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        target_id = _target_id(args.target_id)
        _case_provider_config(
            r1_path=args.r1,
            package_root=args.package_root,
            cli_value=args.case_provider_config,
        )
        bootstrap = start_or_resume(
            r1_path=args.r1,
            mission_id=args.mission_id,
            release_id=args.release_id,
            goal=args.goal,
            external_inputs=_parse_inputs(args.input),
            graph_version=args.graph_version,
        )
        state_root = args.state_root or os.environ.get("PFC_AITEST_STATE_DIR")
        config = discover_config(
            r1_path=args.r1,
            mission_id=args.mission_id,
            release_id=args.release_id,
            goal=args.goal,
            run_id=args.run_id,
            package_root=args.package_root,
            state_root=state_root,
            evidence_root=args.evidence_root,
            dsh_bin=args.dsh_bin,
            patch_path=args.patch,
            target_id=target_id,
            source_revision=args.source_revision,
            repository_ref=args.repository_ref,
            runtime_profile=args.runtime_profile,
            execution_capability_snapshot=args.execution_capability_snapshot,
            max_steps=args.max_steps,
            timeout_seconds=args.timeout_seconds,
        )
        autopilot = BankMissionAutopilot(config)
        result = autopilot.drive()
        mission = autopilot.control._mission()
    except (
        BankMissionError,
        BankMissionStartError,
        BankMissionAutopilotError,
        MissionAutonomousDriverError,
        OSError,
        ValueError,
    ) as exc:
        payload = {
            "status": _failure_status(exc),
            "reason": str(exc),
            "mission_id": args.mission_id,
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 2

    payload = {
        "status": result.status,
        "mission_id": result.mission_id,
        "run_id": config.run_id,
        "release_id": args.release_id,
        "bootstrap_action": bootstrap.get("status"),
        "graph_version": bootstrap.get("graph_version"),
        "steps": result.step_count,
        "last_action": result.action,
        "task_id": result.task_id,
        "node": result.node,
        "reason": result.reason,
        "mission_state": mission.state.value,
        "sufficiency_state": mission.sufficiency_state,
        "r1_path": str(config.r1_path),
        "target_id": config.target_id,
        "manual_continue_required": False,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if result.status in {
        "CONVERGED",
        "CLOSED",
        "WAITING",
        "HUMAN_REQUIRED",
        "BLOCKED",
    } else 1


if __name__ == "__main__":
    raise SystemExit(main())
