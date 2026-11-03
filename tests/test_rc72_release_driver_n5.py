"""Native whole N1-N5 route; protocol children are engineering adapters."""
import json
import subprocess
import sys
from pathlib import Path
import pytest
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_canonical_design import CanonicalDesignService

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_n5_pipeline import N5PipelineService
from test_rc72_release_driver_n4 import _n4_driver
from test_rc72_n5_data_discovery_handoff import _candidate
from test_rc72_n5_data_verification_handoff import _v2_candidate
from rc72_n2_test_support import BATCH, COMMIT, RELEASE


def _n5_driver(tmp_path, *, negative=False, materialized=False, runner_root=None):
    truth, driver, calls = _n4_driver(tmp_path, compact=True, materialized=materialized, runner_root=runner_root)
    script = tmp_path / 'n5-protocol-worker.py'
    script.write_text('import sys,json,uuid\n'
        'print(json.dumps(dict(type="session",session_id="session-n5-product-"+uuid.uuid4().hex)))\n'
        'print(json.dumps(dict(type="tool_call",tool_name=sys.argv[2])))\n'
        'print(json.dumps(dict(type="final",text=sys.argv[1])))\n')
    patch = tmp_path / 'n5-patch.json'
    patch.write_text('{}')
    def launcher(role):
        def run(command, **kwargs):
            truth.rebuild_projection()
            rows = truth.query('rc72_n5_data_discovery_dispatch')
            row = next(r for r in rows if '"data_requirement_id": "%s"' % r['data_requirement_id'] in command[-1])
            if role == 'data-discover':
                candidate = _candidate(row)
                tool = 'data-query'
            else:
                candidate = _v2_candidate(truth, row, repair=negative)
                if not negative:
                    candidate.update(candidate_ref='candidate://bank-data/'+row['data_requirement_id'],
                        source_or_constructor='query-scoped-data:'+row['data_requirement_id'])
                tool = 'data-verify-query'
            calls.append((role,row['data_requirement_id']))
            return subprocess.run([sys.executable,str(script),json.dumps(candidate),tool], **kwargs)
        return DshHeadlessWorkerLauncher(dsh_bin=sys.executable,patch_path=str(patch),cwd=str(tmp_path),
            truth=truth,authority=RC72AuthorityRuntime(('engineering-n5-key-'+role).encode()),
            coordinator_instance_id='n5-product-controller',release_id=RELEASE,
            state_root=str(tmp_path/('runtime-'+role)),command_runner=run)
    discovery, verifier = launcher('data-discover'),launcher('data-verify')
    driver.n5_pipeline = N5PipelineService(truth,source_commit=COMMIT,launcher=discovery,
        allowed_tools=['data-query'],verifier=verifier,verification_tools=['data-verify-query'])
    return truth,driver,calls


def test_all_canonical_case_data_requirements_are_independently_verified_before_n6(tmp_path):
    truth,driver,calls = _n5_driver(tmp_path)
    result = driver.run(release_batch_id=BATCH)
    assert result['status']=='HOLD' and result['reason']=='N6_APPROVED_INPUTS_INCOMPLETE'
    states = {n['node_type']:n['state'] for n in result['nodes']}
    assert states['N5_TEST_DATA']=='PASS' and states['N6_EXECUTABLE_READINESS']=='READY'
    design_cases = CanonicalDesignService(truth,release_id=RELEASE,source_commit=COMMIT).load(release_batch_id=BATCH).cases
    assert {v['case_id'] for v in result['violations']}=={c['tc_id'] for c in design_cases}
    assert all(v['target_node']=='N4' for v in result['violations'])
    assert not truth.query('rc72_n6_executable_contract')
    requirements = truth.query('rc72_n5_data_requirement')
    required = {r['data_requirement_id'] for r in requirements}
    assert required and len(required)>2
    discovered = [item[1] for item in calls if isinstance(item,tuple) and item[0]=='data-discover']
    verified = [item[1] for item in calls if isinstance(item,tuple) and item[0]=='data-verify']
    assert set(discovered)==set(verified)==required
    assert len(discovered)==len(verified)==len(required)
    assert len(truth.query('rc72_n5_data_binding'))==len(required)
    assert all(p['status']=='REUSE_VERIFIED' for p in truth.query('rc72_n5_data_resolution_plan'))
    assert not truth.query('rc72_data_lease')
    assert all(t['state']=='PASS' for t in truth.query('rc7_task',node='TEST_DATA'))
    before = truth.store.path.read_bytes()
    count = len(calls)
    assert driver.run(release_batch_id=BATCH)==result
    assert truth.store.path.read_bytes()==before and len(calls)==count

    # Both accepted raw producer bytes and independent verifier bytes are
    # re-audited after N5 PASS, without restoring a live worker capability.
    for kind in ('rc72_n5_data_discovery_evidence_anchor','rc72_n5_data_verification_evidence_anchor'):
        anchor = truth.query(kind)[0]
        path = Path(anchor['raw_output_ref'][len('file://'):])
        original = path.read_bytes()
        path.write_bytes(original+b'\nchanged source proof\n')
        with pytest.raises(ContractError,match='OWNED_RAW_PROOF_CHANGED'):
            driver.run(release_batch_id=BATCH)
        assert truth.store.path.read_bytes()==before and len(calls)==count
        path.write_bytes(original)
    assert driver.run(release_batch_id=BATCH)==result
