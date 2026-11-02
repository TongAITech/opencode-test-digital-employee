"""Compile approved N4 Case materialization + canonical N1/N5 into N6.

Older N4 candidates remain replayable but cannot execute without explicit,
reviewed request/input/cleanup materialization. Missing facts produce a gap;
this adapter never guesses inputs or substitutes another Case-shaped payload.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, Mapping, Optional, Sequence

from rc6_runtime.truth import TruthRuntime
from .models import ContractError
from .oracle_runtime import DeterministicOracleRuntime, DeterministicOracleError
from .rc72_canonical_design import CanonicalDesignService
from .rc72_n1_executable_binding import N1ExecutableBindingService
from .rc72_n5_data_inventory import N5DataRequirementInventoryService
from .rc72_n5_data_resolution import N5DataResolutionService
from .rc72_n6_completion import N6DeliveryGateService
from .rc72_n6_executable_readiness import (
    ExecutableContract, N6ExecutableReadinessCompiler, canonical_n5_data_ref,
)


class CanonicalExecutableError(ContractError):
    pass


def approved_case_payload(case: Mapping[str, Any], *, mission_id: str) -> Dict[str, Any]:
    """Mechanical schema adaptation only; preserve the approved business fields."""
    execution = case.get('execution')
    if not isinstance(execution, Mapping) or not execution:
        raise CanonicalExecutableError('N6_APPROVED_CASE_EXECUTION_SPEC_MISSING:N4')
    for name in ('inputs', 'request', 'cleanup'):
        if not isinstance(execution.get(name), Mapping) or not execution[name]:
            raise CanonicalExecutableError('N6_APPROVED_CASE_%s_MISSING:N4' % name.upper())
    if not execution.get('binding_key') or not execution.get('authoritative_sources'):
        raise CanonicalExecutableError('N6_APPROVED_CASE_EXECUTION_SOURCES_MISSING')
    for name in ('request', 'cleanup'):
        if execution[name].get('source_ref') not in execution['authoritative_sources']:
            raise CanonicalExecutableError('N6_APPROVED_CASE_%s_SOURCE_UNBOUND' % name.upper())
    oracle = case.get('oracle')
    if not isinstance(oracle, Mapping) or not oracle.get('checks'):
        raise CanonicalExecutableError('N6_APPROVED_CASE_ORACLE_MISSING')
    try:
        DeterministicOracleRuntime.validate_contract(dict(oracle))
    except DeterministicOracleError as exc:
        raise CanonicalExecutableError('N6_APPROVED_CASE_ORACLE_UNRESOLVED:N4') from exc
    return dict(
        release_batch_id=case['release_batch_id'], mission_id=mission_id,
        requirement_id=case['requirement_id'], sst_id=case['sst_id'],
        obligation_id=case['obligation_id'], case_id=case['tc_id'],
        case_ref='r1://artifact/' + case['source_artifact_id'] + '#case/' + case['tc_id'],
        status='PASS', preconditions=deepcopy(case['preconditions']), steps=deepcopy(case['steps']),
        inputs=deepcopy(execution['inputs']), expected=deepcopy(case['expected_results']),
        oracles=deepcopy(oracle['checks']), assertions=deepcopy(oracle['checks']),
        evidence_requirements=deepcopy(case['evidence_requirements']),
        authoritative_sources=list(execution['authoritative_sources']) + [
            case['source_artifact_id'], case['source_artifact_sha256'], case['source_case_sha256']],
    )


def compile_approved_case(case: Mapping[str, Any], *, mission_id: str,
                          runtime_binding: Mapping[str, Any], data_refs: Sequence[Mapping[str, Any]],
                          now: Optional[datetime] = None) -> ExecutableContract:
    payload = approved_case_payload(case, mission_id=mission_id)
    execution = case['execution']
    binding = deepcopy(dict(runtime_binding))
    if binding.get('binding_key') != execution['binding_key']:
        raise CanonicalExecutableError('N6_N1_BINDING_KEY_MISMATCH')
    binding.update(request=deepcopy(execution['request']), cleanup=deepcopy(execution['cleanup']))
    binding['authoritative_sources'] = list(binding.get('authoritative_sources', [])) + payload['authoritative_sources']
    return N6ExecutableReadinessCompiler().compile(payload, data_refs, binding, now=now)


class CanonicalExecutableService:
    def __init__(self, truth: TruthRuntime, *, release_id: str, source_commit: str,
                 now: Optional[datetime] = None):
        self.truth = truth
        self.release_id, self.source_commit, self.now = release_id, source_commit, now

    def compile_batch(self, *, release_batch_id: str) -> Dict[str, Any]:
        design = CanonicalDesignService(self.truth, release_id=self.release_id,
                                        source_commit=self.source_commit).load(release_batch_id=release_batch_id)
        requirements = N5DataRequirementInventoryService(
            self.truth, source_commit=self.source_commit,
        ).current_requirements(release_batch_id=release_batch_id)
        if {row['case_id'] for row in requirements} != {case['tc_id'] for case in design.cases}:
            raise CanonicalExecutableError('N6_CANONICAL_CASE_DENOMINATOR_MISMATCH')
        # Check every source Case before any binding/contract is persisted.
        for case in design.cases:
            approved_case_payload(case, mission_id=design.batch['mission_id'])
        CanonicalDesignService(self.truth, release_id=self.release_id,
                               source_commit=self.source_commit).promote_obligations(release_batch_id=release_batch_id)
        n1 = N1ExecutableBindingService(self.truth, source_commit=self.source_commit)
        n5 = N5DataResolutionService(self.truth, release_id=self.release_id, source_commit=self.source_commit)
        compiled = []
        for case in design.cases:
            refs = []
            for row in requirements:
                if row['case_id'] == case['tc_id']:
                    refs.append(canonical_n5_data_ref(n5.verified_binding(data_requirement_id=row['data_requirement_id']), row))
            runtime = n1.canonicalize(release_batch_id=release_batch_id, binding_key=case['execution']['binding_key'])
            compiled.append(compile_approved_case(case, mission_id=design.batch['mission_id'],
                                                  runtime_binding=runtime, data_refs=refs, now=self.now))
        return N6DeliveryGateService(self.truth, release_id=self.release_id,
                                     source_commit=self.source_commit, now=self.now).complete(
            release_batch_id=release_batch_id, contracts=compiled,
        )
