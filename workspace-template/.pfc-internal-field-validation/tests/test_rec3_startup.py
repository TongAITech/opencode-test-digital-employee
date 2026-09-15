"""Actual installed daily launcher + external host OpenCode; no model call."""
import hashlib
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch


def main():
    installed=Path(os.environ['AITEST_INSTALLED']).resolve()
    host=Path(os.environ['AITEST_CI_HOST']).resolve()
    assert not host.is_relative_to(installed)
    sys.path.insert(0,str(installed/'tools/recovery'))
    import launcher
    assert launcher.WORKSPACE==installed
    files=[host/'config/opencode/opencode.json',host/'data/opencode/auth.json']
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    before={str(p):sha(p) for p in files}
    keys=('XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_CACHE_HOME','XDG_STATE_HOME','OPENCODE_CONFIG','OPENCODE_CONFIG_DIR','OPENCODE_CONFIG_CONTENT')
    env_before={k:os.environ.get(k) for k in keys}
    result=launcher.start_conversation(check_only=True)
    assert result['gates']['AITEST_WORKSPACE_LOADED']=='PASS'
    assert result['gates']['CONTROL_LOOP_BINDING']=='PASS'
    assert Path(result['host_executable']).is_relative_to(host)
    assert before=={str(p):sha(p) for p in files}
    assert env_before=={k:os.environ.get(k) for k in keys}
    assert not (installed/'runtime/opencode').exists()
    assert not (installed/'data/opencode-config').exists()

    # Launcher dispatch must not repeat the expensive whole-install hash before
    # the selected operation. start_conversation() above already exercised the
    # real deep doctor/integrity path once. Evidence export is read-only and is
    # admitted by durable installed identity.
    with patch.object(sys,'argv',['launcher.py','--self-check']), \
         patch.object(launcher,'verify_daily_install'), \
         patch.object(launcher,'prepare'), \
         patch.object(launcher,'verify_files',side_effect=AssertionError('duplicate full scan')), \
         patch.object(launcher,'start_conversation',return_value={'gates':{'CONTROL_LOOP_BINDING':'PASS'}}) as start:
        assert launcher.main()==0
        start.assert_called_once_with(check_only=True)
    with patch.object(sys,'argv',['launcher.py','--export-evidence']), \
         patch.object(launcher,'verify_daily_install'), \
         patch.object(launcher,'prepare'), \
         patch.object(launcher,'verify_files',side_effect=AssertionError('export must not full-scan')), \
         patch.object(launcher,'evidence_export',return_value='fixture.zip') as export:
        assert launcher.main()==0
        export.assert_called_once_with()

    # Interactive mode keeps the historical deep integrity boundary exactly
    # once before exposing any mutating menu operation.
    with patch.object(sys,'argv',['launcher.py']), \
         patch.object(launcher,'verify_daily_install'), \
         patch.object(launcher,'prepare'), \
         patch.object(launcher,'verify_files',return_value=[]) as verify, \
         patch('builtins.input',return_value='0'):
        assert launcher.main()==0
        verify.assert_called_once_with()

    heartbeat=launcher.read(installed/'data/state/control-loop-heartbeat.json')
    assert heartbeat['endpoint']==result['endpoint']
    assert heartbeat['workspace_root']==str(installed)
    print(json.dumps({'status':'PASS','classification':'WINDOWS_INSTALLED_HOST_NATIVE_NO_MODEL',
      'gates':{g:'PASS' for g in ('HOST_NATIVE_OPENCODE','HOST_PROVIDER_AUTH_PRESERVED','AITEST_WORKSPACE_LOADED','CONTROL_LOOP_BOUND')},
      'probe':result,'bank_model_turn':'NOT_EXECUTED','BANK_FIELD_VALIDATION_REQUIRED':True},ensure_ascii=False))

if __name__=='__main__':main()
