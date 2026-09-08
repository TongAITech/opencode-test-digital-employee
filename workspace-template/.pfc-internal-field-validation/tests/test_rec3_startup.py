"""Actual installed daily launcher + external host OpenCode; no model call."""
import hashlib
import json
import os
from pathlib import Path
import sys


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
    heartbeat=launcher.read(installed/'data/state/control-loop-heartbeat.json')
    assert heartbeat['endpoint']==result['endpoint']
    assert heartbeat['workspace_root']==str(installed)
    print(json.dumps({'status':'PASS','classification':'WINDOWS_INSTALLED_HOST_NATIVE_NO_MODEL',
      'gates':{g:'PASS' for g in ('HOST_NATIVE_OPENCODE','HOST_PROVIDER_AUTH_PRESERVED','AITEST_WORKSPACE_LOADED','CONTROL_LOOP_BOUND')},
      'probe':result,'bank_model_turn':'NOT_EXECUTED','BANK_FIELD_VALIDATION_REQUIRED':True},ensure_ascii=False))

if __name__=='__main__':main()
