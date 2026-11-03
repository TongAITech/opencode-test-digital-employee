"""Actual MCP child sees tool-only env; synthetic tool, no bank or model calls."""
import json
from pathlib import Path
import sys

import pytest
from rc7_release import codegraph_mcp
from rc7_release.mcp_stdio import JsonLineMcpClient


@pytest.mark.parametrize('fail',[False,True])
def test_codegraph_child_has_private_home_and_no_worker_or_model_credentials(tmp_path,monkeypatch,fail):
    repo=tmp_path/'approved-repository';repo.mkdir()
    captain=tmp_path/'captain-home';captain.mkdir()
    (captain/'marker').write_text('private-profile-marker')
    for name in ('HOME','USERPROFILE','DSH_HOME','APPDATA','LOCALAPPDATA'):
        monkeypatch.setenv(name,str(captain))
    for name in ('SELECTED_MODEL_API_KEY','UNRELATED_MODEL_TOKEN','CAPTAIN_SIGNING_KEY',
                 'PFC_RC72_TOOL_GATE_TOKEN','PFC_RC72_TOOL_GATE_URL','PFC_RC72_TOOL_GATE_CONTEXT'):
        monkeypatch.setenv(name,'private-'+name)
    script=tmp_path/'codegraph-engineering-server.py'
    script.write_text('''import json,os,sys
from pathlib import Path
for line in sys.stdin:
 request=json.loads(line);method=request['method']
 if 'id' not in request:continue
 if method=='initialize':result={'protocolVersion':'2024-11-05','capabilities':{'tools':{}},'serverInfo':{'name':'engineering-graph','version':'1'}}
 elif method=='tools/list':result={'tools':[{'name':'search_symbols','description':'engineering query','inputSchema':{'type':'object'}}]}
 elif method=='tools/call':
  result={'content':[{'type':'text','text':json.dumps({'home':os.environ['HOME'],'cwd':os.getcwd(),
   'keys':sorted(os.environ),'marker':(Path(os.environ['HOME'])/'marker').exists()})}]}
 else:result={}
 print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}),flush=True)
''')
    homes=[];clients=[]
    def client(command,**kwargs):
        assert command==['configured-codegraph-binary']
        home=Path(kwargs['env']['HOME']);homes.append(home)
        assert home.is_dir()
        if fail:raise RuntimeError('engineering startup failure')
        actual=JsonLineMcpClient([sys.executable,str(script)],**kwargs)
        clients.append(actual)
        return actual
    monkeypatch.setattr(codegraph_mcp,'_resolve_binary',lambda name:'configured-codegraph-binary')
    monkeypatch.setattr(codegraph_mcp,'JsonLineMcpClient',client)
    monkeypatch.setenv('PFC_WORKSPACE',str(repo))
    if fail:
        with pytest.raises(RuntimeError,match='engineering startup failure'):
            codegraph_mcp.list_codegraph_tools()
    else:
        response=codegraph_mcp.call_codegraph_tool(tool_name='search_symbols',arguments={'query':'ApprovedType'})
        actual=json.loads(response['result']['content'][0]['text'])
        assert Path(actual['cwd']).resolve()==repo.resolve()
        assert Path(actual['home'])!=captain and actual['marker'] is False
        assert all('MODEL' not in key and 'CAPTAIN' not in key and not key.startswith('PFC_RC72_TOOL_GATE_') for key in actual['keys'])
        assert 'DSH_HOME' not in actual['keys']
        assert all(c.proc.poll() is not None for c in clients)
    assert homes and all(not h.exists() for h in homes)


def test_direct_code_tool_process_also_drops_provider_and_gate_environment(tmp_path,monkeypatch):
    from rc7_release.professional_tools import _run
    home=tmp_path/'private-bank-home';home.mkdir()
    (home/'marker').write_text('profile marker')
    monkeypatch.setenv('HOME',str(home))
    monkeypatch.setenv('DSH_HOME',str(home))
    monkeypatch.setenv('APPROVED_MODEL_TOKEN','synthetic-model-secret')
    monkeypatch.setenv('PFC_RC72_TOOL_GATE_TOKEN','synthetic-native-capability')
    code="import os,json;from pathlib import Path;print(json.dumps(dict(home=os.environ['HOME'],keys=sorted(os.environ),marker=(Path(os.environ['HOME'])/'marker').exists())))"
    result=_run([sys.executable,'-c',code],cwd=tmp_path)
    observed=json.loads(result['stdout']['text'])
    assert not observed['marker'] and Path(observed['home'])!=home
    assert not Path(observed['home']).exists()
    assert 'DSH_HOME' not in observed['keys']
    assert 'APPROVED_MODEL_TOKEN' not in observed['keys']
    assert 'PFC_RC72_TOOL_GATE_TOKEN' not in observed['keys']


def test_read_only_diff_does_not_execute_repository_textconv(tmp_path,monkeypatch):
    import subprocess
    from test_rc7_professional_tools import _git_repo
    from rc7_release.professional_tools import git_diff
    _,repo,base,head=_git_repo(tmp_path,monkeypatch)
    (repo/'.gitattributes').write_text('RateService.java diff=scope_probe\n')
    subprocess.run(['git','config','diff.scope_probe.textconv','rc72_nonexistent_textconv_command'],
        cwd=repo,check=True,capture_output=True)
    control=subprocess.run(['git','diff','--no-ext-diff',base,head],cwd=repo,capture_output=True,text=True)
    assert control.returncode!=0
    assert 'textconv' in control.stderr.lower()
    result=git_diff(repo_path='cfg-data',base_ref=base,head_ref=head)
    assert result['changed_files']==['RateService.java']
    assert 'limit = 1' in result['diff']['text'] and 'limit = 2' in result['diff']['text']
