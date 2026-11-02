"""Request/schema ownership at the actual native Case materialization boundary."""
from copy import deepcopy
import pytest
from rc7_runtime.rc72_canonical_executable import compile_approved_case
from rc7_runtime.rc72_n6_executable_readiness import ExecutableReadinessError
from test_rc72_n6_executable_readiness import _case, _binding, _data_ref, NOW


def test_native_case_request_schema_gap_goes_to_n3_and_never_to_n1():
    old = _case()
    binding = _binding()
    binding['binding_key']='approved-route-key'
    request = dict(binding['request'])
    request.pop('schema_ref')
    cleanup = deepcopy(binding['cleanup'])
    case = dict(tc_id=old['case_id'],release_batch_id=old['release_batch_id'],requirement_id=old['requirement_id'],
        sst_id=old['sst_id'],obligation_id=old['obligation_id'],preconditions=old['preconditions'],steps=old['steps'],
        expected_results=[old['expected']],evidence_requirements=old['evidence_requirements'],
        source_artifact_id='approved-artifact',source_artifact_sha256='sha256:'+'a'*64,source_case_sha256='sha256:'+'b'*64,
        oracle=dict(checks=[dict(type='API_RESPONSE',actual_path='response.status_code',operator='EQ',expected=200)]),
        execution=dict(binding_key='approved-route-key',inputs=old['inputs'],request=request,cleanup=cleanup,
            authoritative_sources=[request['source_ref'],cleanup['source_ref']]))
    with pytest.raises(ExecutableReadinessError) as error:
        compile_approved_case(case,mission_id=old['mission_id'],runtime_binding=binding,data_refs=[_data_ref()],now=NOW)
    request_gaps = [v for v in error.value.violations if v.code.startswith('N6_REQUEST')]
    assert request_gaps and all(v.target_node=='N3' for v in request_gaps)
