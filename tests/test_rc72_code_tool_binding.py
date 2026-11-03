"""Real Node execution of the production policy, plus registered MCP binding."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest
from rc6_runtime.process_environment import scoped_process_environment
from rc7_release.dsh import _tool_policy_plugin_source
from rc7_release.mcp_server import _extra_tools
from rc7_runtime.rc72_code_tool_binding import NATIVE_CODE_TOOLS, canonical_code_tools, has_codegraph_execution


def test_native_names_are_registered_and_graph_catalogue_cannot_stand_in_for_execution():
    names={row['name'] for row in _extra_tools()}
    assert all(name[len('mcp__pfc_aitest_rc7__'):] in names for name in NATIVE_CODE_TOOLS)
    assert canonical_code_tools(list(reversed(NATIVE_CODE_TOOLS)),allow_legacy=False)==NATIVE_CODE_TOOLS
    assert not has_codegraph_execution({NATIVE_CODE_TOOLS[-2]})
    assert has_codegraph_execution({NATIVE_CODE_TOOLS[-1]})
    with pytest.raises(ValueError):canonical_code_tools(['git','codegraph'],allow_legacy=False)
    with pytest.raises(ValueError):canonical_code_tools(['gitnexus','codegraph'],allow_legacy=False)


def test_production_policy_exposes_concrete_code_tools_and_guards_execution(tmp_path):
    node=shutil.which('node')
    if not node:pytest.skip('actual Node required for generated DSH policy qualification')
    plugin=tmp_path/'policy.mjs';plugin.write_text(_tool_policy_plugin_source())
    harness=tmp_path/'probe.mjs'
    harness.write_text('''import {apply} from './policy.mjs';
const outer={},hooks={};let executionGuard;
const names=JSON.parse(process.env.PFC_RC7_DSH_ALLOWED_TOOLS);
let available=names.map(name=>({name})).concat([{name:'unrelated_tool'}]);
const scope={on:(name,fn)=>{hooks[name]=fn},effect:fn=>fn(),
 tools:{guard:fn=>{executionGuard=fn;return ()=>{}},schemas:()=>available},
 systemPrompt:{section:()=>{}}};
apply({on:(name,fn)=>{outer[name]=fn}});
outer['agent/created']({agent:{ctx:scope}});
const visible=await hooks['system-prompt/assemble']({}, {}, async()=>({tools:[]}));
if(JSON.stringify(visible.tools.map(t=>t.name))!==JSON.stringify(names))throw Error('projection');
if(names.some(name=>executionGuard({name})!==undefined))throw Error('authorized execution denied');
if(!executionGuard({name:'unrelated_tool'}))throw Error('extra execution admitted');
available=available.filter(t=>t.name!==names[names.length-1]);
let refused=false;
try{await hooks['system-prompt/assemble']({}, {}, async()=>({tools:[]}))}
catch(error){refused=error.message.startsWith('RC7_DSH_REQUIRED_TOOL_NOT_REGISTERED:')}
if(!refused)throw Error('missing concrete graph call not detected');
process.stdout.write(JSON.stringify({visible:names,ungranted_execution_refused:true,missing_graph_call_refused:true}));
''')
    environment=scoped_process_environment({'PFC_RC7_DSH_ALLOWED_TOOLS':json.dumps(NATIVE_CODE_TOOLS)},home=tmp_path/'private-home')
    result=subprocess.run([node,str(harness)],env=environment,cwd=tmp_path,capture_output=True,text=True,timeout=15,check=False)
    assert result.returncode==0,result.stderr
    proof=json.loads(result.stdout)
    assert proof['visible']==list(NATIVE_CODE_TOOLS)
    assert proof['ungranted_execution_refused'] is proof['missing_graph_call_refused'] is True
