"""Canonical RC7.2 status and native run/continuation entry."""
import argparse
import json
import re
from pathlib import Path

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_release_driver import release_batch_status
from rc7_runtime.models import ContractError


def main(argv=None):
    parser = argparse.ArgumentParser(description='RC7.2 ReleaseBatch mission')
    parser.add_argument('command', choices=['status', 'run', 'mirror-check'])
    parser.add_argument('--ledger', required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--release-batch', required=True)
    parser.add_argument('--release-id')
    parser.add_argument('--bindings-module')
    parser.add_argument('--mission-config')
    parser.add_argument('--package-root')
    parser.add_argument('--evidence-root')
    parser.add_argument('--economy-config', help='trusted JSON for bank cost windows and soft mission economy targets')
    parser.add_argument('--bridge-user-config', action='store_true')
    parser.add_argument('--retry-returned-failure', action='store_true')
    args = parser.parse_args(argv)
    if args.command != 'run' and args.economy_config:
        parser.error('economy-config is only valid for run')
    if args.command != 'mirror-check' and (args.bridge_user_config or args.retry_returned_failure):
        parser.error('mirror options require mirror-check')
    path = Path(args.ledger).expanduser().resolve()
    if not path.is_file():
        parser.error('existing canonical ledger required')
    truth = TruthRuntime(path)
    if args.command == 'status':
        result = release_batch_status(truth, source_commit=args.source_commit, release_batch_id=args.release_batch)
    else:
        if not all((args.release_id, args.package_root, args.evidence_root)) or bool(args.bindings_module) == bool(args.mission_config):
            parser.error('run requires release-id, package-root, evidence-root and exactly one of mission-config or bindings-module')
        root = Path(args.package_root).expanduser().resolve()
        source = root/'SOURCE_COMMIT'
        if not source.is_file() or source.read_text(encoding='utf-8').strip() != args.source_commit:
            parser.error('run requires the exact package source commit')
        # Validate the existing canonical batch before loading any host module.
        snapshot = release_batch_status(truth, source_commit=args.source_commit, release_batch_id=args.release_batch)
        if snapshot['release_id'] != args.release_id:
            parser.error('run release does not match canonical batch')
        from dataclasses import fields
        from rc7_release.rc72_mission_bindings import load_mission_bindings
        from rc7_runtime.rc72_mission_factory import create_mission_driver
        try:
            # Removing a manifest cannot downgrade a historically full package
            # into the component engineering path before host/model loading.
            prior_full = any(row.get('binding',{}).get('package_root') == str(root)
                and row.get('binding',{}).get('full_package_verified') is True
                for row in truth.query('rc72_bank_pip_mirror_execution',release_batch_id=args.release_batch))
            if (root/'PACKAGE_MANIFEST.json').is_file() or prior_full:
                from rc7_release.rc72_package import verify_package
                from rc7_release.rc72_complete_payload_inventory import verify_inventory
                verify_package(root,expected_source_commit=args.source_commit)
                verify_inventory(root)
            if args.mission_config:
                from rc7_release.rc72_configured_mission import configured_mission_bindings
                bindings = configured_mission_bindings(truth, release_id=args.release_id,
                    source_commit=args.source_commit, config_path=args.mission_config)
            else:
                bindings = load_mission_bindings(args.bindings_module, truth=truth,
                    release_id=args.release_id, source_commit=args.source_commit)
            if args.command == 'run':
                # C10: bind actual native model process boundaries before Factory
                # dispatch, preserving its exact worker-type/authority guards.
                # Mirror-check has no LLM and must not create economy receipts.
                from rc7_runtime.rc72_production_economy_ingress import (
                    bind_release_batch_model_economy, read_mission_economy_config,
                )
                bind_release_batch_model_economy(
                    truth, workers=bindings.workers, release_id=args.release_id,
                    mission_id=snapshot['mission_id'],
                    policy=read_mission_economy_config(args.economy_config),
                )
            driver = create_mission_driver(truth, release_id=args.release_id, source_commit=args.source_commit,
                evidence_root=Path(args.evidence_root).expanduser().resolve(),
                **{f.name: getattr(bindings, f.name) for f in fields(bindings)})
            if driver.bank_pip_mirror.root != root:
                raise ContractError('MISSION_RUNNING_PACKAGE_MIRROR_SCOPE_MISMATCH')
            if args.command == 'mirror-check':
                result = driver.bank_pip_mirror.run(release_batch_id=args.release_batch,
                    bridge_user_config=args.bridge_user_config,retry_returned_failure=args.retry_returned_failure)
                result = dict(result,field_verified=False,bank_final=False)
            else:
                result = driver.run(release_batch_id=args.release_batch)
                economy_result = economy.field_qualification(snapshot['mission_id'])
                # Functional ReleaseBatch truth and model efficiency are
                # independent. Never infer N10 convergence from low cost or
                # an optimistic driver label without all canonical N-nodes.
                node_rows = truth.query('rc72_mission_node', mission_id=snapshot['mission_id'])
                n10_pass = any(
                    row.get('node_type') == 'N10_RELEASE_CONVERGENCE'
                    and row.get('state') == 'PASS'
                    for row in node_rows
                )
                all_nodes_pass = bool(node_rows) and all(
                    row.get('state') == 'PASS' for row in node_rows
                )
                mission_complete = (
                    result.get('status') == 'PASS' and n10_pass and all_nodes_pass
                )
                result = dict(
                    result,
                    MISSION_COMPLETION_STATUS='PASS' if mission_complete else 'HOLD',
                    MODEL_ECONOMY_STATUS=economy_result.status,
                    MODEL_ECONOMY_REASON=economy_result.reason,
                    MODEL_USAGE_TOTAL_STATUS=economy_result.metrics.get('usage_total_status', 'UNKNOWN'),
                    ACTUAL_TOTAL_TOKENS=economy_result.metrics.get('actual_total_tokens'),
                    DSH_PROCESS_INVOCATIONS=economy_result.metrics.get('dsh_process_invocations'),
                    PROVIDER_INFERENCE_CALL_COUNT=economy_result.metrics.get('provider_inference_call_count'),
                    PROVIDER_INFERENCE_CALL_COUNT_STATUS=economy_result.metrics.get('provider_inference_call_count_status', 'UNKNOWN'),
                )
        except (ContractError, RuntimeError, OSError, ValueError) as exc:
            # Public run output carries only a contract code. Error details may
            # include private host paths or credentials and are not receipts.
            code = str(exc).split(':', 1)[0]
            if (not re.fullmatch(r'[A-Z][A-Z0-9_]{0,127}', code)
                    or not code.startswith(('MISSION_', 'RC72_', 'FIELD_MISSION_', 'BANK_PIP_MIRROR_', 'PIP_MIRROR_'))):
                code = 'MISSION_RUN_CONTRACT_HOLD'
            result = dict(release_batch_id=args.release_batch, release_id=args.release_id,
                source_commit=args.source_commit, status='HOLD', reason=code,
                field_verified=False, bank_final=False)
            if args.command == 'run':
                result.update(MISSION_COMPLETION_STATUS='HOLD',
                    MODEL_ECONOMY_STATUS='HOLD',
                    MODEL_ECONOMY_REASON='MISSION_RUN_NOT_COMPLETED',
                    MODEL_USAGE_TOTAL_STATUS='UNKNOWN', ACTUAL_TOTAL_TOKENS=None,
                    DSH_PROCESS_INVOCATIONS=None, PROVIDER_INFERENCE_CALL_COUNT=None,
                    PROVIDER_INFERENCE_CALL_COUNT_STATUS='UNKNOWN')
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if args.command == 'status':
        return 0
    if (args.command == 'mirror-check' and result.get('status') == 'PASS'
            and result.get('bank_pc_mirror_field_fact') is True
            and result.get('full_package_verified') is True and result.get('mode') == 'BANK_FIELD'):
        return 0
    return 37


if __name__ == '__main__':
    raise SystemExit(main())
