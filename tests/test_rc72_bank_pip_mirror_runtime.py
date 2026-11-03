"""Receipt-control unit tests; actual pip effects are qualified on Windows."""
import hashlib,json
from pathlib import Path
import pytest
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_bank_pip_mirror import NativeBankPipMirrorService
from test_rc72_field_qualification import _batch,RELEASE,BATCH,COMMIT


def _setup(tmp_path,monkeypatch):
    from rc7_release import bank_pc_pip_mirror_probe as probe
    root=tmp_path/'component';root.mkdir();(root/'SOURCE_COMMIT').write_text(COMMIT)
    archive=tmp_path/'component.zip';archive.write_bytes(b'unit binding, not a real package archive')
    config=tmp_path/'field.json';config.write_text('{"spec":"unit-fixture==1","module":"unit_fixture"}')
    appdata=tmp_path/'user appdata';user=appdata/'pip/pip.ini';user.parent.mkdir(parents=True);user.write_text('[global]\nindex-url=https://owned.invalid/simple\n')
    monkeypatch.setattr(probe,'windows_user_appdata',lambda:appdata);monkeypatch.setenv('APPDATA',str(appdata));monkeypatch.delenv('PIP_CONFIG_FILE',raising=False)
    authority=RC72AuthorityRuntime(b'unit-mirror-receipt-authority')
    truth=TruthRuntime(tmp_path/'r1.jsonl')
    service=NativeBankPipMirrorService(truth,release_id=RELEASE,source_commit=COMMIT,authority=authority,
        package_root=root,archive=archive,field_config=config,evidence_root=tmp_path/'receipts')
    _batch(truth);calls=[]
    def observed(root,archive,policy,evidence,**kwargs):
        # Simulate only the producer protocol; no claim of actual pip effects.
        calls.append(kwargs);private=Path(evidence)/'private';private.mkdir(parents=True)
        files={name+'.'+suffix+'.log' for name in ('pip-version','provenance','config-debug','config-list','mirror-install','same-interpreter-import','provenance-after') for suffix in ('stdout','stderr')}|{'install-report.json'}
        for name in files:(private/name).write_text('unit protocol observation')
        return dict(gate='BANK_PC_PIP_MIRROR_GATE',schema='RC72_BANK_PC_PIP_MIRROR_V1',
            qualification_scope='ENGINEERING_WINDOWS_USER_MIRROR_SIMULATION',status='PASS',source_commit=COMMIT,archive_sha256=hashlib.sha256(Path(archive).read_bytes()).hexdigest(),
            package_root=str(root),discovery=dict(user_config_sha256=hashlib.sha256(user.read_bytes()).hexdigest()),
            bank_pc_mirror_field_fact=not kwargs['engineering'],bank_final=False,field_verified=False,
            private_evidence_sha256={name:hashlib.sha256((private/name).read_bytes()).hexdigest() for name in files})
    monkeypatch.setattr(probe,'qualify',observed)
    return truth,service,calls


def test_owned_receipt_cold_reentry_is_readonly_and_never_upgrades_engineering(tmp_path,monkeypatch):
    truth,service,calls=_setup(tmp_path,monkeypatch)
    result=service.run(release_batch_id=BATCH,engineering=True)
    assert result['status']=='PASS' and result['bank_pc_mirror_field_fact'] is False and len(calls)==1
    before=truth.store.path.read_bytes()
    cold=NativeBankPipMirrorService(truth,release_id=RELEASE,source_commit=COMMIT,authority=service.authority,
        package_root=service.root,archive=service.archive,field_config=service.config,evidence_root=service.evidence)
    assert cold.audit(execution_id=result['execution_id'],release_batch_id=BATCH,require_field=False)==result
    assert cold.run(release_batch_id=BATCH,engineering=True)==result and len(calls)==1
    assert truth.store.path.read_bytes()==before
    with pytest.raises(ContractError,match='ENGINEERING_NOT_FIELD'):cold.audit(execution_id=result['execution_id'],release_batch_id=BATCH)


@pytest.mark.parametrize('changed',['signature','marker','private-log','archive','policy','source'])
def test_native_receipt_rejects_changed_scope_evidence_and_signature(tmp_path,monkeypatch,changed):
    truth,service,calls=_setup(tmp_path,monkeypatch);result=service.run(release_batch_id=BATCH,engineering=True)
    row=truth.query('rc72_bank_pip_mirror_execution')[0]
    if changed=='signature':
        row['signature']='0'*64;row['artifact_version']+=1;truth.append_atomic('RC72_BANK_PIP_MIRROR_EXECUTION_UPSERTED',row)
    elif changed=='marker':Path(result['result_ref'][7:]).write_text('{"status":"PASS"}')
    elif changed=='private-log':next(service.evidence.rglob('provenance.stdout.log')).write_text('changed')
    elif changed=='archive':service.archive.write_bytes(b'changed')
    elif changed=='policy':service.config.write_text('{}')
    else:(service.root/'SOURCE_COMMIT').write_text('f'*40)
    with pytest.raises((ContractError,KeyError,ValueError)):
        service.audit(execution_id=result['execution_id'],release_batch_id=BATCH,require_field=False)
    assert len(calls)==1


def test_unknown_execution_never_replays_even_when_retry_requested(tmp_path,monkeypatch):
    truth,service,calls=_setup(tmp_path,monkeypatch)
    from rc7_release import bank_pc_pip_mirror_probe as probe
    def interrupted(*args,**kwargs):raise KeyboardInterrupt()
    monkeypatch.setattr(probe,'qualify',interrupted)
    with pytest.raises(KeyboardInterrupt):service.run(release_batch_id=BATCH,engineering=True)
    assert truth.query('rc72_bank_pip_mirror_execution')[0]['state']=='UNKNOWN'
    before=truth.store.path.read_bytes()
    result=service.run(release_batch_id=BATCH,engineering=True,retry_returned_failure=True)
    assert result['reason']=='BANK_PIP_MIRROR_UNKNOWN_NO_REPLAY' and truth.store.path.read_bytes()==before and not calls


def test_returned_failures_have_bounded_explicit_new_attempts(tmp_path,monkeypatch):
    truth,service,calls=_setup(tmp_path,monkeypatch)
    from rc7_release import bank_pc_pip_mirror_probe as probe
    def failed(*args,**kwargs):calls.append(1);raise RuntimeError('fixture producer failed')
    monkeypatch.setattr(probe,'qualify',failed)
    assert service.run(release_batch_id=BATCH,engineering=True)['status']=='HOLD'
    assert service.run(release_batch_id=BATCH,engineering=True)['reason']=='BANK_PIP_MIRROR_RETURNED_FAILURE'
    for _ in range(2):assert service.run(release_batch_id=BATCH,engineering=True,retry_returned_failure=True)['status']=='HOLD'
    assert service.run(release_batch_id=BATCH,engineering=True,retry_returned_failure=True)['reason']=='BANK_PIP_MIRROR_RETRY_LIMIT'
    assert len(calls)==3 and len(truth.query('rc72_bank_pip_mirror_execution'))==3



def test_authenticated_returned_marker_recovers_metadata_without_repeating_effect(tmp_path,monkeypatch):
    truth,service,calls=_setup(tmp_path,monkeypatch)
    real=service._persist;failures=[]
    def interrupted_receipt(row):
        if row['state']=='RETURNED' and not failures:
            failures.append(1);raise RuntimeError('interrupted canonical metadata write')
        return real(row)
    monkeypatch.setattr(service,'_persist',interrupted_receipt)
    with pytest.raises(RuntimeError):service.run(release_batch_id=BATCH,engineering=True)
    assert truth.query('rc72_bank_pip_mirror_execution')[0]['state']=='UNKNOWN' and len(calls)==1
    result=service.run(release_batch_id=BATCH,engineering=True)
    assert result['status']=='PASS' and len(calls)==1
    assert truth.query('rc72_bank_pip_mirror_execution')[0]['state']=='RETURNED'


def test_unsigned_returned_marker_never_promotes_unknown_or_replays(tmp_path,monkeypatch):
    truth,service,calls=_setup(tmp_path,monkeypatch)
    from rc7_release import bank_pc_pip_mirror_probe as probe
    def interrupted(*args,**kwargs):raise KeyboardInterrupt()
    monkeypatch.setattr(probe,'qualify',interrupted)
    with pytest.raises(KeyboardInterrupt):service.run(release_batch_id=BATCH,engineering=True)
    row=truth.query('rc72_bank_pip_mirror_execution')[0]
    path=service.evidence/row['execution_id']/'controller-result.json'
    path.write_text(json.dumps(dict(execution_id=row['execution_id'],binding=row['binding'],status='PASS')))
    with pytest.raises(ContractError,match='SIGNATURE_OR_SCOPE'):
        service.run(release_batch_id=BATCH,engineering=True,retry_returned_failure=True)
    assert not calls and truth.query('rc72_bank_pip_mirror_execution')[0]['state']=='UNKNOWN'
