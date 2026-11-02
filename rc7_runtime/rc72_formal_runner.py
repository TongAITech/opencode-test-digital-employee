"""Bind approved N1 reality and N4 Script qualification to the SAME N7 Attempt.

The runtime owns the actual inherited Runner process and signs its receipt.
Worker claims cannot supply a target identity or promote an exit/result flag.
"""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import hmac
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from rc6_runtime import contracts, truth as registry
from rc6_runtime.reality import BankRealityRegistry, _validate_attributes, FORBIDDEN_SECRET_KEYS
from rc6_runtime.target import TargetIdentityBuilder
from rc6_runtime.automation import PytestRunnerAdapter, JUnitRunnerAdapter
from rc6_runtime.executable_spec import ExecutableSpecBuilder, canonical_fingerprint
from .execution_environment import ExecutionEnvironmentAdapter, ExecutionEnvironmentAdmissionService
from .models import ContractError
from .rc72_canonical_design import CanonicalDesignService
from .rc72_n7_execution_admission import _hash
from .runtime_execution import StrictScriptExecutionBundleLoader, _EvidenceBackedProcessHarness
from rc6_runtime.process_environment import scoped_process_environment
from .truth_overlay import install_rc7_truth_overlay

_KIND = 'rc72_n7_formal_runner_receipt'
_EVENT = 'RC72_N7_FORMAL_RUNNER_RECEIPT_UPSERTED'


class FormalRunnerError(ContractError):
    pass


def _utc(value):
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise FormalRunnerError('FORMAL_TARGET_OBSERVATION_TIMEZONE_REQUIRED')
    return parsed.astimezone(timezone.utc)


def _reject_nested_secrets(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in FORBIDDEN_SECRET_KEYS | {'authorization', 'cookie', 'private_key'}:
                raise FormalRunnerError('FORMAL_TARGET_PROFILE_SECRET_VALUE_FORBIDDEN')
            _reject_nested_secrets(child)
    elif isinstance(value, list):
        for child in value:
            _reject_nested_secrets(child)


class _ApprovedReality(BankRealityRegistry):
    def __init__(self, facts, *, sources, at, max_age):
        self._state = {'schema_version': 1, 'facts': {}, 'migrations': {}}
        for row in facts:
            if not isinstance(row, dict):
                raise FormalRunnerError('FORMAL_TARGET_FACT_INVALID')
            key = self._key(row.get('kind'), row.get('id'))
            if key in self._state['facts']:
                raise FormalRunnerError('FORMAL_TARGET_FACT_DUPLICATE')
            _validate_attributes(row.get('attributes'))
            _reject_nested_secrets(row['attributes'])
            if row.get('drift'):
                raise FormalRunnerError('FORMAL_TARGET_FACT_DRIFT_UNRESOLVED')
            if row.get('source_ref') not in sources or not row.get('verified_at'):
                raise FormalRunnerError('FORMAL_TARGET_FACT_SOURCE_UNBOUND')
            age = (at - _utc(row['verified_at'])).total_seconds()
            if age < -30 or age > max_age:
                raise FormalRunnerError('FORMAL_TARGET_FACT_STALE')
            self._state['facts'][key] = deepcopy(row)


def build_approved_target(contract, *, at):
    environment = contract['environment']
    profile = environment.get('target_profile')
    if not isinstance(profile, dict) or not isinstance(profile.get('facts'), list) or not profile['facts']:
        raise FormalRunnerError('FORMAL_FULL_TARGET_PROFILE_REQUIRED:N1')
    age = profile.get('max_age_seconds')
    if isinstance(age, bool) or not isinstance(age, int) or age < 1:
        raise FormalRunnerError('FORMAL_TARGET_FRESHNESS_POLICY_REQUIRED:N1')
    selectors = deepcopy(profile.get('selectors'))
    if not isinstance(selectors, dict) or selectors.get('release_id') != environment.get('deployed_release_id'):
        raise FormalRunnerError('FORMAL_TARGET_DEPLOYED_RELEASE_MISMATCH')
    view = _ApprovedReality(profile['facts'], sources=contract['authoritative_sources'], at=at, max_age=age)
    target = TargetIdentityBuilder(view).build(**selectors)
    env = view.require('environment', selectors['environment_fact_id'])
    if env['source_ref'] != environment['source_ref'] or target.environment_id != environment['name']:
        raise FormalRunnerError('FORMAL_TARGET_ENVIRONMENT_BINDING_MISMATCH')
    route, gateway = urlsplit(contract['endpoint']['url']), urlsplit(target.api_gateway_url)
    if (route.scheme, route.netloc) != (gateway.scheme, gateway.netloc):
        raise FormalRunnerError('FORMAL_TARGET_ENDPOINT_GATEWAY_MISMATCH')
    return target


def _validate(payload):
    out = deepcopy(payload)
    for key in ('runner_receipt_id', 'release_id', 'source_commit', 'preparation_id', 'attempt_id',
                'worker_id', 'contract_id', 'contract_sha256', 'actual_sha256', 'started_at', 'signature'):
        contracts._require_str(out, key)
    if not isinstance(out.get('target_identity'), dict) or not isinstance(out.get('runner_result'), dict):
        raise contracts.DomainValidationError('FORMAL_RUNNER_RECEIPT_OBJECTS_REQUIRED')
    for key in ('field_verified', 'bank_final', 'delivery_authorized'):
        if key in out:
            raise contracts.DomainValidationError('FORMAL_RUNNER_FIELD_CLAIM_FORBIDDEN')
    out.update(artifact_type=_KIND, artifact_version=contracts._artifact_version(out))
    return out


def install_rc72_formal_runner_overlay():
    install_rc7_truth_overlay()
    contracts.VALIDATORS[_KIND] = _validate
    registry.EVENT_TYPES[_EVENT] = (_KIND, 'runner_receipt_id')
    registry.BUCKETS[_KIND] = 'rc72_n7_formal_runner_receipts'
    registry.IDENTITY_FIELDS[_KIND] = 'runner_receipt_id'


def preparation_check_specs(contract):
    checks = [('PRECONDITION', dict(id='N7-PRE-%d' % index, requirement=value))
              for index, value in enumerate(contract['preconditions'])]
    checks += [('DATA_RECHECK', deepcopy(ref)) for ref in sorted(contract['data_refs'], key=lambda value: value['data_ref'])]
    return checks


def verified_formal_receipt(preparation, p, c, raw):
    ref = raw.get('runner_receipt_id')
    if ref is None:
        return None
    row = preparation._one(_KIND, runner_receipt_id=ref)
    signed = {k: v for k, v in row.items() if k not in {'signature', 'artifact_type', 'artifact_version'}}
    if not hmac.compare_digest(row['signature'], preparation.authority._sign(signed)):
        raise FormalRunnerError('FORMAL_RUNNER_RECEIPT_SIGNATURE_INVALID')
    if (any(row.get(k) != p[k] for k in ('release_id', 'source_commit', 'preparation_id', 'attempt_id', 'worker_id', 'contract_id'))
            or row['contract_sha256'] != c['contract_sha256']
            or row['actual_sha256'] != _hash({k: v for k, v in raw.items() if k != 'runner_receipt_id'})):
        raise FormalRunnerError('FORMAL_RUNNER_RECEIPT_BINDING_MISMATCH')
    if row.get('purpose') != 'N7_FORMAL_RUNNER_RECEIPT':
        raise FormalRunnerError('FORMAL_RUNNER_RECEIPT_PURPOSE_INVALID')
    if ref != 'N7RUNNER-' + _hash([p['preparation_id'], c['contract_sha256']])[:24]:
        raise FormalRunnerError('FORMAL_RUNNER_RECEIPT_ID_INVALID')
    expected = build_approved_target(c, at=_utc(row['started_at']))
    if row['target_identity'] != expected.as_dict():
        raise FormalRunnerError('FORMAL_RUNNER_TARGET_IDENTITY_MISMATCH')
    if (canonical_fingerprint(row['frozen_case']) != row['case_fingerprint']
            or canonical_fingerprint(ExecutableSpecBuilder._oracle_source(row['frozen_case'])) != row['oracle_fingerprint']):
        raise FormalRunnerError('FORMAL_RUNNER_FROZEN_CASE_FINGERPRINT_INVALID')
    for key, digest_key in (('script_source_ref', 'script_source_sha256'), ('script_qualification_ref', 'script_qualification_sha256')):
        path = Path(row[key][len('file://'):]) if row[key].startswith('file://') else None
        if path is None or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row[digest_key]:
            raise FormalRunnerError('FORMAL_RUNNER_APPROVED_SOURCE_CHANGED')
    probe_path = Path(row['tool_probe_captured_ref'][len('file://'):])
    if not row['tool_probe_captured_ref'].startswith('file://') or not probe_path.is_file() or hashlib.sha256(probe_path.read_bytes()).hexdigest() != row['tool_probe_sha256']:
        raise FormalRunnerError('FORMAL_RUNNER_PROBE_EVIDENCE_CHANGED')
    expected_checks = preparation_check_specs(c)
    actual_checks = row.get('preparation_checks', [])
    if len(actual_checks) != len(expected_checks):
        raise FormalRunnerError('FORMAL_PREPARATION_CHECK_DENOMINATOR_MISMATCH')
    for check, (kind, spec) in zip(actual_checks, expected_checks):
        if check['kind'] != kind or check['spec'] != spec or check.get('success') is not True:
            raise FormalRunnerError('FORMAL_PREPARATION_CHECK_BINDING_MISMATCH')
        path = Path(check['captured_ref'][len('file://'):])
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != check['sha256']:
            raise FormalRunnerError('FORMAL_PREPARATION_CHECK_EVIDENCE_CHANGED')
        evidence = preparation._one('rc7_evidence', evidence_id=check['evidence_id'])
        if evidence.get('content_hash') != check['sha256'] or p['attempt_id'] not in evidence.get('subject_refs', []):
            raise FormalRunnerError('FORMAL_PREPARATION_CHECK_TRUTH_MISMATCH')
    result = row['runner_result']
    for field in ('stdout_ref', 'stderr_ref'):
        path = Path(result[field][len('file://'):]) if result[field].startswith('file://') else None
        if path is None or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row['process_evidence_sha256'][field]:
            raise FormalRunnerError('FORMAL_RUNNER_PROCESS_EVIDENCE_CHANGED')
    return row


class FormalN7RunnerAdapter:
    def __init__(self, preparation, *, evidence_root, timeout_seconds=300, execution_env=None, environment_adapter=None):
        install_rc72_formal_runner_overlay()
        self.preparation, self.truth = preparation, preparation.truth
        self.root = Path(evidence_root).resolve()
        self.timeout = timeout_seconds
        self.execution_env = scoped_process_environment(execution_env, home=self.root / 'qualification-home')
        self.environment_adapter = environment_adapter
        self.loader = StrictScriptExecutionBundleLoader(evidence_root=str(self.root / 'qualification'),
                                                       validation_timeout_seconds=timeout_seconds)

    def _source(self, contract, context):
        original = self.preparation._one('rc72_n7_execution_preparation', attempt_id=context['attempt_id'])
        p = self.preparation.assert_current(original['preparation_id'])
        if any(context[k] != p[k] for k in ('workitem_id', 'attempt_id', 'worker_id', 'session_id')):
            raise FormalRunnerError('FORMAL_RUNNER_CONTEXT_MISMATCH')
        target = build_approved_target(contract, at=datetime.now(timezone.utc))
        if not isinstance(self.environment_adapter, ExecutionEnvironmentAdapter):
            raise FormalRunnerError('FORMAL_EXECUTABLE_ENVIRONMENT_ADAPTER_REQUIRED')
        design = CanonicalDesignService(self.truth, release_id=p['release_id'],
            source_commit=p['source_commit']).load(release_batch_id=p['release_batch_id'])
        if design.batch.get('version_ids') and target.release_id not in design.batch['version_ids']:
            raise FormalRunnerError('FORMAL_TARGET_OUTSIDE_RELEASE_BATCH')
        source = next(case for case in design.cases if case['tc_id'] == p['case_id'])
        if any(source[key] not in contract['authoritative_sources'] for key in ('source_case_sha256', 'source_artifact_sha256')):
            raise FormalRunnerError('FORMAL_N4_SOURCE_NO_LONGER_MATCHES_N6')
        spec = source['execution'].get('runner')
        if not isinstance(spec, dict) or spec.get('source_ref') not in contract['authoritative_sources']:
            raise FormalRunnerError('FORMAL_APPROVED_RUNNER_BINDING_REQUIRED:N4')
        result_ref = spec.get('script_result_ref')
        cwd = spec.get('cwd')
        if not isinstance(result_ref, str) or not result_ref.startswith('file://') or not isinstance(cwd, str):
            raise FormalRunnerError('FORMAL_SCRIPT_RESULT_AND_CWD_REQUIRED')
        return p, target, source, result_ref, cwd

    def _load(self, contract, context):
        p, target, source, result_ref, cwd = self._source(contract, context)
        bundle = self.loader.load(result_ref[len('file://'):], cwd=cwd, env=self.execution_env)
        if (bundle.spec.tc_id != contract['case_id'] or bundle.spec.release_id != p['release_id']
                or bundle.spec.requirement_id != contract['requirement_id']
                or bundle.spec.layer != self.preparation._one('rc72_etu', etu_id=p['etu_id'])['test_level']
                or set(bundle.spec.test_data_refs) != {ref['data_ref'] for ref in contract['data_refs']}):
            raise FormalRunnerError('FORMAL_RUNNER_SPEC_LINEAGE_MISMATCH')
        admission = self.preparation._one('rc72_n7_execution_admission', admission_id=p['admission_id'])
        n4 = next(row for row in admission['upstream_refs'] if row['node_type'] == 'N4_TEST_DESIGN')
        delivery = self.preparation._one('rc72_node_delivery', delivery_id=n4['delivery_id'])
        version = source.get('case_version', delivery['version'])
        if isinstance(version, bool) or bundle.spec.case_version != version:
            raise FormalRunnerError('FORMAL_FROZEN_CASE_REVISION_MISMATCH')
        # The frozen Case is a mechanical projection of the exact approved N4
        # source. Execution metadata and runtime source hashes are not business fields.
        for key, value in source.items():
            if key not in {'execution', 'status', 'case_version', 'release_id', 'source_artifact_id', 'source_artifact_sha256', 'source_case_sha256'} and bundle.frozen_case.get(key) != value:
                raise FormalRunnerError('FORMAL_FROZEN_CASE_SEMANTICS_CHANGED:' + key)
        if bundle.frozen_case.get('expected') != json.dumps(source['expected_results'], ensure_ascii=False, sort_keys=True):
            raise FormalRunnerError('FORMAL_FROZEN_EXPECTED_RESULTS_CHANGED')
        if bundle.frozen_case.get('status') != 'FROZEN' or bundle.frozen_case.get('oracle', {}).get('checks') != contract['oracles']:
            raise FormalRunnerError('FORMAL_FROZEN_CASE_ORACLE_MISMATCH')
        ExecutableSpecBuilder.verify_case_binding(bundle.spec, bundle.frozen_case)
        source_path = Path(bundle.script.source_ref[len('file://'):])
        if hashlib.sha256(source_path.read_bytes()).hexdigest() != bundle.source_sha256:
            raise FormalRunnerError('FORMAL_APPROVED_SCRIPT_SOURCE_CHANGED')
        if bundle.spec.runner_type == 'PYTEST' and not re.fullmatch(r'(?:[A-Za-z_]\w*::)*[A-Za-z_]\w*(?:\[[^/\\]+\])?', bundle.script.test_symbol):
            raise FormalRunnerError('FORMAL_PYTEST_SYMBOL_MUST_STAY_IN_APPROVED_SOURCE')
        return p, target, bundle, cwd

    def preflight(self, *, contract, context):
        # No subprocess, import, collect or other external tool before durable intent.
        p, target, source, result_ref, cwd = self._source(contract, context)
        if not Path(result_ref[len('file://'):]).is_file() or not Path(cwd).is_dir():
            raise FormalRunnerError('FORMAL_SCRIPT_RESULT_OR_WORKSPACE_MISSING')

    def _check_preparation(self, p, target, contract):
        from .rc72_n7_execution_evidence import ExecutionEvidenceService
        evidence = ExecutionEvidenceService(self.preparation)
        checks = []
        context = dict(target_id=target.target_id, workitem_id=p['workitem_id'], attempt_id=p['attempt_id'],
                       worker_id=p['worker_id'], contract_id=contract['contract_id'])
        for index, (kind, spec) in enumerate(preparation_check_specs(contract)):
            if kind == 'PRECONDITION':
                result = self.environment_adapter.resolve_precondition(deepcopy(spec), deepcopy(context))
            else:
                result = self.environment_adapter.verify_data(deepcopy(spec), {'data_ref': spec['data_ref']}, deepcopy(context))
            if (not isinstance(result, dict) or not isinstance(result.get('success'), bool)
                    or not isinstance(result.get('evidence_ref'), str) or not result['evidence_ref'].startswith('file://')):
                raise FormalRunnerError('FORMAL_PREPARATION_EXECUTABLE_EVIDENCE_REQUIRED')
            if kind == 'DATA_RECHECK' and result.get('data_ref') != spec['data_ref']:
                raise FormalRunnerError('FORMAL_PREPARATION_DATA_SUBSTITUTION_FORBIDDEN')
            source = Path(result['evidence_ref'][len('file://'):])
            if not source.is_file():
                raise FormalRunnerError('FORMAL_PREPARATION_EVIDENCE_FILE_MISSING')
            raw = source.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            captured = self.root / 'preparation-checks' / p['attempt_id'] / ('%d-%s.bin' % (index, digest))
            captured.parent.mkdir(parents=True, exist_ok=True)
            captured.write_bytes(raw)
            evidence_id = 'N7CHECK-' + _hash([p['attempt_id'], kind, spec, digest])[:24]
            check = dict(kind=kind, spec=spec, success=result['success'], evidence_id=evidence_id,
                         captured_ref='file://' + str(captured), sha256=digest)
            check_signature = self.preparation.authority._sign(dict(
                purpose='N7_LIVE_PREPARATION_CHECK', attempt_id=p['attempt_id'], **check))
            evidence._ensure('rc7_evidence', 'RC7_EVIDENCE_UPSERTED', 'evidence_id', dict(
                evidence_id=evidence_id, release_id=p['release_id'], mission_id=p['mission_id'],
                kind='N7_FORMAL_' + kind, source_ref=result['evidence_ref'], content_ref=check['captured_ref'],
                content_hash=digest, subject_refs=[p['attempt_id'], p['case_id']], check_spec=spec,
                check_success=result['success'], check_runtime_signature=check_signature, artifact_version=1))
            evidence._ensure('evidence', 'EVIDENCE_UPSERTED', 'id', dict(id=evidence_id,
                release_id=p['release_id'], kind='N7_FORMAL_' + kind, ref=check['captured_ref'],
                source_artifact_ref=contract['contract_id'], tc_id=p['case_id'], attempt_id=p['attempt_id'], artifact_version=1))
            checks.append(check)
            if not result['success']:
                raise FormalRunnerError('FORMAL_PREPARATION_NOT_SATISFIED:' + kind)
        return checks

    def __call__(self, *, contract, context):
        p, target, bundle, cwd = self._load(contract, context)
        started = datetime.now(timezone.utc).isoformat()
        probe = self.environment_adapter.probe_tool(tool_id=contract['tool_route']['tool'], target_id=target.target_id, layer=bundle.spec.layer)
        ExecutionEnvironmentAdmissionService._validate_probe(probe, tool_id=contract['tool_route']['tool'])
        if not probe.success or not probe.evidence_ref or not probe.evidence_ref.startswith('file://'):
            raise FormalRunnerError('FORMAL_EXECUTION_TOOL_PROBE_FAILED')
        probe_path = Path(probe.evidence_ref[len('file://'):])
        if not probe_path.is_file():
            raise FormalRunnerError('FORMAL_EXECUTION_TOOL_PROBE_EVIDENCE_MISSING')
        probe_bytes = probe_path.read_bytes()
        probe_capture = self.root / 'formal-probes' / (p['attempt_id'] + '.json')
        probe_capture.parent.mkdir(parents=True, exist_ok=True)
        probe_capture.write_bytes(probe_bytes)
        preparation_checks = self._check_preparation(p, target, contract)
        runners = {'PYTEST': PytestRunnerAdapter, 'JUNIT': JUnitRunnerAdapter}
        if bundle.spec.runner_type not in runners:
            raise FormalRunnerError('FORMAL_RUNNER_NOT_IMPLEMENTED')
        runner = runners[bundle.spec.runner_type](timeout_seconds=self.timeout)
        runner.harness = _EvidenceBackedProcessHarness(evidence_root=str(self.root), timeout_seconds=self.timeout)
        env = dict(self.environment_adapter.execution_env(target_id=target.target_id, layer=bundle.spec.layer))
        env.update(self.execution_env)
        # The inherited runner supports explicit legacy module paths; N7 denies them.
        env = scoped_process_environment(env, home=self.root / 'process-home')
        env.update(RC72_EXECUTABLE_CONTRACT=json.dumps(contract, sort_keys=True),
                   RC72_ATTEMPT_CONTEXT=json.dumps(context, sort_keys=True),
                   RC72_TARGET_IDENTITY=json.dumps(target.as_dict(), sort_keys=True))
        result = runner.execute(spec=bundle.spec, script=bundle.script, validation=bundle.validation, cwd=cwd, env=env)
        raw = deepcopy(result.actual_result)
        if 'runner_receipt_id' in raw:
            raise FormalRunnerError('FORMAL_RUNNER_RESERVED_RESULT_FIELD_FORBIDDEN')
        receipt_id = 'N7RUNNER-' + _hash([p['preparation_id'], contract['contract_sha256']])[:24]
        receipt = dict(runner_receipt_id=receipt_id, purpose='N7_FORMAL_RUNNER_RECEIPT', release_id=p['release_id'], source_commit=p['source_commit'],
            preparation_id=p['preparation_id'], attempt_id=p['attempt_id'], worker_id=p['worker_id'],
            contract_id=contract['contract_id'], contract_sha256=contract['contract_sha256'],
            target_identity=target.as_dict(), frozen_case=deepcopy(bundle.frozen_case),
            case_fingerprint=bundle.spec.case_fingerprint, oracle_fingerprint=bundle.spec.oracle_fingerprint,
            preparation_checks=preparation_checks, tool_probe=asdict(probe), tool_probe_captured_ref='file://' + str(probe_capture),
            tool_probe_sha256=hashlib.sha256(probe_bytes).hexdigest(),
            required_tool_observed=any(call['tool_id'] == contract['tool_route']['tool'] for call in result.tool_calls),
            spec_id=bundle.spec.spec_id, script_id=bundle.script.script_id, script_source_sha256=bundle.source_sha256, script_source_ref=bundle.script.source_ref,
            script_qualification_ref=bundle.upstream_result_ref,
            script_qualification_sha256=hashlib.sha256(Path(bundle.upstream_result_ref[len('file://'):]).read_bytes()).hexdigest(), runner_result=asdict(result),
            actual_sha256=_hash(raw), started_at=started,
            process_evidence_sha256={key: hashlib.sha256(Path(getattr(result, key)[len('file://'):]).read_bytes()).hexdigest()
                for key in ('stdout_ref', 'stderr_ref')})
        receipt['signature'] = self.preparation.authority._sign(receipt)
        receipt['artifact_version'] = 1
        self.truth.append_atomic(_EVENT, receipt)
        raw['runner_receipt_id'] = receipt_id
        return raw


install_rc72_formal_runner_overlay()
