"""Fresh package ingress preserves original metadata, never seeds Q7 or nodes."""
import json
import subprocess
import sys

import pytest
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_batch_registration import SCHEMA, read_batch_input, register_batch
from rc7_runtime.rc72_release_driver import release_batch_status
from rc7_release.rc72_mission_cli import main

COMMIT = 'a'*40


def _input(tmp_path):
    root = tmp_path/'package'
    root.mkdir()
    (root/'SOURCE_COMMIT').write_text(COMMIT)
    data = dict(schema=SCHEMA, release_id='RELEASE-1', source_commit=COMMIT,
        release_batch_id='BATCH-1', mission_id='MISSION-1', name='Original batch',
        planned_release_time=None, version_ids=['version-1'],
        application_ids=['APP-1'], requirement_ids=['REQ-1','REQ-2'])
    path = tmp_path/'approved.json'
    path.write_text(json.dumps(data))
    ledger = tmp_path/'state'/'r1.jsonl'
    args = ['register','--ledger',str(ledger),'--package-root',str(root),
        '--batch-input',str(path),'--release-id','RELEASE-1','--release-batch','BATCH-1',
        '--source-commit',COMMIT]
    return data, path, ledger, args


def test_fresh_registration_and_cold_retry_are_atomic_and_do_not_start_mission(tmp_path,capsys):
    data,path,ledger,args = _input(tmp_path)
    assert not ledger.exists()
    assert main(args)==0
    result=json.loads(capsys.readouterr().out)
    assert result['status']=='REGISTERED' and not result['field_verified'] and not result['bank_final']
    before=ledger.read_bytes()
    assert len(before.splitlines())==1
    assert main(args)==0
    capsys.readouterr()
    assert ledger.read_bytes()==before
    cold=TruthRuntime(ledger)
    batch=cold.query('rc72_release_batch')[0]
    assert batch['requirement_ids']==data['requirement_ids']
    assert batch['state']=='REGISTERED' and batch['readiness']=='UNKNOWN'
    assert batch['registration']['source_ref']==path.as_uri()
    assert not cold.query('rc72_mission_node')
    assert not cold.query('rc72_q7_admission')
    assert not cold.query('rc7_evidence')
    assert release_batch_status(cold,source_commit=COMMIT,release_batch_id='BATCH-1')['nodes']==[]
    with pytest.raises(ContractError,match='REGISTERED_SOURCE_MISMATCH'):
        release_batch_status(cold,source_commit='b'*40,release_batch_id='BATCH-1')


@pytest.mark.parametrize('change',['status','readiness','field','unknown','empty_requirements',
    'duplicate_requirements','source','release','batch','bad_identity','duplicate_key','too_large'])
def test_invalid_original_input_refused_before_ledger_creation(tmp_path,capsys,change):
    data,path,ledger,args=_input(tmp_path)
    if change=='status': data['state']='PASS'
    elif change=='readiness': data['readiness']='READY'
    elif change=='field': data['field_verified']=True
    elif change=='unknown': data['gate']={'status':'PASS'}
    elif change=='empty_requirements': data['requirement_ids']=[]
    elif change=='duplicate_requirements': data['requirement_ids']*=2
    elif change=='source': data['source_commit']='b'*40
    elif change=='release': data['release_id']='foreign'
    elif change=='batch': data['release_batch_id']='foreign'
    elif change=='bad_identity': data['mission_id']=' mission '
    path.write_text(json.dumps(data))
    if change=='duplicate_key': path.write_text(path.read_text().replace('{','{"schema":"other",',1))
    if change=='too_large': path.write_bytes(b' '*1048577)
    assert main(args)==37
    result=json.loads(capsys.readouterr().out)
    assert result['status']=='HOLD' and not result['bank_final']
    assert not ledger.exists()


@pytest.mark.parametrize('change',['bytes','requirements','mission','release'])
def test_registration_cannot_rewrite_original_denominator_or_adopt_another_batch(tmp_path,capsys,change):
    data,path,ledger,args=_input(tmp_path)
    assert main(args)==0
    capsys.readouterr()
    before=ledger.read_bytes()
    if change=='requirements': data['requirement_ids']=['REQ-1']
    elif change=='mission': data['mission_id']='OTHER-MISSION'
    elif change=='release': data['release_id']='OTHER-RELEASE'
    path.write_text(json.dumps(data,indent=2))
    assert main(args)==37
    capsys.readouterr()
    assert ledger.read_bytes()==before


def test_direct_registration_cannot_import_pass_state(tmp_path):
    _,path,ledger,_=_input(tmp_path)
    payload=read_batch_input(path,release_id='RELEASE-1',source_commit=COMMIT,release_batch_id='BATCH-1')
    from rc7_runtime.rc72_truth import install_rc72_truth_overlay
    install_rc72_truth_overlay()
    truth=TruthRuntime(ledger)
    payload['state']='PASS'
    with pytest.raises(ContractError,match='INITIAL_METADATA_ONLY'):
        register_batch(truth,payload)
    assert not ledger.read_bytes()


def test_retry_preserves_later_canonical_batch_state_without_a_new_write(tmp_path,capsys):
    _,_,ledger,args=_input(tmp_path)
    assert main(args)==0
    capsys.readouterr()
    truth=TruthRuntime(ledger)
    row=truth.query('rc72_release_batch')[0]
    row.update(state='RUNNING',readiness='CHECKING',artifact_version=2)
    truth.append_atomic('RC72_RELEASE_BATCH_UPSERTED',row)
    before=ledger.read_bytes()
    assert main(args)==0
    capsys.readouterr()
    assert ledger.read_bytes()==before
    assert TruthRuntime(ledger).query('rc72_release_batch')[0]['state']=='RUNNING'


def test_fresh_cli_process_can_register_then_cold_status_without_in_process_overlay_state(tmp_path):
    _,_,ledger,args=_input(tmp_path)
    registered=subprocess.run([sys.executable,'-m','rc7_release.rc72_mission_cli',*args],
        capture_output=True,text=True,timeout=20,check=True)
    assert json.loads(registered.stdout)['status']=='REGISTERED'
    before=ledger.read_bytes()
    status=subprocess.run([sys.executable,'-m','rc7_release.rc72_mission_cli','status',
        '--ledger',str(ledger),'--source-commit',COMMIT,'--release-batch','BATCH-1'],
        capture_output=True,text=True,timeout=20,check=True)
    assert json.loads(status.stdout)['nodes']==[]
    assert ledger.read_bytes()==before
