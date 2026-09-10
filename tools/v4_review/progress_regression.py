#!/usr/bin/env python3
"""S4: production R1 + G2.1 + real controller subprocess; deterministic Host fixture.
Real product implementation under test; synthetic targets; NOT a real-model/L4 qualification.
"""
from __future__ import annotations
import argparse, collections, contextlib, datetime, hashlib, json, os, signal, sqlite3, subprocess, sys, threading, time, traceback
sys.dont_write_bytecode = True
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

REPO=Path(__file__).resolve().parents[2]
RUNTIME=REPO/'workspace-template/ai-test/runtime'
sys.path.insert(0,str(RUNTIME))
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.g2_1.managed_orchestration import default_g21_service
from aitest_runtime.durable_core import canonical_sha256
from aitest_runtime.r2_6 import HumanGateApplicationService
from aitest_runtime.r2_6.contracts import OUTCOMES, policy_digest


def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def save(path,obj): path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str)+'\n')
def append(path,obj):
    data=(json.dumps({'at':now(),**obj},ensure_ascii=False,default=str)+'\n').encode()
    fd=os.open(path,os.O_CREAT|os.O_APPEND|os.O_WRONLY,0o600)
    try: os.write(fd,data)
    finally: os.close(fd)
def rows(path):
    if not path.exists():return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
def runtime(root):return create_canonical_runtime(root,db_path=root/'state/runtime-spine.db')
def svc(root):return default_g21_service(runtime(root),root)
def wait_for(predicate,seconds=20):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        try:
            value=predicate()
            if value:return value
        except (FileNotFoundError,json.JSONDecodeError,sqlite3.OperationalError):pass
        time.sleep(.05)
    return None

def request(scenario):
    stamp=now(); expiry=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=1)).isoformat()
    return {'intake_id':'s4:'+scenario,'operation':'CREATE','scope':{'mode':'EXPLICIT_SET','project_id':'S4_SYNTHETIC','version':scenario,'requirements':['REQ-S4']},
        'goal':{'title':'S4 single synthetic goal','intent':'Run bounded synthetic worker progression; no bank quality claim','constraints':[]},
        'source':{'kind':'USER','source_ref':'s4-fixture-user-turn:'+scenario,'source_digest':canonical_sha256(scenario),'observed_at':stamp,'valid_until':None,'source_precedence':1},
        'actor':{'type':'USER','id':'LABELED_HOST_FIXTURE'},'resolution':{'resolution_id':'s4-resolution:'+scenario,'request_digest':canonical_sha256('resolve:'+scenario),'snapshot_id':'s4-snapshot:'+scenario,'fact_set_digest':canonical_sha256([]),'status':'RESOLVED','reason_code':None,'source_refs':['s4-fixture-user-turn:'+scenario],'valid_until':expiry}}
def proposal(scenario):
    keys=['A','B','C'] if scenario in {'happy','gate'} else ['A','B'] if scenario in {'failed','crash_gap'} else ['A']
    roles=['REQUIREMENT_ANALYST','CODE_ANALYST','EVALUATOR']
    return {'objective':'S4 synthetic durable liveness: '+scenario,'tasks':[{'task_key':k,'intent':'S4-WORK:'+k+':'+scenario,'acceptance_criteria':[{'id':k+'-receipt','description':'Synthetic file receipt matches actual bounded work'}],
        'routing':{'role':roles[i%3],'required_capabilities':['OPENCODE_AGENT_SESSION','TASK_OUTCOME_REPORT'],'isolation_policy':'DEDICATED_TASK_SESSION','parallelism_policy':'PARALLEL_SAFE'}} for i,k in enumerate(keys)],
        'dependencies':[{'from':'A','to':'C'}] if scenario=='gate' else [{'from':a,'to':b} for a,b in zip(keys,keys[1:])]}

def open_gate(root,env):
    routes={o:['NONE'] for o in OUTCOMES}; allowed=['EXTERNAL_ACTION_COMPLETED']; pol='s4-canonical-wait'
    a=runtime(root).replay_composed(env['mission_id']).extension_state('r1_3b_execution_resume').attempt(env['attempt_id'])
    return HumanGateApplicationService(runtime(root)).open_gate({'mission_id':env['mission_id'],'gate_id':'s4-gate','plan_id':a.plan_id,'plan_revision_id':a.plan_revision_id,'task_id':env['task_id'],'root_attempt_id':env['root_attempt_id'],'origin_attempt_id':env['attempt_id'],'origin_session_id':env['session_id'],'gate_kind':'EXTERNAL_ACTION','request_payload':{'action':'Synthetic explicit user action; do not auto-complete'},'response_schema':{'type':'object'},'expires_at':None,'expiry_policy':'NONE','decision_policy_id':pol,'decision_policy_version':1,'decision_policy_digest':policy_digest(pol,1,allowed,routes),'allowed_outcomes':allowed,'allowed_routes_by_outcome':routes,'request_provenance':{'source_ref':'s4-fixture-gate','source_digest':canonical_sha256('s4-fixture-gate'),'observed_at':now()},'actor':{'type':'SYSTEM','id':'S4_HOST_FIXTURE'}})

def worker(root,scenario,envelope_path):
    envelope=json.loads(envelope_path.read_text());mid=envelope['mission_id']
    if not envelope.get('task_id'):
        result=svc(root).propose_plan(mid,proposal(scenario));save(root/'planner-result.json',result);return 0
    sid=envelope['session_id']
    def bound():
        control=svc(root).session_control.state(mid)
        return any(p.external_session_id==sid and p.status=='BOUND' for p in control.provisions)
    if not wait_for(bound,12):raise RuntimeError('FIXTURE_BOUND_SESSION_TIMEOUT')
    task=runtime(root).replay_composed(mid).extension_state('r1_2_work_graph').task(envelope['task_id']);key=task.intent.split(':')[1]
    record={'scenario':scenario,'task_key':key,'task_id':envelope['task_id'],'mission_id':mid,'session_id':sid,'attempt_id':envelope['attempt_id'],'root_attempt_id':envelope['root_attempt_id'],'pid':os.getpid(),'generation':envelope['_fixture_generation']}
    append(root/'worker-starts.jsonl',record)
    if scenario=='gate' and key=='A':
        if envelope['_fixture_generation']==1:open_gate(root,envelope)
        append(root/'worker-waits.jsonl',{**record,'reason':'CANONICAL_GATE_PENDING'});return 0
    if scenario in {'idle','recovery','storm'} and envelope['_fixture_generation']==1 or scenario=='storm':
        append(root/'worker-waits.jsonl',{**record,'reason':'INJECTED_NONTERMINAL_IDLE' if scenario=='idle' else 'INJECTED_HOST_FAILURE'});return 0
    if scenario in {'busy','busy_pressure'}:
        append(root/'inflight.jsonl',{**record,'effect':'REAL_SCRATCH_FILE_WRITE_WAITING_RELEASE'})
        # This is an external-operation fixture: host abort does not revoke a sent operation.
        if not wait_for(lambda:(root/'release-busy.marker').exists(),22):raise RuntimeError('FIXTURE_BUSY_RELEASE_TIMEOUT')
    if scenario=='failed':
        action=subprocess.run([sys.executable,'-c','raise SystemExit(17)'],capture_output=True,text=True)
        append(root/'effects.jsonl',{**record,'exit_code':action.returncode,'outcome':'ACTUAL_SYNTHETIC_PROCESS_FAILURE'})
        outcome='FAILED'
    else:
        source=root/'input.txt';dest=root/'effects'/f"{key}-{sid}.json";dest.parent.mkdir(exist_ok=True)
        action=subprocess.run([sys.executable,'-c','import hashlib,json,pathlib,sys; p=pathlib.Path(sys.argv[1]);pathlib.Path(sys.argv[2]).write_text(json.dumps({"source_sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"bytes":p.stat().st_size}))',str(source),str(dest)],capture_output=True,text=True)
        append(root/'effects.jsonl',{**record,'exit_code':action.returncode,'artifact':str(dest),'artifact_sha256':hashlib.sha256(dest.read_bytes()).hexdigest() if dest.exists() else None})
        outcome='SUCCEEDED' if action.returncode==0 else 'FAILED'
    service=svc(root)
    if scenario=='crash_gap' and key=='A':
        # Fault injection kills this process at the real complete_task -> advance boundary.
        def crash_before_advance(*args,**kwargs):os._exit(73)
        service.advance=crash_before_advance
    try:
        result=service.report_task_outcome(mid,task_id=envelope['task_id'],attempt_id=envelope['attempt_id'],session_id=sid,outcome=outcome,summary='S4 labeled fixture actual process receipt; not G4/Case PASS',external_references=[{'namespace':'S4_SYNTHETIC_PROCESS','id':'effects.jsonl','version':hashlib.sha256((root/'effects.jsonl').read_bytes()).hexdigest()}])
        save(root/f'outcome-{sid}.json',result)
    except Exception as e:append(root/'worker-rejections.jsonl',{**record,'error':type(e).__name__,'detail':str(e)})
    return 0

class Host:
    def __init__(self,root,scenario,env):
        self.root=root;self.scenario=scenario;self.env=env;self.sessions={};self.messages={};self.count=0;self.generations=collections.Counter();self.processes=[];self.lock=threading.RLock()
    def prompt(self,sid,body):
        text=body['parts'][0]['text'];envelope=json.loads(text.split('\n',1)[1]);rootkey=envelope.get('root_attempt_id','PLANNER')
        with self.lock:
            self.generations[rootkey]+=1;generation=self.generations[rootkey];envelope['_fixture_generation']=generation
            data=self.sessions[sid];data['activity']='busy' if self.scenario in {'busy','busy_pressure'} and envelope.get('task_id') else 'idle'
            data['healthy']=not (self.scenario in {'recovery','storm'} and envelope.get('task_id') and (generation==1 or self.scenario=='storm'))
            if self.scenario=='busy_pressure' and envelope.get('task_id') and generation==1:data['contextUtilization']=.96
            self.messages[sid].append({'info':{'id':'m'+str(len(self.messages[sid])),'sessionID':sid,'role':'user'},'parts':body['parts']})
        path=self.root/'prompts'/f'{sid}-{generation}.json';path.parent.mkdir(exist_ok=True);save(path,envelope)
        append(self.root/'prompts.jsonl',{'session_id':sid,'generation':generation,'task_id':envelope.get('task_id'),'root_attempt_id':envelope.get('root_attempt_id'),'agent':body['agent'],'envelope_path':str(path),'digest':hashlib.sha256(text.encode()).hexdigest()})
        log=open(self.root/f'worker-{sid}-{generation}.log','w')
        proc=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'worker','--root',str(self.root),'--scenario',self.scenario,'--envelope',str(path)],env=self.env,cwd=self.root,stdout=log,stderr=subprocess.STDOUT)
        self.processes.append((proc,log))
    def close(self):
        for proc,log in self.processes:
            if proc.poll() is None:proc.terminate()
            try:proc.wait(timeout=3)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
            log.close()
        save(self.root/'host-worker-exits.json',[{'pid':p.pid,'exit_code':p.returncode} for p,_ in self.processes])

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def respond(self,value,code=200):
        data=json.dumps(value).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers()
        try:self.wfile.write(data)
        except BrokenPipeError:pass
    @property
    def host(self):return self.server.host
    def record(self):
        p=urlparse(self.path);append(self.host.root/'http.jsonl',{'method':self.command,'path':p.path,'directory':self.headers.get('x-opencode-directory'),'query':parse_qs(p.query)});return p.path
    def do_GET(self):
        p=self.record();h=self.host
        with h.lock:
            if p=='/global/health':return self.respond({'healthy':True})
            if p=='/session':return self.respond(list(h.sessions.values()))
            if p=='/session/status':return self.respond({k:{'type':v['activity']} for k,v in h.sessions.items()})
            if p.endswith('/message'):return self.respond(h.messages.get(p.split('/')[-2],[]))
            if p.startswith('/session/'):
                sid=p.rsplit('/',1)[1];return self.respond(h.sessions[sid]) if sid in h.sessions else self.respond({'error':'session missing'},404)
        self.respond({'error':'fixture unsupported'},404)
    def do_POST(self):
        p=self.record();h=self.host;body=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))) or '{}')
        with h.lock:
            if p=='/session':
                h.count+=1;sid='s4-host-'+str(h.count);h.sessions[sid]={'id':sid,'title':body.get('title'),'directory':str(h.root),'healthy':True,'messageCount':1,'compactionCount':0,'contextUsed':64,'contextLimit':32768,'contextUtilization':.01,'activity':'idle'};h.messages[sid]=[];return self.respond(h.sessions[sid])
            sid=p.split('/')[2] if len(p.split('/'))>2 else ''
            if p.endswith('/abort'):
                data=h.sessions.get(sid,{});append(h.root/'aborts.jsonl',{'session_id':sid,'activity_at_abort':data.get('activity')});data['activity']='idle';return self.respond(True)
            if p.endswith('/prompt_async'):
                self.respond({'accepted':True,'sessionID':sid});h.prompt(sid,body);return
        self.respond({'error':'fixture unsupported'},404)
    def do_DELETE(self):
        p=self.record();self.host.sessions.pop(p.rsplit('/',1)[1],None);self.respond(True)

def snapshot(root,mid,name):
    state=svc(root).status(mid);save(root/f'{name}.json',state);return state

def task_states(state):return {v['intent'].split(':')[1]:v['lifecycle_state'] for v in state['work_graph']['tasks']}
def summary_state(root,mid):
    rt=runtime(root);cs=rt.replay_composed(mid);graph=cs.extension_state('r1_2_work_graph');ex=cs.extension_state('r1_3b_execution_resume');ctrl=svc(root).session_control.state(mid)
    return {'mission_id':mid,'mission_status':cs.core_state.mission.status.value,'head_seq':rt.get_head_seq(mid),'tasks':{t.intent.split(':')[1]:t.lifecycle_state.value for t in graph.tasks},'attempts':[a.to_dict() for a in ex.attempts],'rotations':[r.to_dict() for r in ctrl.rotations],'provisions':[p.to_dict() for p in ctrl.provisions],'gates':[g.to_dict() for g in cs.extension_state('r2_6_human_gate').gates]}
def ticks(root):return [r for r in rows(root/'controller.log') if r.get('schema_version')=='aitest.g2.1.control-loop-tick.v1']

@contextlib.contextmanager
def environment(env):
    old=dict(os.environ);os.environ.clear();os.environ.update(env)
    try:yield
    finally:os.environ.clear();os.environ.update(old)

def run_scenario(base,scenario,interval):
    root=base/scenario;root.mkdir(parents=True);(root/'state').mkdir();(root/'home').mkdir();(root/'temp').mkdir();(root/'input.txt').write_text('S4 isolated synthetic source\n'*20)
    env={'PATH':os.environ.get('PATH',''),'HOME':str(root/'home'),'TMPDIR':str(root/'temp'),'PYTHONPATH':str(RUNTIME),'PYTHONDONTWRITEBYTECODE':'1','PYTHONUNBUFFERED':'1','AITEST_WORKSPACE_ROOT':str(root),'AITEST_RUNTIME_SPINE_DB':str(root/'state/runtime-spine.db')}
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);env['AITEST_OPENCODE_ENDPOINT']='http://127.0.0.1:'+str(server.server_port)
    host=Host(root,scenario,env);server.host=host;thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();loop=None;log=None;result={'scenario':scenario,'fixture':'DETERMINISTIC_HOST_TRANSPORT_AND_PLANNER_WORKER_FIXTURE','actual_runtime':'PRODUCT_UNDER_V4_IMPLEMENTATION','actual_model':'NONE','actual_layer':'L1_COMPONENT_WITH_REAL_LOCAL_HTTP_AND_SUBPROCESSES','checks':{}}
    try:
        with environment(env):
            started=svc(root).start_test(request(scenario));save(root/'single-goal-start.json',started);mid=started['intake']['intake']['mission_id'];result['mission_id']=mid
            Demand= lambda condition,msg: (_ for _ in ()).throw(RuntimeError(msg)) if not condition else None
            Demand(wait_for(lambda:rows(root/'worker-starts.jsonl'),15),'FIRST_WORKER_TIMEOUT')
            if scenario in {'happy','failed','crash_gap'}:
                Demand(wait_for(lambda:summary_state(root,mid)['tasks'].get('A') in {'SUCCEEDED','FAILED'},15),'FIRST_RESULT_TIMEOUT')
            if scenario=='gate':Demand(wait_for(lambda:summary_state(root,mid)['gates'],12),'GATE_OPEN_TIMEOUT')
            before=summary_state(root,mid);save(root/'before-controller.json',before)
            controller_start=time.monotonic()
            log=open(root/'controller.log','w');loop=subprocess.Popen([sys.executable,'-m','aitest_runtime.control_loop','--workspace-root',str(root),'--interval',str(interval)],env=env,cwd=root,stdout=log,stderr=subprocess.STDOUT)
            Demand(wait_for(lambda:len(ticks(root))>=10,22),'CONTROLLER_10_TICKS_TIMEOUT')
            observed=summary_state(root,mid);save(root/'after-10-ticks.json',observed)
            result['ticks']=len(ticks(root));result['before']=before;result['after']=observed
            result['controller_interval_seconds']=interval;result['observation_duration_seconds']=round(time.monotonic()-controller_start,3)
            starts=rows(root/'worker-starts.jsonl');effects=rows(root/'effects.jsonl');prompts=rows(root/'prompts.jsonl');checks=result['checks']
            with sqlite3.connect(root/'state/runtime-spine.db') as db:mission_count=db.execute("SELECT COUNT(DISTINCT mission_id) FROM events WHERE event_type='mission.created'").fetchone()[0]
            # Event name is emitted from actual event stream; generic distinct owner is also recorded.
            with sqlite3.connect(root/'state/runtime-spine.db') as db:
                events=[dict(zip([d[0] for d in c.description],row)) for c in [db.execute('SELECT seq,event_type,entity_type,entity_id,session_id,payload_json FROM events ORDER BY seq')] for row in c.fetchall()]
                mission_count=db.execute('SELECT COUNT(*) FROM mission_projection').fetchone()[0]
            save(root/'events-after-10-ticks.json',events);checks['one_mission_for_one_goal']=mission_count==1
            checks['all_provisions_have_unique_tokens']=len(observed['provisions'])==len({p['provision_token'] for p in observed['provisions']})
            if scenario=='happy':
                checks['three_workers_finish_without_second_user_input']=observed['tasks']=={'A':'SUCCEEDED','B':'SUCCEEDED','C':'SUCCEEDED'}
                checks['one_actual_effect_per_task']=collections.Counter(e['task_key'] for e in effects)=={'A':1,'B':1,'C':1}
                checks['no_worker_reprompt_after_completion']=len([p for p in prompts if p.get('task_id')])==3
            elif scenario=='idle':
                checks['idle_worker_automatically_resumes']=observed['tasks'].get('A')=='SUCCEEDED'
                # Independent oracle correction: generation1 intentionally exits;
                # successful AUTO_CONTINUE necessarily starts generation2.
                identity=('task_id','session_id','attempt_id','root_attempt_id')
                checks['idle_without_pressure_does_not_duplicate']=(
                    len(starts)==2 and [s['generation'] for s in starts]==[1,2]
                    and all(starts[0][k]==starts[1][k] for k in identity)
                    and len(observed['attempts'])==1 and not observed['rotations']
                    and len(effects)==1 and effects[0]['generation']==2
                    and len([p for p in prompts if p.get('task_id')])==2
                    and any(w['generation']==1 and w['reason']=='INJECTED_NONTERMINAL_IDLE' for w in rows(root/'worker-waits.jsonl')))
                checks['one_accepted_completion']=sum(e['event_type']=='task.outcome_recorded.v1' for e in events)==1
                result['no_progress_evidence']={'r1_sequence_delta':observed['head_seq']-before['head_seq'],'completed_task_delta':sum(x=='SUCCEEDED' for x in observed['tasks'].values())-sum(x=='SUCCEEDED' for x in before['tasks'].values()),'worker_prompt_count':len([p for p in prompts if p.get('task_id')])}
            elif scenario=='recovery':
                checks['unhealthy_session_automatically_recovers']=observed['tasks'].get('A')=='SUCCEEDED'
                checks['same_root_attempt_across_recovery']=len({a['root_attempt_id'] for a in observed['attempts']})==1 and len(observed['attempts'])==2
                checks['one_effect_after_recovery']=len(effects)==1
                checks['one_rotation_only']=len(observed['rotations'])==1
                old=before['attempts'][0];head=runtime(root).get_head_seq(mid)
                try:svc(root).report_task_outcome(mid,task_id=old['task_id'],attempt_id=old['attempt_id'],session_id=old['runtime_session_id'],outcome='SUCCEEDED',summary='S4 late stale caller attack');rejected=False
                except Exception as e:rejected=True;result['late_completion_error']=str(e)
                checks['stale_predecessor_completion_rejected_without_event']=rejected and head==runtime(root).get_head_seq(mid)
            elif scenario in {'busy','busy_pressure'}:
                checks['busy_external_operation_not_reprompted']=len(starts)==1
                checks['busy_session_not_aborted']=not rows(root/'aborts.jsonl')
                checks['one_inflight_effect']=len(rows(root/'inflight.jsonl'))==1
                (root/'release-busy.marker').touch();wait_for(lambda:summary_state(root,mid)['tasks'].get('A')=='SUCCEEDED',15);wait_for(lambda:all(p.poll() is not None for p,_ in host.processes),5)
                effects=rows(root/'effects.jsonl');checks['one_actual_effect_after_release']=len(effects)==1
                save(root/'after-busy-release.json',summary_state(root,mid));result['effects_after_release']=effects
            elif scenario=='failed':
                checks['failed_process_recorded_as_failed']=observed['tasks'].get('A')=='FAILED' and effects and effects[0]['exit_code']==17
                checks['failure_does_not_run_dependent_or_fake_success']=observed['tasks'].get('B')!='SUCCEEDED' and len(effects)==1
                checks['mission_failure_or_recovery_is_explicit']=observed['mission_status']!='ACTIVE' or observed['tasks'].get('A')!='FAILED'
            elif scenario=='crash_gap':
                checks['completion_receipt_durable_before_crash']=observed['tasks'].get('A')=='SUCCEEDED'
                checks['controller_recovers_dispatch_gap']=observed['tasks'].get('B')=='SUCCEEDED'
                result['worker_exit_codes']=[p.poll() for p,_ in host.processes]
            elif scenario=='gate':
                checks['gate_remains_pending_without_human_answer']=any(g['status']=='PENDING' for g in observed['gates'])
                checks['waiting_gate_no_extra_A_prompt']=len([s for s in starts if s['task_key']=='A'])==1
                checks['controller_dispatches_independent_B_while_A_waits']=observed['tasks'].get('B')=='SUCCEEDED'
                checks['dependent_C_stays_blocked']=observed['tasks'].get('C')!='SUCCEEDED'
                # Separate capability probe: stop autonomous loop, then explicitly invoke actual Scheduler.
                loop.terminate();loop.wait(timeout=5);loop=None
                manual=svc(root).advance(mid);save(root/'explicit-scheduler-probe.json',manual)
                wait_for(lambda:summary_state(root,mid)['tasks'].get('B')=='SUCCEEDED',15)
                after=summary_state(root,mid);save(root/'after-explicit-scheduler-probe.json',after)
                result['diagnostic_component_probe']={'explicit_scheduler_dispatched_independent_B':after['tasks'].get('B')=='SUCCEEDED','is_autonomous_evidence':False}
            elif scenario=='storm':
                checks['repeated_same_failure_gets_bounded_terminal_or_wait']=observed['mission_status']!='ACTIVE' or len(observed['rotations'])<5
                result['observed_rotation_count']=len(observed['rotations']);result['observed_actual_effect_count']=len(effects)
            result['status']='ALL_SCENARIO_CHECKS_TRUE' if all(checks.values()) else 'V4_REQUIREMENT_GAPS_OBSERVED'
            final=summary_state(root,mid);save(root/'final-state.json',final)
            result['controller_failures']= [r for r in rows(root/'controller.log') if r.get('status')=='TICK_FAIL']
            checks['controller_ticks_without_error']=not result['controller_failures']
            result['status']='ALL_SCENARIO_CHECKS_TRUE' if all(checks.values()) else 'V4_REQUIREMENT_GAPS_OBSERVED'
            result['http_session_status_reads']=sum(r['path']=='/session/status' for r in rows(root/'http.jsonl'))
            result['product_projection_verify']=runtime(root).verify_projection(mid)
    except Exception as e:result.update(status='HARNESS_OR_ENVIRONMENT_ERROR',error=repr(e),traceback=traceback.format_exc())
    finally:
        if loop is not None:
            loop.terminate()
            try:loop.wait(timeout=5)
            except subprocess.TimeoutExpired:loop.kill();loop.wait()
        if log:log.close()
        host.close();server.shutdown();server.server_close();thread.join(timeout=2)
        result['worker_exits']=[p.returncode for p,_ in host.processes];result['artifact_root']=str(root);save(root/'result.json',result)
    print(json.dumps({'scenario':scenario,'status':result['status'],'checks':result.get('checks'),'error':result.get('error')},ensure_ascii=False),flush=True)
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['worker','run']);p.add_argument('--root',type=Path,required=True);p.add_argument('--scenario');p.add_argument('--envelope',type=Path);p.add_argument('--interval',type=float,default=1.1);p.add_argument('--scenarios',default='happy,idle,recovery,busy,busy_pressure,failed,crash_gap,gate,storm');a=p.parse_args()
    if a.mode=='worker':raise SystemExit(worker(a.root,a.scenario,a.envelope))
    a.root=a.root.resolve();a.root.mkdir(parents=True,exist_ok=False)
    (a.root/'harness-source.py').write_bytes(Path(__file__).read_bytes())
    results=[run_scenario(a.root,s,a.interval) for s in a.scenarios.split(',')]
    save(a.root/'summary.json',{'source_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),'source_clean':not subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True).strip(),'spike':'S4-LIVENESS','actual_model':'NONE','runtime':'PRODUCT_UNDER_V4_IMPLEMENTATION','qualification':'LABELED_HOST_FIXTURE_NOT_L4','results':[{'scenario':r['scenario'],'status':r['status'],'checks':r.get('checks'),'artifact_root':r['artifact_root']} for r in results]})
