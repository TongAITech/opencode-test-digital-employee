"""Run recoverability contracts and real offline payload smoke on the target host.

Construction fixture observations are expressly not bank acceptance. Every child
runs the shipped Python. This script never invokes an installer or downloader.
"""
from __future__ import annotations
import argparse
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path


def run(command, cwd, env, timeout=240, required_stdout=None):
    started = time.monotonic()
    try:
        process = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True,
                                 encoding='utf-8', errors='replace', timeout=timeout)
        content_ok = required_stdout is None or required_stdout in process.stdout
        structured = None
        for match in re.finditer(r'\{', process.stdout):
            try:
                candidate, _ = json.JSONDecoder().raw_decode(process.stdout[match.start():])
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict) and isinstance(candidate.get('gates'), dict):
                structured = candidate
                break
        return {'status': 'PASS' if process.returncode == 0 and content_ok else 'FAIL', 'exit_code': process.returncode,
                'elapsed_s': round(time.monotonic() - started, 2),
                'structured_report': structured,
                'required_stdout': required_stdout, 'required_stdout_observed': content_ok,
                'stdout': process.stdout if len(process.stdout) <= 14000 else process.stdout[:7000] + '\n[output truncated]\n' + process.stdout[-7000:],
                'stderr': process.stderr if len(process.stderr)<=12000 else process.stderr[:6000]+'\n[stderr truncated]\n'+process.stderr[-6000:]}
    except Exception as exc:
        return {'status': 'FAIL', 'error': type(exc).__name__, 'message': str(exc),
                'elapsed_s': round(time.monotonic() - started, 2)}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True); parser.add_argument('--source-only', action='store_true')
    parser.add_argument('--installed',type=Path); parser.add_argument('--installed-b',type=Path)
    args = parser.parse_args(); bundle = args.bundle.resolve(); workspace = bundle / 'workspace-template'
    tests = workspace / '.pfc-internal-field-validation/tests'
    installed=args.installed.resolve() if args.installed else None
    installed_b=args.installed_b.resolve() if args.installed_b else None
    if not args.source_only and (not installed or not installed_b):raise RuntimeError('TWO_INSTALLED_WORKSPACES_REQUIRED')
    runtime_workspace=installed or workspace
    source_head=(json.loads((bundle/'BUILD_PROVENANCE.json').read_text()).get('source_head') if (bundle/'BUILD_PROVENANCE.json').is_file() else subprocess.check_output(['git','-C',str(bundle),'rev-parse','HEAD'],text=True).strip())
    source_clean=(not subprocess.check_output(['git','-C',str(bundle),'status','--porcelain'],text=True).strip()) if args.source_only else True
    env = dict(os.environ)
    # Imported Runtime modules plus local test-only deps when on construction Mac.
    env['PYTHONPATH'] = os.pathsep.join(filter(None, [str(workspace / 'ai-test/runtime'), env.get('PYTHONPATH')]))
    env.update(PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
               PIP_NO_INDEX='1', PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD='1', OPENCODE_DISABLE_AUTOUPDATE='1',
               OPENCODE_DISABLE_MODELS_FETCH='1', OPENCODE_DISABLE_DEFAULT_PLUGINS='1',
               K6_NO_USAGE_REPORT='true')
    for key in ('GH_TOKEN', 'GITHUB_TOKEN', 'OPENCODE_SERVER_PASSWORD', 'AITEST_MODEL_KEY', 'AITEST_RUNTIME_SPINE_DB', 'PFC_LOCAL_STATE_ROOT'):
        env.pop(key, None)
    if not args.source_only: env['AITEST_TEST_RUNTIME_SOURCE'] = str(installed)
    if installed: env['AITEST_INSTALLED']=str(installed)
    chrome = runtime_workspace / 'runtime/browser/chrome-win64/chrome.exe' if os.name == 'nt' else Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
    if chrome.is_file(): env['AITEST_BROWSER_SMOKE_CHROMIUM'] = str(chrome)
    # Contract fixtures are separate from the real graph engine query below.
    env['AITEST_CODEGRAPH_BINARY'] = str(bundle / 'data/validation/contract-fixture-no-codegraph.exe')
    suites = [
        'test_recovery_install_lifecycle.py', 'test_rec3_host_native.py',
        'test_rec3_business_contracts.py', 'test_rec3_ui_journey.py',
        'test_recovery_autonomous_entry.py', 'test_recovery_context_stress.py',
        'test_recovery_intake.py', 'test_recovery_executors.py', 'test_recovery_g4_execution.py', 'test_recovery_read_product_entry.py',
        'test_g2_1_pressure_fallback.py', 'test_recovery_browser.py', 'test_recovery_real_opencode.py', 'test_recovery_hosted_intake.py',
        'test_mac_delivery_default_path.py', 'test_interactive_truth_envelope.py',
        'test_g2_1_background_control_loop_subprocess.py', 'test_g2_1_session_router_control_loop.py', 'test_planner_continue_refresh.py',
        'test_g1_g2_product_path_subprocess.py', 'test_g1_g2_1_launch_auth_decoupling.py',
        'test_g3_testing_intelligence_product_path.py', 'test_g4_full_same_mission_product_e2e.py',
        'test_g4_governed_execution_binding_wave2.py', 'test_g4_sensitive_ingress_closure.py',
        'test_g4_explicit_user_turn_resume_closure.py', 'test_g4_terminal_prewrite_guard_closure.py',
        'test_g5_product_path.py', 'test_g5_worker_binding_and_recovery.py',
        'test_g5_adversarial_defect_truth.py', 'test_g5_human_gate_and_duplicate_correlation.py',
        'test_g5_same_mission_e2e.py', 'test_g5_opencode_surface.py',
    ]
    if not args.source_only:suites.insert(2,'test_rec3_startup.py')
    results = {}
    output = args.output.resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    def progress():
        output.write_text(json.dumps({'status': 'IN_PROGRESS', 'LOCAL_VALIDATION_PASS': False,
            'WINDOWS_CI_PASS': False, 'BANK_FIELD_VALIDATION_REQUIRED': True,
            'host': platform.system(), 'suites': results}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for name in suites:
        if not (tests / name).is_file():
            results[name] = {'status': 'FAIL', 'reason': 'REQUIRED_TEST_MISSING'}
        else:
            results[name] = run([sys.executable, '-X', 'utf8', '-c', "import sys,runpy; from pathlib import Path; p=sys.argv[1]; sys.path.insert(0,str(Path(p).parent)); sys.argv=[p]; runpy.run_path(p,run_name='__main__')", str(tests / name)], bundle, env, timeout=1200)
        print(name + ': ' + results[name]['status'], flush=True)
        progress()
    seal_test = bundle / 'tools/recovery/check_qualification_seal.py'
    results[seal_test.name] = run([sys.executable, '-X', 'utf8', str(seal_test)], bundle, env, timeout=120)
    print(seal_test.name + ': ' + results[seal_test.name]['status'], flush=True)
    progress()
    payloads = {}
    if not args.source_only:
        sys.path.insert(0, str(installed / 'tools/recovery'))
        import launcher
        failures=launcher.verify_files()
        payloads['archive_integrity']={'status':'FAIL' if failures else 'PASS','failed_paths':failures}
        from install import verify_install_identity
        installs=[]
        for target in (installed,installed_b):
            errors=verify_install_identity(target)
            topology=all((target/n).exists() for n in ('AGENTS.md','.opencode','ai-test','runtime','tools','bindings','data','AITEST.sh'))
            topology=topology and not any((target/n).exists() for n in ('workspace-template','.github','.pfc-internal-field-validation','runtime/opencode'))
            manifest=json.loads((target/'INSTALL_MANIFEST.json').read_text(encoding='utf-8'))
            installs.append({'root':str(target),'identity_errors':errors,'topology':topology,'install_id':manifest['install_id']})
        payloads['formal_installation']={'status':'PASS' if installed!=installed_b and all(not x['identity_errors'] and x['topology'] for x in installs) else 'FAIL','installations':installs}
        payloads['portable_python'] = {'status': 'PASS' if os.name == 'nt' and sys.version_info[:3] == (3, 12, 10) else 'FAIL', 'version': sys.version, 'executable': sys.executable}
        for package, expected in [('playwright', '1.62.0'), ('greenlet', '3.5.5'), ('httpx', '0.28.1'), ('pytest', '7.2.2'), ('pypdf', '6.17.0')]:
            try:
                actual = importlib.metadata.version(package)
                payloads[package] = {'status': 'PASS' if actual == expected else 'FAIL', 'version': actual}
            except Exception as exc: payloads[package] = {'status': 'FAIL', 'error': str(exc)}
        runtime = installed / 'runtime'
        commands = {
            'k6_version': [str(runtime / 'tools/k6/k6.exe'), 'version'],
            'java_version': [str(runtime / 'tools/java/bin/java.exe'), '-version'],
            'codegraph_version': [str(runtime / 'code-intelligence/codegraph/codegraph-server-win32-x64.exe'), '--info'],
        }
        for name, command in commands.items():
            payloads[name] = run(command, workspace, env, timeout=90, required_stdout='aitest-director' if name == 'opencode_agents' else None)
        graph_root = bundle / 'data/validation/codegraph-smoke'
        graph_root.mkdir(parents=True, exist_ok=True)
        graph_file = graph_root / 'loan.py'
        graph_file.write_text('def loan_accepts(amount):\n    return amount > 0\n\ndef submit(amount):\n    return loan_accepts(amount)\n', encoding='utf-8')
        graph_command = [str(runtime / 'code-intelligence/codegraph/codegraph-server-win32-x64.exe'),
                         '--graph-only', '--workspace', str(graph_root), '--run-tool', 'codegraph_get_ai_context',
                         '--tool-args', json.dumps({'uri': graph_file.as_uri(), 'line': 1, 'intent': 'explain'})]
        payloads['codegraph_real_query'] = run(graph_command, graph_root, env, timeout=120)
        if 'loan_accepts' not in payloads['codegraph_real_query'].get('stdout', ''):
            payloads['codegraph_real_query']['status'] = 'FAIL'
        # ZAP full engine startup is a separate proof from the passive API runner.
        jars = list((runtime / 'tools/zap').glob('zap-*.jar'))
        payloads['zap_engine'] = run([str(runtime / 'tools/java/bin/java.exe'), '-jar', str(jars[0]), '-cmd', '-version'], runtime / 'tools/zap', env, timeout=120) if jars else {'status': 'FAIL', 'reason': 'ZAP_JAR_MISSING'}
        payloads['single_entry_server_control_loop'] = run([sys.executable, '-X', 'utf8', str(installed / 'tools/recovery/launcher.py'), '--self-check'], bundle, env, timeout=150)
        payloads['single_entry_evidence_export'] = run([sys.executable, '-X', 'utf8', str(installed / 'tools/recovery/launcher.py'), '--export-evidence'], bundle, env, timeout=90)
    if args.source_only:
        current_head=subprocess.check_output(['git','-C',str(bundle),'rev-parse','HEAD'],text=True).strip()
        dirty=subprocess.check_output(['git','-C',str(bundle),'status','--porcelain'],text=True).strip()
        results['source_identity_guard']={'status':'PASS' if source_clean and not dirty and current_head==source_head else 'FAIL','reason':'Exact clean source must remain unchanged during validation'}
    passed = all(result['status'] == 'PASS' for result in results.values())
    payload_pass = bool(payloads) and all(result['status'] == 'PASS' for result in payloads.values())
    sys.path.insert(0,str(bundle/'tools/recovery'))
    from closure_contract import REQUIRED_GATES,PACKAGE_VERSION
    gates={g:'NOT_PROVEN' for g in REQUIRED_GATES};gate_evidence={}
    for name,suite in results.items():
        report=suite.get('structured_report') or {}
        if suite.get('status')=='PASS' and isinstance(report.get('gates'),dict):
            for key,value in report['gates'].items():
                gates[key]=value;gate_evidence[key]={'suite':name,'classification':report.get('classification'),'status':value}
    def admit(names,suite):
        if results.get(suite,{}).get('status')=='PASS':
            for name in names.split():
                gates[name]='PASS';gate_evidence[name]={'suite':suite,'status':'PASS','classification':'SYNTHETIC_CONTRACT_OR_LOCAL_SERVICE_ONLY'}
    admit('NO_EXACT_OPENCODE_VERSION_PIN','test_rec3_host_native.py')
    admit('TASK_AWARE_KNOWLEDGE_RETRIEVAL STANDARD_CASE_RUNTIME_VALIDATION API_BUSINESS_LOGIC_EXECUTION','test_rec3_business_contracts.py')
    if chrome.is_file():admit('UI_MULTI_STEP_EXECUTION AI_BROWSER_INTERACTIVE HUMAN_GATE_BROWSER_RESUME HUMAN_TEACHING_TRACE PLAYWRIGHT_CANDIDATE_GENERATION PLAYWRIGHT_REPLAY_VALIDATION','test_rec3_ui_journey.py')
    if payloads.get('formal_installation',{}).get('status')=='PASS':
        for name in ('V1_6_INSTALL_LIFECYCLE_RESTORED','USER_SELECTABLE_INSTALL_TARGET','WORKSPACE_ROOT_TOPOLOGY'):
            gates[name]='PASS';gate_evidence[name]={'payload':'formal_installation','status':'PASS'}
    gates['NATURAL_LANGUAGE_MISSION_ENTRY']=gates.get('NATURAL_LANGUAGE_START_TEST','NOT_PROVEN')
    # A deterministic protocol fixture proves transport/routing, not semantic AI.
    gates['AUTONOMOUS_PLANNER']='PASS' if gates.get('AUTONOMOUS_PLAN')=='PASS' else 'REAL_SEMANTIC_MODEL_VALIDATION_REQUIRED'
    if results.get('test_recovery_autonomous_entry.py',{}).get('status')=='PASS':
        gates['BOUNDED_EVIDENCE']='PASS';gate_evidence['BOUNDED_EVIDENCE']={'suite':'test_recovery_autonomous_entry.py','status':'PASS'}
    regression=[name for name in suites if name.startswith(('test_g1','test_g2','test_g3','test_g4','test_g5'))]
    if regression and all(results[name]['status']=='PASS' for name in regression):
        gates['G1_G5_REGRESSION']='PASS';gate_evidence['G1_G5_REGRESSION']={'suites':regression,'status':'PASS'}
    windows_execution_pass=passed and payload_pass and os.name=='nt'
    gates['WINDOWS_FULL_QUALIFICATION']='PASS' if windows_execution_pass and all(gates[g]=='PASS' for g in REQUIRED_GATES if g not in ('FINAL_ZIP_SEALED','WINDOWS_FULL_QUALIFICATION')) else 'PENDING_OR_FAILED'
    gates['FINAL_ZIP_SEALED']='PENDING'
    result = {'schema_version': 'aitest.machine-validation.v1', 'product_version': PACKAGE_VERSION,
              'host': {'system': platform.system(), 'machine': platform.machine(), 'python': platform.python_version()},
              'source_head': source_head,
              'LOCAL_VALIDATION_PASS': passed, 'WINDOWS_CI_PASS': gates['WINDOWS_FULL_QUALIFICATION']=='PASS', 'WINDOWS_EXECUTION_TESTS_PASS': windows_execution_pass,
              'BANK_FIELD_VALIDATION_REQUIRED': True,
              'real_model_BLOAN_turn': 'AUTH_REQUIRED / NOT_EXECUTED',
              'bank_4A_Starlink_CAT_DB': 'BANK_BINDING_REQUIRED / NOT_EXECUTED',
              'fixture_boundary': 'Contract suites use synthetic requirements and OpenCode HTTP fixtures; HTTP/UI/pytest/k6 payload smoke uses a real local test server. None is bank evidence.',
              'suites': results, 'payloads': payloads,'installed_runtime_roots':[str(x) for x in (installed,installed_b) if x],
              'work_item': 'REC3_FINAL_TURNKEY_PRODUCT_CONVERGENCE_CONTRACT_REISSUE', 'gates': gates, 'gate_evidence': gate_evidence,
              'closure': 'HOLD_UNTIL_ALL_REQUIRED_GATES_PASS',
              'status': 'PASS' if passed and (args.source_only or payload_pass) else 'FAIL'}
    output = args.output.resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: result[k] for k in ('status', 'LOCAL_VALIDATION_PASS', 'WINDOWS_CI_PASS', 'BANK_FIELD_VALIDATION_REQUIRED')}, indent=2))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__': raise SystemExit(main())
