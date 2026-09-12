"""Real Host/model Primary admission probe; no General file rerun or L4 claim."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
from contextlib import closing
import subprocess
import sys
import time
import uuid


def main():
    p=argparse.ArgumentParser()
    for name in ('repo','dependencies','opencode','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--timeout',type=int,default=120);args=p.parse_args()
    repo=args.repo.resolve();out=args.output.resolve();ws=out/'workspace';ws.mkdir(parents=True,exist_ok=False)
    for name in ('.opencode','ai-test'):
        shutil.copytree(repo/'workspace-template'/name,ws/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc','node_modules','state','evidence'))
    for name in ('opencode.json','AGENTS.md'):shutil.copyfile(repo/'workspace-template'/name,ws/name)
    shutil.copytree(args.dependencies,ws/'.opencode/node_modules')
    head=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
    dirty=subprocess.check_output(['git','-C',str(repo),'status','--porcelain'],text=True)
    sources={str(f.relative_to(ws)):hashlib.sha256(f.read_bytes()).hexdigest() for f in ws.rglob('*') if f.is_file() and 'node_modules' not in f.parts}
    (ws/'INSTALL_MANIFEST.json').write_text(json.dumps({'classification':'PRIMARY_BINDING_COMPONENT','head':head,'source_snapshot':sources}))
    (ws/'runtime/python').mkdir(parents=True);(ws/'runtime/python/python').symlink_to(sys.executable)
    subprocess.run(['git','init','--quiet','--template=',str(ws)],check=True)
    sys.path[:0]=[str(repo/'tools/recovery'),str(ws/'ai-test/runtime')]
    from host_opencode import CapabilityClient
    from aitest_runtime.canonical_runtime import create_canonical_runtime
    from aitest_runtime.autonomous_orchestration import DirectoryScopedOpenCodeSessionProvider
    from aitest_runtime.primary_sessions import PrimarySessionOwner
    from aitest_runtime import product_entry
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    env=dict(os.environ)
    for k in ('GH_TOKEN','GITHUB_TOKEN'):env.pop(k,None)
    env.update(AITEST_WORKSPACE_ROOT=str(ws),AITEST_RUNTIME_SPINE_DB=str(ws/'data/state/runtime-spine.db'),PFC_LOCAL_STATE_ROOT=str(ws/'data'),
        AITEST_OPENCODE_ENDPOINT='http://127.0.0.1:'+str(port),OPENCODE_SERVER_USERNAME='opencode',OPENCODE_SERVER_PASSWORD=uuid.uuid4().hex,
        OPENCODE_DISABLE_AUTOUPDATE='1',OPENCODE_DISABLE_MODELS_FETCH='1',OPENCODE_DISABLE_DEFAULT_PLUGINS='1',OPENCODE_DISABLE_LSP_DOWNLOAD='1',OPENCODE_DISABLE_SHARE='1',
        npm_config_offline='true',npm_config_registry='http://127.0.0.1:9',PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(ws/'ai-test/runtime'))
    client=CapabilityClient(env['AITEST_OPENCODE_ENDPOINT'],ws,env)
    result={'classification':'REAL_HOST_PRIMARY_BINDING_COMPONENT_NOT_L4','source_head':head,'source_dirty':bool(dirty),'source_snapshot':sources,
        'status':'FAIL','bank_field':'NOT_RUN','director_auto_rotation':'NOT_TESTED','user_technical_command_count':0,
        'host_auth_or_model_config_modified':False,'default_plugins':'DISABLED_FOR_ISOLATED_COMPONENT_PROBE'}
    server=None;created=[]
    try:
        with (out/'host.log').open('w') as log:server=subprocess.Popen([str(args.opencode),'serve','--hostname','127.0.0.1','--port',str(port)],cwd=ws,env=env,stdout=log,stderr=subprocess.STDOUT)
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            try:
                if client.request('GET','/global/health',timeout=1).get('healthy'):break
            except Exception:time.sleep(.25)
        else:raise RuntimeError('HOST_START_FAILED')
        runtime=create_canonical_runtime(ws,db_path=ws/'data/state/runtime-spine.db')
        provider=DirectoryScopedOpenCodeSessionProvider(ws,base_url=env['AITEST_OPENCODE_ENDPOINT'],username=env['OPENCODE_SERVER_USERNAME'],password=env['OPENCODE_SERVER_PASSWORD'])
        owner=PrimarySessionOwner(runtime,ws,provider);binding=owner.ensure_current();sid=binding['session_id'];created.append(sid)
        result['initial_binding']=binding
        client.request('POST','/session/'+sid+'/prompt_async',{'agent':'aitest-director','parts':[{'type':'text','text':'请查看当前测试任务状态，只查询状态，不创建或执行测试。'}]})
        deadline=time.monotonic()+args.timeout;observed=None;rows=[]
        while time.monotonic()<deadline:
            rows=client.request('GET','/session/'+sid+'/message?limit=20',budget=1024*1024)
            for row in rows:
                for part in row.get('parts',[]):
                    if part.get('type')=='tool' and part.get('tool')=='aitest_director' and part.get('state',{}).get('status')=='completed':
                        raw=part['state'].get('output','')
                        try:value=json.loads(raw)
                        except (ValueError,TypeError):continue
                        if value.get('primary_binding',{}).get('session_id')==sid:observed=(row,part,value)
            if observed:break
            time.sleep(.5)
        (out/'host-messages.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
        if observed is None:raise RuntimeError('ACTUAL_PRIMARY_TOOL_SUCCESS_NOT_OBSERVED')
        row,part,value=observed;result['actual_tool_result']=value;result['model_identity']={k:row['info'].get(k) for k in ('providerID','modelID')}
        if not all(result['model_identity'].values()):raise RuntimeError('ACTUAL_MODEL_IDENTITY_REQUIRED')
        # This is explicit component fencing, not automatic pressure rotation.
        owner.fence('COMPONENT_STALE_CALL_PROBE');new=owner.ensure_current();created.append(new['session_id']);result['successor_binding']=new
        previous=dict(os.environ)
        try:
            os.environ.update(env,AITEST_HOST_SESSION_ID=sid,AITEST_HOST_MESSAGE_ID=row['info']['id'],AITEST_HOST_CALL_ID=part['callID'])
            try:product_entry.orchestration_command('DIRECTOR','status',part['state']['input']['payload'])
            except Exception as exc:result['old_call_denial']=getattr(exc,'code',str(exc))
        finally:os.environ.clear();os.environ.update(previous)
        with closing(sqlite3.connect(runtime.db_path)) as conn:result['mission_count']=conn.execute('SELECT count(*) FROM mission_projection').fetchone()[0]
        result['status']='PASS' if result.get('old_call_denial')=='STALE_CALLER' and result['mission_count']==0 and new['epoch']==2 and new['logical_agent_id']==binding['logical_agent_id'] else 'FAIL'
    except Exception as exc:result['error']=type(exc).__name__+': '+str(exc)[:1000]
    finally:
        for sid in created:
            try:client.request('POST','/session/'+sid+'/abort',{})
            except Exception:pass
        if server and server.poll() is None:
            server.terminate()
            try:server.wait(timeout=5)
            except subprocess.TimeoutExpired:server.kill();server.wait()
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({k:v for k,v in result.items() if k!='source_snapshot'},ensure_ascii=False,indent=2))
    return 0 if result['status']=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())
