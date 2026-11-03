"""Inherited version-era final tools cannot certify the RC7.2 ReleaseBatch."""
import json,os,shutil,subprocess
from pathlib import Path
import pytest
from rc7_release.bank_field_launcher import run_bank_final
from rc7_release.final_qualification import evaluate_final_qualification


def test_legacy_bank_final_dispatch_never_starts_external_services_for_rc72(tmp_path,monkeypatch):
    (tmp_path/'RELEASE_FAMILY').write_text('RC7.2\n')
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:pytest.fail('inherited final tool started'))
    assert run_bank_final(dict(package_root=str(tmp_path)))==37


@pytest.mark.parametrize('name',['QUALIFY-FINAL.sh','QUALIFY-BANK-FINAL.sh'])
def test_actual_inherited_shell_entry_refuses_rc72_before_python_or_service_io(tmp_path,name):
    bash=shutil.which('bash')
    if not bash:pytest.skip('bash contract covered in engineering platform CI')
    repo=Path(__file__).resolve().parents[1];target=tmp_path/'packaging/rc7'/name;target.parent.mkdir(parents=True)
    shutil.copy2(repo/'packaging/rc7'/name,target);(tmp_path/'RC72_RELEASE_IDENTITY.json').write_text('{}')
    result=subprocess.run([bash,str(target)],capture_output=True,text=True,timeout=10)
    assert result.returncode==37
    assert json.loads(result.stderr)['reason']=='RC72_NATIVE_RELEASE_FINAL_AND_BANK_PC_PIP_MIRROR_GATE_REQUIRED'


def test_old_final_report_format_cannot_accept_a_renamed_rc72_delivery():
    from test_rc7_delivery_closure import _gate,_delivery,COMMIT
    delivery=_delivery();delivery['package_name']='PFC-AITest-DSH-Turnkey-RC7.2-BANK-WIN10'
    result=evaluate_final_qualification(COMMIT,_gate('ENGINEERING_PASS'),_gate('ADMIN_PLATFORM_PASS'),None,delivery)
    assert result['status']=='HOLD'
    assert any('RC72_NATIVE_RELEASE_FINAL_AND_BANK_PC_PIP_MIRROR_GATE_REQUIRED' in b for b in result['blocking_reasons'])


@pytest.mark.parametrize('name',['QUALIFY-FINAL.cmd','QUALIFY-BANK-FINAL.cmd'])
@pytest.mark.skipif(os.name!='nt',reason='actual Windows CMD entry checked by Windows qualification')
def test_actual_windows_inherited_final_entry_refuses_rc72(tmp_path,name):
    repo=Path(__file__).resolve().parents[1];target=tmp_path/'packaging/rc7'/name;target.parent.mkdir(parents=True)
    shutil.copy2(repo/'packaging/rc7'/name,target);(tmp_path/'RC72_RELEASE_IDENTITY.json').write_text('{}')
    result=subprocess.run([os.environ['COMSPEC'],'/d','/c',str(target)],capture_output=True,text=True,timeout=10)
    assert result.returncode==37 and 'RC72_NATIVE_RELEASE_FINAL_AND_BANK_PC_PIP_MIRROR_GATE_REQUIRED' in result.stderr
