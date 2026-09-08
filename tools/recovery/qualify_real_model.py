"""Construction-only real host model probe; no authored Plan or provider override."""
import argparse,base64,hashlib,json,os,platform,shutil,socket,subprocess,sys,time,uuid,threading,urllib.request
from datetime import datetime,timezone,timedelta
from pathlib import Path
parser=argparse.ArgumentParser()
parser.add_argument('--repo',type=Path,required=True)
parser.add_argument('--payload-workspace',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--host-opencode',type=Path,required=True)
parser.add_argument('--timeout',type=int,default=600)
args=parser.parse_args();repo=args.repo.resolve();run=args.output.resolve();ws=run/'workspace'
ws.mkdir(parents=True,exist_ok=False)
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def file_sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
started_at=datetime.now(timezone.utc).isoformat()

head=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
assert not subprocess.check_output(['git','-C',str(repo),'status','--porcelain'],text=True).strip()
for name in ('.opencode','ai-test'):
 shutil.copytree(repo/'workspace-template'/name,ws/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc','node_modules'))
for name in ('AGENTS.md','opencode.json'):
 shutil.copy2(repo/'workspace-template'/name,ws/name)
# Only dependency bytes may come from the local payload cache; Agent and tool
# source must remain the exact clean Git checkout under qualification.
shutil.copytree(args.payload_workspace/'.opencode/node_modules',ws/'.opencode/node_modules')
(ws/'INSTALL_MANIFEST.json').write_text(json.dumps({'classification':'CONSTRUCTION_REAL_MODEL_ONLY','source_head':head}))
if os.name=='nt':shutil.copytree(args.payload_workspace/'runtime/python',ws/'runtime/python')
else:
 (ws/'runtime/python').mkdir(parents=True);(ws/'runtime/python/python').symlink_to(sys.executable)
subprocess.run(['git','init','--quiet','--template=',str(ws)],check=True)
sys.path[:0]=[str(repo/'tools/recovery'),str(ws/'ai-test/runtime')]
from host_opencode import CapabilityClient
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
from aitest_runtime.autonomous_orchestration import DirectoryScopedOpenCodeSessionProvider
with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
env=dict(os.environ)
for k in ('GH_TOKEN','GITHUB_TOKEN'):env.pop(k,None)
env.update(AITEST_WORKSPACE_ROOT=str(ws),AITEST_RUNTIME_SPINE_DB=str(ws/'data/state/runtime-spine.db'),PFC_LOCAL_STATE_ROOT=str(ws/'data'),
 AITEST_OPENCODE_ENDPOINT=f'http://127.0.0.1:{port}',OPENCODE_SERVER_USERNAME='opencode',OPENCODE_SERVER_PASSWORD=uuid.uuid4().hex,
 OPENCODE_DISABLE_AUTOUPDATE='1',OPENCODE_DISABLE_MODELS_FETCH='1',OPENCODE_DISABLE_DEFAULT_PLUGINS='1',OPENCODE_DISABLE_LSP_DOWNLOAD='1',OPENCODE_DISABLE_SHARE='1',
 npm_config_offline='true',npm_config_registry='http://127.0.0.1:9',PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=os.pathsep.join([str(ws/'ai-test/runtime'),os.environ.get('PYTHONPATH','')]))
# XDG_CONFIG_HOME, host model selection, provider config, and authentication are untouched.
client=CapabilityClient(env['AITEST_OPENCODE_ENDPOINT'],ws,env)
result={'source_head':head,'classification':'REAL_HOST_MODEL_SEMANTIC_PLANNING_ONLY','BANK_FIELD_VALIDATION_REQUIRED':True,
 'schema_version':'aitest.real-semantic-planner-proof.v1','harness_sha256':file_sha(Path(__file__)),
 'product_version':'1.13.0','source_branch':subprocess.check_output(['git','-C',str(repo),'branch','--show-current'],text=True).strip(),
 'host_system':platform.system(),'started_at':started_at,'source_workspace':str(ws),'source_clean':True,
 'user_request':'测试 BLOAN-PF1.1.0','external_input_scope':'PUBLIC_PACKAGE_AND_SYNTHETIC_LOCAL_LOAN_ONLY','host_provider_auth_copied':False,'script_authored_plan':False,'status':'FAIL','gates':{'AUTONOMOUS_PLAN':'NOT_PROVEN'}}
server=loop=None;old=dict(os.environ);seeded=False;tool_receipts={};model_identities=set();event_response=None;event_ready=threading.Event()
# Actual loopback service and a tiny Git project, visibly synthetic source input.
sys.path.insert(0,str(repo/'workspace-template/.pfc-internal-field-validation/tests'))
from test_rec3_business_contracts import BusinessService
from http.server import ThreadingHTTPServer
business=ThreadingHTTPServer(('127.0.0.1',0),BusinessService)
threading.Thread(target=business.serve_forever,daemon=True).start()
origin='http://127.0.0.1:'+str(business.server_port)
code=ws/'synthetic-loan';code.mkdir()
def git(*args):return subprocess.check_output(['git','-C',str(code),*args],text=True).strip()
git('init','--quiet');(code/'loan.py').write_text('def quote(amount):\n    return {"amount": amount, "fee": amount * .02}\n')
git('add','.');git('-c','user.name=REC3 Synthetic Fixture','-c','user.email=fixture@invalid','commit','-qm','Synthetic baseline')
base_ref=git('rev-parse','HEAD');(code/'loan.py').write_text('def quote(amount):\n    if not 0 < amount <= 1000: return {"error": "LIMIT"}\n    return {"amount": amount, "fee": amount * .02}\n')
git('add','.');git('-c','user.name=REC3 Synthetic Fixture','-c','user.email=fixture@invalid','commit','-qm','Synthetic amount boundary')
head_ref=git('rev-parse','HEAD')
(ws/'bindings').mkdir(exist_ok=True)
(ws/'bindings/execution.json').write_text(json.dumps({'approved':True,'approval_ref':'SYNTHETIC_QUALIFICATION_ONLY','allowed_origins':[origin],'allowed_methods':['GET','POST']}))
doc=ws/'synthetic-requirement.md';doc.write_text('# SYNTHETIC QUALIFICATION ONLY\nProject BLOAN, release BLOAN-PF1.1.0. This is a local loan service, not bank evidence. Requirement LOCAL-LOAN-R1: amount must be positive and at most 1000; fee equals 2 percent of amount. Check boundary amounts 0,1,1000,1001 and the arithmetic relation. Code revisions and approved local service are in Current Release and binding_context. External bank access is outside this synthetic scope.\n')
def seed_inputs(runtime,mission):
 from aitest_runtime.recovery_intake import RecoveryIntakeService
 intake=RecoveryIntakeService(runtime);intake.import_document(mission,doc,'LOCAL-LOAN-R1')
 now=datetime.now(timezone.utc);path=ws/'synthetic-current-release.json'
 path.write_text(json.dumps({'project_id':'BLOAN','release_id':'BLOAN-PF1.1.0','revision':'1','observed_at':now.isoformat(),
  'requirements':[{'requirement_id':'LOCAL-LOAN-R1','sst_ids':[]}],
  'repositories':[{'repository_id':'LOCAL-LOAN','application_id':'LOCAL-LOAN','repository_path':str(code),'base_ref':base_ref,'head_ref':head_ref}]}))
 approval={'adapter':'APPROVED_EXPORT','source_system':'STARLINK','binding_id':'SYNTHETIC-ONLY','revision':'1','project_id':'BLOAN','release_id':'BLOAN-PF1.1.0',
  'approved_by':'CONSTRUCTION_SYNTHETIC_FIXTURE','approval_ref':'SYNTHETIC_QUALIFICATION_ONLY','approved_at':now.isoformat(),'valid_until':(now+timedelta(hours=1)).isoformat(),'expected_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
 intake.import_current_release(mission,path,approval)

try:
 server=subprocess.Popen([str(args.host_opencode),'serve','--hostname','127.0.0.1','--port',str(port)],cwd=ws,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 deadline=time.monotonic()+45
 while time.monotonic()<deadline:
  try:
   if client.request('GET','/global/health',timeout=1).get('healthy'):break
  except Exception:time.sleep(.25)
 original_request=client.request
 def bounded_catalog_request(method,path,body=None,**kw):
  result['last_probe_path']=path.split('?')[0]
  if path=='/provider':kw['budget']=16*1024*1024
  return original_request(method,path,body,**kw)
 client.request=bounded_catalog_request
 result['capabilities']=client.probe()
 # Observe the host's actual tool events. Never supply model responses or Plan content.
 def observe_tools():
  global event_response
  auth=base64.b64encode(('opencode:'+env['OPENCODE_SERVER_PASSWORD']).encode()).decode()
  request=urllib.request.Request(env['AITEST_OPENCODE_ENDPOINT']+'/event',headers={'Authorization':'Basic '+auth})
  try:
   event_response=urllib.request.urlopen(request,timeout=args.timeout+30);event_ready.set()
   for line in event_response:
    if len(line)>65536 or not line.startswith(b'data:'):continue
    event=json.loads(line[5:]);props=event.get('properties',{})
    if event.get('type')=='message.updated':
     info=props.get('info',{})
     if info.get('role')=='assistant' and info.get('providerID') and info.get('modelID'):
      model_identities.add((info['providerID'],info['modelID']))
    if event.get('type')!='message.part.updated':continue
    part=props.get('part',{});state=part.get('state',{});inputs=state.get('input',{})
    if part.get('type')!='tool' or part.get('tool') not in ('aitest_director','aitest_planner'):continue
    action=inputs.get('action')
    if action not in ('start_test','propose_plan'):continue
    proposal=(inputs.get('payload') or {}).get('proposal') or inputs.get('proposal')
    receipt={'session_id':part.get('sessionID'),'call_id':part.get('callID'),'tool':part.get('tool'),'action':action,
      'status':state.get('status'),'input_digest':digest(inputs),'proposal_digest':digest(proposal) if proposal else None,
      'task_count':len(proposal.get('tasks',[])) if isinstance(proposal,dict) else 0}
    tool_receipts[(part.get('sessionID'),part.get('callID'))]=receipt
  except Exception as exc:result['event_observer_error']=type(exc).__name__;event_ready.set()
 threading.Thread(target=observe_tools,daemon=True).start()
 if not event_ready.wait(10) or event_response is None:raise RuntimeError('REAL_TOOL_EVENT_OBSERVER_REQUIRED')
 os.environ.update(env);runtime=create_canonical_runtime(ws)
 provider=DirectoryScopedOpenCodeSessionProvider(ws,timeout=20)
 with (run/'control-loop.log').open('w') as log:
  loop=subprocess.Popen([sys.executable,'-m','aitest_runtime.control_loop','--workspace-root',str(ws),'--interval','3'],cwd=ws,env=env,stdout=log,stderr=subprocess.STDOUT)
 director=client.request('POST','/session',{'title':'REC3 synthetic goal real semantic Planner qualification'})['id']
 client.request('POST',f'/session/{director}/prompt_async',{'parts':[{'type':'text','text':'测试 BLOAN-PF1.1.0'}]})
 result['director_session_id']=director;deadline=time.monotonic()+args.timeout
 while time.monotonic()<deadline:
  messages=client.request('GET',f'/session/{director}/message?limit=10')
  errors=[m['info']['error'].get('name','UNKNOWN') for m in messages if m.get('info',{}).get('error')]
  if errors:result['model_errors']=errors;break
  service=G21AutonomousOrchestrationService(runtime,ws,session_provider=provider)
  missions=service._all_mission_ids()
  if missions:
   mission=missions[0]
   if not seeded:
    # Import after the natural-language Mission admission has finished binding
    # its Planner, as the normal user-facing attachment entry does.
    admitted=service.session_control.state(mission)
    if not any(p.role=='PLANNER' and p.status=='BOUND' for p in admitted.provisions):
     time.sleep(.1);continue
    seed_inputs(runtime,mission);seeded=True
   state=runtime.replay_composed(mission);graph=state.extension_state('r1_2_work_graph');control=service.session_control.state(mission)
   planners=[p for p in control.provisions if p.role=='PLANNER' and p.external_session_id]
   workers=[p for p in control.provisions if p.task_id and p.external_session_id]
   # Local diagnostic observations only, never sent back into a prompt.
   snapshots=[]
   for provision in planners:
    try:
     seen=client.request('GET',f'/session/{provision.external_session_id}/message?limit=30')
     snapshots.append({'session_id':provision.external_session_id,'messages':[{'role':m.get('info',{}).get('role'),'agent':m.get('info',{}).get('agent'),'error':m.get('info',{}).get('error',{}).get('name'),
      'parts':[{'type':p.get('type'),'text':str(p.get('text',''))[:2500],'tool':p.get('tool'),'status':p.get('state',{}).get('status'),'action':p.get('state',{}).get('input',{}).get('action'),'output':str(p.get('state',{}).get('output',''))[:2500],'error':str(p.get('state',{}).get('error',''))[:1000]} for p in m.get('parts',[]) if p.get('type') in ('text','tool')]} for m in seen]})
    except Exception:pass
   if snapshots:(run/'planner-observations.json').write_text(json.dumps(snapshots,ensure_ascii=False,indent=2))
   result.update(mission_id=mission,planner_sessions=[p.external_session_id for p in planners],task_count=len(graph.tasks),worker_sessions=[p.external_session_id for p in workers])
   semantic=[r for r in list(tool_receipts.values()) if r['action']=='propose_plan' and r['task_count']>=2 and r['session_id'] in [p.external_session_id for p in planners]]
   actual_models=[{'provider_id':p,'model_id':m} for p,m in sorted(model_identities) if 'fixture' not in (p+' '+m).lower()]
   if planners and workers and len(graph.tasks)>=2 and semantic and actual_models and all(p.external_session_id!=director for p in planners+workers):
    result.update(status='PASS',gates={'AUTONOMOUS_PLAN':'PASS'},r1_cursor=runtime.get_head_seq(mission),plan_tasks_digest=hashlib.sha256(json.dumps(graph.to_dict(),sort_keys=True).encode()).hexdigest())
    result.update(semantic_planner='REAL_HOST_MODEL',model_identities=actual_models,tool_receipts=list(tool_receipts.values()),
     plan_events=[{'seq':e.seq,'type':e.event_type,'payload_digest':digest(e.payload)} for e in runtime.list_events(mission) if 'plan' in e.event_type or 'task_route' in e.event_type],
     synthetic_requirement_sha256=file_sha(doc),r1_event_digest=digest([e.to_dict() for e in runtime.list_events(mission)]))
    break
  if loop.poll() is not None:raise RuntimeError('CONTROL_LOOP_EXITED')
  time.sleep(1)
except Exception as exc:result.update(error_type=type(exc).__name__,error_capability=getattr(exc,'capability',None),error_code=getattr(exc,'code',None))
finally:
 for p in (loop,server):
  if p is not None and p.poll() is None:
   p.terminate()
   try:p.wait(timeout=10)
   except subprocess.TimeoutExpired:p.kill();p.wait()
 if event_response is not None:event_response.close()
 business.shutdown();business.server_close()
 os.environ.clear();os.environ.update(old)
 result['completed_at']=datetime.now(timezone.utc).isoformat()
 if subprocess.check_output(['git','-C',str(repo),'status','--porcelain'],text=True).strip() or subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()!=head:
  result.update(status='FAIL',source_clean=False,gates={'AUTONOMOUS_PLAN':'SOURCE_CHANGED'})
 result['report_path']=str(run/'result.json');(run/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(result,ensure_ascii=False,indent=2))

raise SystemExit(0 if result['status']=='PASS' else 1)
