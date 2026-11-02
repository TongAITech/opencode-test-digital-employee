"""Native whole-Case N6 product route, never caller-supplied contracts."""
from .models import ContractError
from .rc72_canonical_design import CanonicalDesignService
from .rc72_canonical_executable import CanonicalExecutableService, CanonicalExecutableError, approved_case_payload
from .rc72_n6_executable_readiness import ExecutableReadinessError

_CASE_GAPS = {
    'N6_APPROVED_CASE_EXECUTION_SPEC_MISSING:N4', 'N6_APPROVED_CASE_INPUTS_MISSING:N4',
    'N6_APPROVED_CASE_REQUEST_MISSING:N4', 'N6_APPROVED_CASE_CLEANUP_MISSING:N4',
    'N6_APPROVED_CASE_EXECUTION_SOURCES_MISSING', 'N6_APPROVED_CASE_REQUEST_SOURCE_UNBOUND',
    'N6_APPROVED_CASE_CLEANUP_SOURCE_UNBOUND', 'N6_APPROVED_CASE_ORACLE_MISSING',
    'N6_APPROVED_CASE_ORACLE_UNRESOLVED:N4',
}


class N6PipelineService:
    def __init__(self, truth, *, release_id, source_commit):
        self.truth, self.release_id, self.source_commit = truth, release_id, source_commit

    def complete(self, *, release_batch_id):
        design = CanonicalDesignService(self.truth, release_id=self.release_id,
            source_commit=self.source_commit).load(release_batch_id=release_batch_id)
        if design.batch['release_id'] != self.release_id:
            raise ContractError('RC72_N6_PIPELINE_RELEASE_MISMATCH')
        violations = []
        # Report the full missing-materialization denominator before any compile
        # writes. Missing facts remain the original owning node's work.
        for case in design.cases:
            try:
                approved_case_payload(case, mission_id=design.batch['mission_id'])
            except CanonicalExecutableError as exc:
                if str(exc) not in _CASE_GAPS:
                    raise
                violations.append(dict(case_id=case['tc_id'], code=str(exc), target_node='N4'))
        if violations:
            return dict(status='HOLD', reason='N6_APPROVED_INPUTS_INCOMPLETE', violations=violations)
        try:
            return CanonicalExecutableService(self.truth, release_id=self.release_id,
                source_commit=self.source_commit).compile_batch(release_batch_id=release_batch_id)
        except ExecutableReadinessError as exc:
            return dict(status='HOLD', reason='N6_EXECUTABLE_READINESS_NOT_ACCEPTED',
                violations=[dict(v.to_payload(), case_id=getattr(exc,'case_id',None)) for v in exc.violations])
