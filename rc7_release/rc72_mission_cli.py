"""Canonical RC7.2 status and native run/continuation entry."""
import argparse
import json
import re
from pathlib import Path

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_release_driver import release_batch_status
from rc7_runtime.rc72_domain import AutonomousMissionNode
from rc7_runtime.models import ContractError


def _accepted_ten_node_completion(node_rows, transitions=None, n7_gates=None, n7_deliveries=None):
    """Admit the exact N1-N10 denominator, including the real N7->N9 route.

    Normal successful N7 execution forwards directly to N9: N8 MUST stay
    NOT_STARTED.  Never invent an N8 PASS merely to satisfy a CLI status
    guard, and never bypass it without the exact accepted R1 FORWARD edge.
    """
    required = {node.value for node in AutonomousMissionNode.ordered()}
    if (not isinstance(node_rows, list) or len(node_rows) != len(required)
            or any(not isinstance(row, dict) for row in node_rows)):
        return False
    types = [row.get('node_type') for row in node_rows]
    if set(types) != required or len(set(types)) != len(types):
        return False
    by_type = {row['node_type']: row for row in node_rows}
    if all(row.get('state') == 'PASS' for row in node_rows):
        return True
    n8 = by_type['N8_DIAGNOSIS_RECOVERY']
    if (n8.get('state') != 'NOT_STARTED'
            or any(row.get('state') != 'PASS' for row in node_rows if row is not n8)
            or n8.get('gate_refs') or n8.get('delivery_refs')
            or n8.get('active_delivery_version') is not None
            or not isinstance(transitions, list)
            or not isinstance(n7_gates, list)
            or not isinstance(n7_deliveries, list)):
        return False
    n7, n9 = by_type['N7_EXECUTION'], by_type['N9_DEFECT']
    mission = n7.get('mission_id')
    n7_id, n9_id = n7.get('mission_node_id'), n9.get('mission_node_id')
    gate_refs = n7.get('gate_refs')
    if (not isinstance(mission, str) or not mission
            or n8.get('mission_id') != mission or n9.get('mission_id') != mission
            or not isinstance(n7_id, str) or not n7_id
            or not isinstance(n9_id, str) or not n9_id
            or not isinstance(gate_refs, list) or not gate_refs):
        return False
    # Historical gate_refs persist after a new N7 execution generation.
    # Only the Gate of the currently active signed N7 Delivery can authorize
    # bypass. A stale older PASS Gate is never sufficient.
    if not isinstance(n7.get('active_delivery_version'), int):
        return False
    deliveries = [d for d in n7_deliveries if isinstance(d, dict)
        and d.get('mission_id') == mission
        and d.get('mission_node_id') == n7_id
        and d.get('node_type') == 'N7_EXECUTION'
        and d.get('version') == n7['active_delivery_version']
        and d.get('delivery_id') in n7.get('delivery_refs', [])]
    if len(deliveries) != 1:
        return False
    gates = [g for g in n7_gates if isinstance(g, dict)
        and g.get('mission_id') == mission
        and g.get('mission_node_id') == n7_id
        and g.get('node_type') == 'N7_EXECUTION'
        and g.get('decision') == 'PASS'
        and g.get('delivery_id') == deliveries[0]['delivery_id']
        and g.get('gate_id') in gate_refs]
    if len(gates) != 1:
        return False
    return any(
        isinstance(edge, dict)
        and edge.get('mission_id') == mission
        and edge.get('kind') == 'FORWARD'
        and edge.get('from_node_type') == 'N7_EXECUTION'
        and edge.get('to_node_type') == 'N9_DEFECT'
        and edge.get('from_mission_node_id') == n7_id
        and edge.get('to_mission_node_id') == n9_id
        and edge.get('source_gate_id') == gates[0]['gate_id']
        for edge in transitions
    )


def _require_field_captain(command, package_root, bindings):
    """GAP-02: a transported bank Mission must run under real DSH custody.

    A DSH chat team or empty configuration is not a Captain observation.
    Configured hosts can bootstrap/reenter an observed, signed R1 Captain;
    engineering component fixtures without a full package retain their
    explicitly non-Field legacy evaluation path.
    """
    if (command in {'run', 'admit-script-ready'}
            and (command == 'admit-script-ready'
                 or (Path(package_root) / 'PACKAGE_MANIFEST.json').is_file())
            and getattr(bindings, 'captain_binding', None) is None):
        raise ContractError('C07_REAL_DSH_CAPTAIN_HOST_REQUIRED_FOR_FIELD_RUN')


def main(argv=None, *, bank_trust_roots=None):
    """CLI entry or explicitly bank-embedded Host invocation.

    No command-line flag or JSON file may invent bank Host signing roots.
    A trusted in-process bank controller may inject the roots; ordinary CLI
    invocation lacks them and fails closed before any Captain bootstrap.
    """
    parser = argparse.ArgumentParser(description='RC7.2 ReleaseBatch mission')
    parser.add_argument('command', choices=['status', 'run', 'script-ready-status',
        'admit-script-ready', 'mirror-check', 'review-reproduction',
        'review-professional', 'accept-professional-resolution', 'complete-professional-n9'])
    parser.add_argument('--ledger', required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--release-batch', required=True)
    parser.add_argument('--release-id')
    parser.add_argument('--bindings-module')
    parser.add_argument('--mission-config')
    parser.add_argument('--captain-observer-module',
        help='approved bank-local AgentTeams membership provider Python module')
    parser.add_argument('--dsh-host-url', default='http://127.0.0.1:4096',
        help='local DSH/OpenCode REST address; loopback only')
    parser.add_argument('--package-root')
    parser.add_argument('--evidence-root')
    parser.add_argument('--economy-config', help='trusted JSON for bank cost windows and soft mission economy targets')
    parser.add_argument('--bridge-user-config', action='store_true')
    parser.add_argument('--retry-returned-failure', action='store_true')
    parser.add_argument('--reproduction-request')
    parser.add_argument('--defect-id')
    parser.add_argument('--attestation-ref')
    args = parser.parse_args(argv)
    if args.command != 'run' and args.economy_config:
        parser.error('economy-config is only valid for run')
    if (args.captain_observer_module and
            (not args.mission_config or args.bindings_module
             or args.command not in {'run', 'admit-script-ready'})):
        parser.error('captain-observer-module requires a configured formal run')
    # A real bank professional decision is never sourced from the ordinary
    # JSON capability manifest. The trusted Host module must supply a typed
    # MissionProfessionalReviewBinding and its independent verifier. The N9
    # review, source-Gap adjudication and NodeGate are three separate steps;
    # none is an implicit approval to replay a bank operation or pass N10.
    if args.command == 'review-reproduction':
        if (not args.bindings_module or args.mission_config
                or not args.reproduction_request or not args.attestation_ref
                or args.defect_id):
            parser.error('review-reproduction requires trusted Host binding, request and attestation (no defect)')
    elif args.command == 'review-professional':
        if (not args.bindings_module or args.mission_config
                or not args.reproduction_request or not args.defect_id
                or not args.attestation_ref):
            parser.error('review-professional requires trusted Host binding, reproduction request, defect and attestation')
    elif args.command == 'accept-professional-resolution':
        if (not args.bindings_module or args.mission_config
                or not args.reproduction_request or not args.defect_id
                or args.attestation_ref):
            parser.error('accept-professional-resolution requires an existing reviewed request and defect, not a new attestation')
    elif args.command == 'complete-professional-n9':
        if (not args.bindings_module or args.mission_config
                or args.reproduction_request or args.defect_id or args.attestation_ref):
            parser.error('complete-professional-n9 requires trusted Host binding and no caller-selected evidence')
    elif args.reproduction_request or args.defect_id or args.attestation_ref:
        parser.error('N9 approval references require the exact trusted Host professional command')
    if args.command != 'mirror-check' and (args.bridge_user_config or args.retry_returned_failure):
        parser.error('mirror options require mirror-check')
    path = Path(args.ledger).expanduser().resolve()
    if not path.is_file():
        parser.error('existing canonical ledger required')
    # Register all C10-owned events BEFORE TruthRuntime replays a historical
    # R1 ledger, including UNKNOWN provider usage and shared batch evidence.
    from rc7_runtime.rc72_economy_replay_bootstrap import install_rc72_economy_replay_bindings
    from rc7_runtime.rc72_captain_dispatch_fencing import install_captain_dispatch_overlay
    install_rc72_economy_replay_bindings()
    # Register real Captain lease events before a cold R1 projection. A
    # configured JSON without a DSH Host binding must not hide old leases.
    install_captain_dispatch_overlay()
    from rc7_runtime.rc72_script_ready_gate import install_script_ready_admission_overlay
    install_script_ready_admission_overlay()
    truth = TruthRuntime(path)
    if args.command == 'status':
        result = release_batch_status(truth, source_commit=args.source_commit, release_batch_id=args.release_batch)
    elif args.command == 'script-ready-status':
        from rc7_runtime.rc72_script_ready_gate import NativeScriptReadyGateProducer
        result = NativeScriptReadyGateProducer(truth, release_id=args.release_id,
            source_commit=args.source_commit).inspect(release_batch_id=args.release_batch)
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
            if args.command in {'run', 'admit-script-ready'}:
                # GAP-02: before calling any Host factory (which may create a
                # first R1 Captain), prove canonical Q7 is currently ADMITTED.
                # Full mirror byte verification still occurs after composition.
                admissible = truth.query('rc72_q7_admission',
                    release_batch_id=args.release_batch)
                matching = [row for row in admissible
                    if row.get('source_commit') == args.source_commit
                    and row.get('mission_id') == snapshot['mission_id']]
                if len(matching) != 1:
                    raise ContractError('FIELD_MISSION_EXACT_SOURCE_COMMIT_ADMISSION_REQUIRED')
                if matching[0].get('status') != 'ADMITTED':
                    raise ContractError('FIELD_MISSION_Q7_ADMISSION_HOLD')
            if args.mission_config:
                if args.captain_observer_module:
                    from rc7_release.rc72_dsh_agentteams_factory import configured_agentteams_host_bindings
                    bindings = configured_agentteams_host_bindings(
                        truth, release_id=args.release_id,
                        source_commit=args.source_commit,
                        release_batch_id=args.release_batch,
                        config_path=args.mission_config,
                        provider_module=args.captain_observer_module,
                        dsh_base_url=args.dsh_host_url,
                        bank_trust_roots=bank_trust_roots)
                else:
                    from rc7_release.rc72_configured_mission import configured_mission_bindings
                    bindings = configured_mission_bindings(
                        truth, release_id=args.release_id,
                        source_commit=args.source_commit, config_path=args.mission_config,
                        release_batch_id=args.release_batch)
            else:
                bindings = load_mission_bindings(args.bindings_module, truth=truth,
                    release_id=args.release_id, source_commit=args.source_commit,
                    release_batch_id=args.release_batch)
            # A full offline bank Mission may never silently choose the
            # ungoverned legacy path simply because Captain startup was not
            # observed. Reject before factory, worker, budget or business I/O.
            _require_field_captain(args.command, root, bindings)
            # Factory composition has no R1 effects.  In particular, do not
            # allocate the first soft token budget while Q7 Field admission is
            # HOLD: a refused Mission must leave the canonical ledger intact.
            driver = create_mission_driver(truth, release_id=args.release_id, source_commit=args.source_commit,
                evidence_root=Path(args.evidence_root).expanduser().resolve(),
                **{f.name: getattr(bindings, f.name) for f in fields(bindings)})
            if driver.bank_pip_mirror.root != root:
                raise ContractError('MISSION_RUNNING_PACKAGE_MIRROR_SCOPE_MISMATCH')
            if args.command == 'run':
                from rc7_runtime.rc72_field_mission_start import ReleaseBatchFieldMissionLauncher
                admission = ReleaseBatchFieldMissionLauncher(
                    truth, source_commit=args.source_commit,
                    bank_pip_mirror=driver.bank_pip_mirror)
                # This is the same exact batch + signed mirror admission as
                # driver.start(), but READ-ONLY. It happens before C10 creates
                # any budget, wraps any DSH launcher, or performs business I/O.
                admission._admission(admission._batch(args.release_batch))
                from rc7_runtime.rc72_production_economy_ingress import (
                    bind_release_batch_model_economy, read_mission_economy_config,
                )
                economy = bind_release_batch_model_economy(
                    truth, workers=bindings.workers, release_id=args.release_id,
                    mission_id=snapshot['mission_id'],
                    policy=read_mission_economy_config(args.economy_config),
                )
            if args.command == 'admit-script-ready':
                # Uses canonical N6 NodeGate + signed Host admission. No RC6
                # gate string, no model budget, no SUT effect or fabricated PASS.
                from rc7_runtime.rc72_script_ready_gate import NativeScriptReadyGateProducer
                from rc7_runtime.rc72_field_mission_start import ReleaseBatchFieldMissionLauncher
                launcher = ReleaseBatchFieldMissionLauncher(
                    truth, source_commit=args.source_commit,
                    bank_pip_mirror=driver.bank_pip_mirror)
                launcher._admission(launcher._batch(args.release_batch))
                result = NativeScriptReadyGateProducer(
                    truth, release_id=args.release_id, source_commit=args.source_commit,
                    authority=bindings.execution_authority).issue(
                        release_batch_id=args.release_batch,
                        captain_binding=bindings.captain_binding)
            elif args.command == 'review-reproduction':
                # This is a trusted Host-controlled HumanGate R1 write; it
                # never spends mission tokens, invokes DSH, or executes N7.
                result = driver.review_reproduction(
                    release_batch_id=args.release_batch,
                    request_id=args.reproduction_request,
                    attestation_ref=args.attestation_ref)
            elif args.command == 'review-professional':
                # External trusted Human reviewer approves *existing* R1
                # evidence; never builds a Defect, edits the failed N7 or
                # makes another DSH/HTTP call.
                result = driver.review_professional_resolution(
                    release_batch_id=args.release_batch,
                    request_id=args.reproduction_request,
                    defect_id=args.defect_id,
                    attestation_ref=args.attestation_ref)
            elif args.command == 'accept-professional-resolution':
                # This is a distinct explicit post-review R1 adjudication.
                # The prior signed independent review is mandatory, and
                # original N8 failed Attempts remain immutable.
                result = driver.accept_professional_resolution(
                    release_batch_id=args.release_batch,
                    request_id=args.reproduction_request,
                    defect_id=args.defect_id)
            elif args.command == 'complete-professional-n9':
                # Never treats a professional N9 Gate as a release N10 PASS.
                # The service will re-audit actual RCA, fix, regression,
                # original source Gap and every professional WorkItem.
                result = driver.complete_professional_n9(
                    release_batch_id=args.release_batch)
            elif args.command == 'mirror-check':
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
                all_nodes_pass = _accepted_ten_node_completion(
                    node_rows,
                    transitions=truth.query('rc72_node_transition',
                        mission_id=snapshot['mission_id']),
                    n7_gates=truth.query('rc72_node_gate',
                        mission_id=snapshot['mission_id']),
                    n7_deliveries=truth.query('rc72_node_delivery',
                        mission_id=snapshot['mission_id']))
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
                    DSH_PROCESS_INVOCATION_COUNT_STATUS=economy_result.metrics.get('dsh_process_invocation_count_status', 'UNKNOWN'),
                    DSH_PROCESS_LAUNCH_ERROR_COUNT=economy_result.metrics.get('dsh_process_launch_error_count'),
                    PROVIDER_INFERENCE_CALL_COUNT=economy_result.metrics.get('provider_inference_call_count'),
                    PROVIDER_INFERENCE_CALL_COUNT_STATUS=economy_result.metrics.get('provider_inference_call_count_status', 'UNKNOWN'),
                    LOSSLESS_JSON_COMPACTED_CALLS=economy_result.metrics.get('lossless_json_compacted_calls', 0),
                    VERIFIED_PROMPT_SERIALIZATION_SAVED_BYTES=economy_result.metrics.get('verified_prompt_serialization_saved_bytes', 0),
                    VERIFIED_PROMPT_TOKEN_SAVINGS=economy_result.metrics.get('verified_prompt_token_savings'),
                )
        except (ContractError, RuntimeError, OSError, ValueError) as exc:
            # Public run output carries only a contract code. Error details may
            # include private host paths or credentials and are not receipts.
            code = str(exc).split(':', 1)[0]
            if (not re.fullmatch(r'[A-Z][A-Z0-9_]{0,127}', code)
                    or not code.startswith(('MISSION_', 'RC72_', 'FIELD_MISSION_', 'BANK_PIP_MIRROR_', 'PIP_MIRROR_', 'SCRIPT_READY_', 'C07_'))):
                code = 'MISSION_RUN_CONTRACT_HOLD'
            result = dict(release_batch_id=args.release_batch, release_id=args.release_id,
                source_commit=args.source_commit, status='HOLD', reason=code,
                field_verified=False, bank_final=False)
            if args.command == 'run':
                result.update(MISSION_COMPLETION_STATUS='HOLD',
                    MODEL_ECONOMY_STATUS='HOLD',
                    MODEL_ECONOMY_REASON='MISSION_RUN_NOT_COMPLETED',
                    MODEL_USAGE_TOTAL_STATUS='UNKNOWN', ACTUAL_TOTAL_TOKENS=None,
                    DSH_PROCESS_INVOCATIONS=None,
                    DSH_PROCESS_INVOCATION_COUNT_STATUS='UNKNOWN',
                    DSH_PROCESS_LAUNCH_ERROR_COUNT=None,
                    PROVIDER_INFERENCE_CALL_COUNT=None,
                    PROVIDER_INFERENCE_CALL_COUNT_STATUS='UNKNOWN',
                    LOSSLESS_JSON_COMPACTED_CALLS=None,
                    VERIFIED_PROMPT_SERIALIZATION_SAVED_BYTES=None,
                    VERIFIED_PROMPT_TOKEN_SAVINGS=None)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if args.command == 'status':
        return 0
    if (args.command == 'admit-script-ready' and result.get('status') == 'ADMITTED'
            and result.get('n6_gate_id') and result.get('admission_id')
            and result.get('bank_final') is False and result.get('field_verified') is False):
        return 0
    if (args.command == 'review-reproduction'
            and result.get('human_decision') in {'APPROVED','REJECTED'}
            and result.get('status') == 'HOLD'):
        # Command succeeded at recording human disposition. Mission remains
        # HOLD until independent new execution, RCA and N9 Gate pass.
        return 0
    if (args.command == 'review-professional'
            and result.get('status') == 'HOLD'
            and result.get('review_id')
            and result.get('n9_gate_pass') is False
            and result.get('bank_final') is False):
        # Successful durable human signoff is still an N9 HOLD.
        return 0
    if (args.command == 'accept-professional-resolution'
            and result.get('status') == 'ADJUDICATED'
            and result.get('original_gap_evaluation_id')
            and result.get('n9_gate_pass') is False
            and result.get('bank_final') is False):
        return 0
    if (args.command == 'complete-professional-n9'
            and result.get('status') == 'PASS'
            and result.get('state') == 'N9_PASS'
            and result.get('n9_gate_pass') is True
            and result.get('field_verified') is False
            and result.get('bank_final') is False):
        # N9 success is not N10 convergence or FIELD_VERIFIED.
        return 0
    if (args.command == 'mirror-check' and result.get('status') == 'PASS'
            and result.get('bank_pc_mirror_field_fact') is True
            and result.get('full_package_verified') is True and result.get('mode') == 'BANK_FIELD'):
        return 0
    return 37


if __name__ == '__main__':
    raise SystemExit(main())
