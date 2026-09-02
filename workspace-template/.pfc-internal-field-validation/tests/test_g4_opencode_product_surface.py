from __future__ import annotations
import json, os, subprocess, sys, tempfile
from pathlib import Path

WORKSPACE=Path(__file__).resolve().parents[2]
AGENTS=WORKSPACE/'.opencode/agents'
COMMANDS=WORKSPACE/'.opencode/commands'
TOOL=(WORKSPACE/'.opencode/tools/aitest.ts').read_text(encoding='utf-8')
ENTRY=(WORKSPACE/'ai-test/runtime/aitest_runtime/product_entry.py').read_text(encoding='utf-8')
G4=(WORKSPACE/'ai-test/runtime/aitest_runtime/g4/service.py').read_text(encoding='utf-8')

def txt(path: Path)->str: return path.read_text(encoding='utf-8')

def main()->int:
    checks={}
    director=txt(AGENTS/'aitest-director.md'); executor=txt(AGENTS/'aitest-executor.md')
    requirement=txt(AGENTS/'aitest-requirement-analyst.md'); strategist=txt(AGENTS/'aitest-test-strategist.md')
    designer=txt(AGENTS/'aitest-case-designer.md'); evaluator=txt(AGENTS/'aitest-evaluator.md')
    execute=txt(COMMANDS/'aitest-execute.md'); preflight=txt(COMMANDS/'aitest-preflight.md')
    api=txt(COMMANDS/'aitest-api-test-design.md'); ui=txt(COMMANDS/'aitest-ui-test-design.md')
    sec=txt(COMMANDS/'aitest-security-test-design.md'); perf=txt(COMMANDS/'aitest-performance-test-design.md')
    teach=txt(COMMANDS/'aitest-browser-teach.md')
    checks['01_director_g4_authority_open_g5_g6_hold']='aitest_g4_director: allow' in director and 'G4 real execution' in director and 'G5 confirmed-defect truth' in director and 'G6 continuous closed loop remain HOLD' in director
    checks['02_executor_agent_executes_g4_without_session_ownership']='authorized real execution' in executor and 'Step Cursor' in executor and 'Human Takeover' in executor and 'Do not observe, create, close, or rotate your own Session' in executor
    checks['03_g3_roles_do_not_execute_but_no_false_g4_hold']=all('G4 HOLD' not in s and 'G4 remains HOLD' not in s for s in (requirement,strategist,designer,evaluator)) and 'G4 Executor' in requirement and 'G4 may execute' in strategist and 'G4 Executor' in designer and 'Authorized execution belongs to G4' in evaluator
    checks['04_execute_command_routes_router_bound_g4']='agent: aitest-executor' in execute and 'aitest_executor' in execute and 'G4 actions' in execute and 'HumanGate' in execute and 'TEST_FAIL != CONFIRMED_DEFECT' in execute and '当前 HOLD' not in execute
    checks['05_preflight_reports_g1_g4_truth_not_legacy']='G1-G4' in preflight and 'aitest_g4_director' in preflight and 'R1 Event Stream' in preflight and 'legacy runtime' in preflight and '当前 HOLD' not in preflight
    checks['06_api_ui_design_handoff_to_g4']=all('G4 Router-bound' in s for s in (api,ui)) and '不得猜 URL' in api and 'HumanGate/BrowserLease' in ui
    checks['07_security_performance_design_profiles_then_g4']=all('G4 Router-bound' in s and 'fail closed' in s for s in (sec,perf)) and '不得发明 SLA/SLO' in perf and 'destructive=false by default' in sec
    checks['08_browser_teach_boundary_is_g6_not_false_g4_pending']='G4 受控浏览器真实执行' in teach and 'G6/知识演化' in teach and 'G4/G6` canonical product wiring 尚未通过' not in teach
    checks['09_tool_g4_wrapper_calls_product_entry_and_r1']='aitest_runtime.product_entry", "g4"' in TOOL and 'AITEST_G4_TRUTH_CONTRACT_FAILED' in TOOL and 'R1_EVENT_STREAM' in TOOL
    checks['10_tool_executor_and_director_expose_authorized_g4_actions']='request_human_takeover|reconcile_human_takeover|complete_human_takeover' in TOOL and 'execute_capability' in TOOL and 'create_goal|control_tick|coverage_from_g3' in TOOL and 'return g4(context as ToolContext, "EXECUTOR"' in TOOL
    checks['11_product_entry_g4_enabled_g5_g6_hold']='G4_PRODUCT_ENTRY' in ENTRY and 'G4 real-execution tools' in ENTRY and 'G5 defect truth and G6 closed-loop mutations remain HOLD' in ENTRY and '"g4"' in ENTRY
    checks['12_command_tool_entry_r1_chain']='agent: aitest-executor' in execute and 'return g4(context as ToolContext, "EXECUTOR"' in TOOL and 'def g4_command(' in ENTRY and 'self.runtime.execute({' in G4 and '"truth_source": "R1_EVENT_STREAM"' in G4
    # Product subprocess must be able to load an explicitly configured provider factory;
    # in-process monkeypatch injection is not a valid OpenCode composition mechanism.
    with tempfile.TemporaryDirectory(prefix='g4-provider-factory-') as td:
        temp=Path(td)
        (temp/'g4_test_provider.py').write_text('''
class Provider:
    capability_id = "API"
    capability_status = "AVAILABLE"
    safety_profile = {}
    auth_requirements = {}
    side_effect_classification = "READ_ONLY"
    retry_semantics = {}
    evidence_channels = ("fixture",)
    def prepare(self, step, runtime_facts): return dict(step)
    def execute(self, prepared, execution_context): return {"ok": True}
    def observe(self, result): return dict(result)
    def collect_evidence(self, result): return ["fixture:evidence"]
    def cleanup(self, result): return {"ok": True}
def factory(root=None, profile=None):
    return {"capability_executors": {"API": Provider()}}
''',encoding='utf-8')
        env=os.environ.copy(); runtime=str(WORKSPACE/'ai-test/runtime'); env['PYTHONPATH']=str(temp)+os.pathsep+runtime; env['AITEST_WORKSPACE_ROOT']=str(WORKSPACE); env['AITEST_RUNTIME_SPINE_DB']=str(temp/'runtime-spine.db'); env['AITEST_G4_PROVIDER_FACTORY']='g4_test_provider:factory'
        payload={'mission_id':'surface-provider-load','capability_id':'API','executor_request':{'url':'https://sut.test/ping','method':'GET','authorized_scope':{'environment':'TEST'}}}
        proc=subprocess.run([sys.executable,'-m','aitest_runtime.product_entry','g4','--role','EXECUTOR','--action','validate_executor','--payload',json.dumps(payload)],cwd=str(WORKSPACE),env=env,text=True,capture_output=True,timeout=60)
        try: result=json.loads(proc.stdout)
        except Exception: result={}
        checks['13_subprocess_provider_factory_composition']=proc.returncode==0 and result.get('truth_source')=='R1_EVENT_STREAM' and result.get('status')=='AVAILABLE' and result.get('decision',{}).get('capability_id')=='API'
    checks['14_provider_factory_is_explicit_and_fail_closed']='load_provider_bundle' in ENTRY and 'AITEST_G4_PROVIDER_FACTORY' in (WORKSPACE/'ai-test/runtime/aitest_runtime/g4/composition.py').read_text(encoding='utf-8') and 'UNCONFIGURED' in (WORKSPACE/'ai-test/runtime/aitest_runtime/g4/composition.py').read_text(encoding='utf-8')
    out={'status':'PASS' if all(checks.values()) else 'FAIL','passed':sum(bool(v) for v in checks.values()),'total':len(checks),'checks':checks}
    print(json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True)); return 0 if out['status']=='PASS' else 1

if __name__=='__main__': raise SystemExit(main())
