"""V1.13.0 one-entry offline Windows package launcher."""
from __future__ import annotations
import argparse
import base64
from contextlib import closing
from datetime import datetime, timedelta, timezone
import getpass
import hashlib
import importlib.metadata
import json
import os
import secrets
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request
import uuid
import zipfile
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[2]
WORKSPACE = BUNDLE
DATA = BUNDLE / 'data'
VERSION = '1.13.0'
sys.path.insert(0, str(Path(__file__).resolve().parent))
import host_opencode


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()


def read(path, default=None):
    return json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).is_file() else default


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as output:
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.write('\n'); output.flush(); os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare():
    # Preserve host provider/model/auth and XDG variables byte-for-byte.
    for name in ('state', 'logs', 'evidence', 'imports', 'exports'):
        (DATA / name).mkdir(parents=True, exist_ok=True)
    (WORKSPACE / 'bindings').mkdir(exist_ok=True)
    sys.path.insert(0, str(WORKSPACE / 'ai-test/runtime'))
    os.environ.update(AITEST_WORKSPACE_ROOT=str(WORKSPACE),
        AITEST_RUNTIME_SPINE_DB=str(DATA / 'state/runtime-spine.db'), PFC_LOCAL_STATE_ROOT=str(DATA),
        PYTHONPATH=str(WORKSPACE / 'ai-test/runtime'), PYTHONNOUSERSITE='1', PYTHONUTF8='1',
        PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1',
        AITEST_G4_PROVIDER_FACTORY='aitest_runtime.recovery_executors:provider_bundle',
        AITEST_CONTROL_LOOP_HEARTBEAT_PATH=str(DATA / 'state/control-loop-heartbeat.json'),
        OPENCODE_DISABLE_AUTOUPDATE='1', OPENCODE_DISABLE_MODELS_FETCH='1',
        OPENCODE_DISABLE_LSP_DOWNLOAD='1', PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD='1',
        PIP_NO_INDEX='1', NPM_CONFIG_OFFLINE='true', npm_config_offline='true', CODEGRAPH_SKIP_MODEL_FETCH='1')
    # Never insert bundled OpenCode, host config caches, or a second auth home.
    portable_bins = [WORKSPACE / 'runtime' / item for item in
        ('python', 'tools/rg', 'tools/k6', 'tools/java/bin', 'tools/ffmpeg', 'tools/adb')]
    existing = os.environ.get('PATH', '').split(os.pathsep)
    os.environ['PATH'] = os.pathsep.join([str(p) for p in portable_bins if p.is_dir() and str(p) not in existing] + existing)
    java = WORKSPACE / 'runtime/tools/java'
    if java.is_dir(): os.environ['JAVA_HOME'] = str(java)
    from aitest_runtime.canonical_runtime import create_canonical_runtime
    create_canonical_runtime(WORKSPACE)
    return dict(os.environ)


def provision_opencode_config():
    raise RuntimeError('HOST_PROVIDER_AUTH_COPY_FORBIDDEN')


def verify_files():
    from install import InstallError, verify_package
    try:
        verify_package(BUNDLE, installed=True)
        return []
    except (InstallError, OSError, ValueError) as exc:
        return [str(exc)]


def verify_daily_install():
    from install import verify_install_identity
    failures = verify_install_identity(BUNDLE)
    if failures: raise RuntimeError('INSTALL_REQUIRED: 请先运行 ./INSTALL.sh；' + '; '.join(failures))


def doctor(full=False):
    failures = verify_files() if full else []
    from aitest_runtime.canonical_runtime import runtime_status
    runtime = runtime_status(WORKSPACE)
    def module(name):
        try: __import__(name); return 'READY'
        except ImportError: return 'FAIL'
    def exists(relative): return 'READY' if (WORKSPACE / relative).is_file() else 'FAIL'
    execution = read(WORKSPACE / 'bindings/execution.json', {})
    bound = execution.get('approved') is True and bool(execution.get('approval_ref'))
    def target(capability): return 'READY' if bound else 'BANK_BINDING_REQUIRED'
    try:
        host_opencode.resolve(WORKSPACE)
        oc_status = 'READY'
    except RuntimeError:
        oc_status = 'FAIL'
    binding_status = provider_configuration()[1]
    matrix = {
        'Runtime': 'READY' if runtime.get('truth_source') == 'R1_EVENT_STREAM' else 'FAIL',
        'OpenCode': oc_status,
        'Model': 'AUTH_REQUIRED',
        'HostProvider': 'READY' if oc_status=='READY' else 'FAIL',
        'ControlLoop': 'READY',
        'Browser': exists('runtime/browser/chrome-win64/chrome.exe'),
        'CodeGraph': exists('runtime/code-intelligence/codegraph/codegraph-server-win32-x64.exe'),
        'API': 'FAIL' if module('httpx') == 'FAIL' else target('API'),
        'UI': 'FAIL' if module('playwright.sync_api') == 'FAIL' else target('UI'),
        'Unit': 'FAIL' if module('pytest') == 'FAIL' else ('READY' if execution.get('native_runners') and bound else 'BANK_BINDING_REQUIRED'),
        'Security': 'FAIL' if module('httpx') == 'FAIL' else target('SECURITY'),
        'ZAP': 'READY' if any((WORKSPACE / 'runtime/tools/zap').glob('zap*.jar')) and (WORKSPACE / 'runtime/tools/java/bin/java.exe').is_file() else 'FAIL',
        'Performance': 'FAIL' if exists('runtime/tools/k6/k6.exe') == 'FAIL' else target('PERFORMANCE'),
        'Starlink': 'BANK_BINDING_REQUIRED',
        'CAT': 'BANK_BINDING_REQUIRED', 'DB': 'BANK_BINDING_REQUIRED',
        'Integrity': 'FAIL' if failures else ('READY' if full else 'NOT_CHECKED'),
    }
    heartbeat = read(DATA / 'state/control-loop-heartbeat.json', {})
    from aitest_runtime.recovery_intake import RecoveryIntakeService
    from aitest_runtime.canonical_runtime import create_canonical_runtime
    for mission in runtime.get('missions', []):
        context = RecoveryIntakeService(create_canonical_runtime(WORKSPACE)).work_context(mission['mission_id'])
        if context.get('starlink_export_status') == 'READY': matrix['Starlink'] = 'READY'
    return {'version': VERSION, 'status': 'FAIL' if failures or 'FAIL' in matrix.values() else 'READY_WITH_BANK_BINDINGS',
            'truth_source': 'R1_EVENT_STREAM', 'architecture_baseline': 'v7/FROZEN/UNCHANGED',
            'g1_g5_engineering': 'CLOSED/FROZEN', 'g6': 'HOLD', 'matrix': matrix,
            'control_loop_last_heartbeat': heartbeat.get('status', 'STARTS_WITH_CONVERSATION'),
            'integrity_failures': failures, 'bank_field_validation': 'BANK_FIELD_VALIDATION_REQUIRED',
            'security_scope': 'API_PASSIVE_BASELINE; ZAP payload separate, active scan requires governed binding',
            'provider_binding': binding_status}


def display_doctor(full=True):
    result = doctor(full)
    print('\nAITest V1.13.0 · 能力自检')
    for key, value in result['matrix'].items(): print(f'  {key:15} {value}')
    print('G1-G5 CLOSED/FROZEN；G6 HOLD。行内结果需要现场验证。')
    write(DATA / 'logs/doctor.json', result)
    return result


def model_settings():
    print('本工作目录直接使用 PATH 中的宿主 OpenCode，以及它现有的 provider/model/auth。')
    print('模型或登录需调整时，请使用行内 OpenCode 自己的设置入口；本产品不复制配置或密钥。')


def model_configuration(*_args, **_kwargs):
    raise RuntimeError('ISOLATED_PROVIDER_CONFIGURATION_FORBIDDEN')


def provider_configuration():
    return {}, {'mode': 'HOST_NATIVE_OPENCODE', 'auth': 'HOST_AUTH_PROBE_REQUIRED',
                'qualification': 'HOST_PROVIDER_AUTH_PRESERVED', 'bank_gate': 'BANK_FIELD_VALIDATION_REQUIRED'}


def windows_host():
    return os.name == 'nt'


def start_conversation(check_only=False, attach_runner=None):
    if not windows_host(): raise RuntimeError('WINDOWS_HOST_REQUIRED')
    report = display_doctor(True)
    if report['integrity_failures']: raise RuntimeError('INSTALLED_RUNTIME_INTEGRITY_FAILED')
    env = prepare()
    executable = host_opencode.resolve(WORKSPACE, env)
    endpoint = env.get('AITEST_OPENCODE_ENDPOINT')
    owned = not bool(endpoint)
    if owned:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        endpoint = f'http://127.0.0.1:{port}'
        env.setdefault('OPENCODE_SERVER_USERNAME', 'opencode')
        env.setdefault('OPENCODE_SERVER_PASSWORD', secrets.token_urlsafe(32))
    env['AITEST_OPENCODE_ENDPOINT'] = endpoint
    client = host_opencode.CapabilityClient(endpoint, WORKSPACE, env)
    server = loop = None
    def stop(process):
        if process is None or process.poll() is not None: return
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        else: process.terminate()
        try: process.wait(timeout=10)
        except subprocess.TimeoutExpired: process.kill(); process.wait()
    try:
        if owned:
            # Host owns its own logs/config/auth. Do not capture provider output
            # that could contain private credentials into package evidence.
            server = subprocess.Popen(host_opencode.command(executable, 'serve', '--hostname',
                '127.0.0.1', '--port', str(port), env=env), cwd=WORKSPACE, env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.monotonic() + 45
            while True:
                if server.poll() is not None: raise RuntimeError('HOST_OPENCODE_PROCESS_START_FAILED')
                try:
                    if client.request('GET', '/global/health', timeout=1).get('healthy'): break
                except Exception: pass
                if time.monotonic() >= deadline: raise RuntimeError('HOST_OPENCODE_PROCESS_START_TIMEOUT')
                time.sleep(.25)
        probe = client.probe()
        with (DATA / 'logs/control-loop.log').open('a', encoding='utf-8') as log:
            loop = subprocess.Popen([sys.executable, '-X', 'utf8', '-m', 'aitest_runtime.control_loop',
                '--workspace-root', str(WORKSPACE), '--interval', '3'], cwd=WORKSPACE, env=env,
                stdout=log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 20
        while True:
            if loop.poll() is not None: raise RuntimeError('CONTROL_LOOP_START_FAILED')
            heartbeat = read(DATA / 'state/control-loop-heartbeat.json', {})
            if (heartbeat.get('pid') == loop.pid and heartbeat.get('status') == 'PASS'
                    and heartbeat.get('endpoint') == endpoint and heartbeat.get('workspace_root') == str(WORKSPACE)):
                break
            if time.monotonic() >= deadline: raise RuntimeError('CONTROL_LOOP_BINDING_NOT_VERIFIED')
            time.sleep(.25)
        probe['gates']['CONTROL_LOOP_BINDING'] = 'PASS'
        previous = read(DATA / 'state/director-entry-session.json', {})
        previous_id = previous.get('session_id') if isinstance(previous, dict) else None
        session = None
        if isinstance(previous_id, str) and previous_id.startswith('ses_') and len(previous_id) < 160 and previous_id.replace('_','').replace('-','').isalnum():
            try: session = client.request('GET', '/session/' + previous_id)
            except Exception: pass
        if not session:
            session = client.request('POST', '/session', {'title': 'AITest Director'})
        if not isinstance(session, dict) or not session.get('id'):
            raise host_opencode.CompatibilityRequired('DIRECTOR_SESSION')
        write(DATA / 'state/director-entry-session.json', {'session_id': session['id'], 'operational_only': True})
        readiness = {**probe, 'server': 'PASS', 'control_loop_process': 'PASS',
                     'director_session_id': session['id'], 'host_executable': str(executable),
                     'endpoint': endpoint, 'workspace_root': str(WORKSPACE), 'operational_only': True}
        write(DATA / 'state/startup-readiness.json', readiness)
        if check_only: return readiness
        print('宿主 OpenCode 与 AITest 工作目录已连接；Control Loop 已接管 Session 健康监控。')
        print('输入：测试 BLOAN-PF1.1.0。4A 在浏览器中完成，再回到对话输入“完成”。')
        return (attach_runner or subprocess.call)(host_opencode.command(executable, 'attach', endpoint,
            '--dir', str(WORKSPACE), '--session', session['id'], env=env), cwd=WORKSPACE, env=env)
    finally:
        stop(loop)
        if owned: stop(server)


def evidence_export():
    target = DATA / 'exports' / ('AITest-Evidence-' + time.strftime('%Y%m%d-%H%M%S') + '.zip')
    snapshot = DATA / 'exports/runtime-spine.snapshot.db'
    with closing(sqlite3.connect(DATA / 'state/runtime-spine.db')) as source, closing(sqlite3.connect(snapshot)) as dest:
        source.backup(dest)
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.write(snapshot, 'state/runtime-spine.db')
        for path in (DATA / 'evidence').rglob('*'):
            if path.is_file(): archive.write(path, str(path.relative_to(DATA)))
        for name in ('MACHINE_VALIDATION_RESULT.json', 'BUILD_PROVENANCE.json', 'CAPABILITY_PARITY_MATRIX.md'):
            if (BUNDLE / name).is_file(): archive.write(BUNDLE / name, name)
    snapshot.unlink()
    print('证据已导出：' + str(target))
    return str(target)


def import_asset(release=False):
    from aitest_runtime.recovery_intake import RecoveryIntakeService
    from aitest_runtime.canonical_runtime import create_canonical_runtime, runtime_status
    missions = runtime_status(WORKSPACE).get('missions', [])
    if not missions: print('请先进入对话创建测试 Mission，再导入附件。'); return
    for i, item in enumerate(missions): print(i + 1, item['mission_id'])
    index = int(input('选择 Mission 编号：') or '1') - 1
    mission = missions[index]['mission_id']
    path = Path(input('粘贴本地文件路径：').strip().strip('"')).expanduser().resolve()
    if not path.is_file(): raise ValueError('文件不存在')
    destination = DATA / 'imports' / (sha(path) + path.suffix.lower())
    import shutil
    shutil.copyfile(path, destination)
    service = RecoveryIntakeService(create_canonical_runtime(WORKSPACE))
    if release:
        print('仅导入已获批准的 Current Release / Starlink 导出文件。')
        project = input('项目标识：').strip(); version = input('发布版本：').strip()
        approval = input('批准记录编号：').strip()
        if not approval: raise ValueError('批准记录编号必填')
        now = datetime.now(timezone.utc)
        days = int(input('批准有效天数 [1]：').strip() or '1')
        if not 1 <= days <= 90: raise ValueError('有效期应为 1–90 天')
        contract = {'adapter': 'APPROVED_EXPORT', 'source_system': 'STARLINK',
                    'binding_id': 'export-' + uuid.uuid4().hex, 'revision': '1', 'approval_ref': approval,
                    'project_id': project, 'release_id': version, 'expected_sha256': sha(destination),
                    'approved_by': getpass.getuser(), 'approved_at': now.isoformat(),
                    'valid_until': (now + timedelta(days=days)).isoformat()}
        write(WORKSPACE / 'bindings/starlink.json', contract)
        result = service.import_current_release(mission, destination, contract)
    else:
        source_id = input('附件业务编号（Requirement/SST）：').strip() or path.stem
        revision = input('附件修订号：').strip() or '1'
        kind = input('类型 REQUIREMENT / SST [REQUIREMENT]：').strip().upper() or 'REQUIREMENT'
        result = service.import_document(mission, destination, source_id, source_kind=kind, revision=revision)
    print('导入结果：' + result.get('status', 'UNKNOWN') + '。文件版本和来源已写入 Runtime，返回对话继续测试即可。')


def execution_settings():
    print('填写已批准的测试环境地址，不要填写生产环境或密钥。')
    origins = [value.strip().rstrip('/') for value in input('允许测试的地址（含协议和端口，多个用逗号分隔）：').split(',') if value.strip()]
    from urllib.parse import urlsplit
    if not origins or any(urlsplit(x).scheme not in ('http', 'https') or urlsplit(x).username or urlsplit(x).path for x in origins):
        raise ValueError('请填写完整源地址，例如 https://test.example:8443')
    approval = input('批准记录编号：').strip()
    if not approval: raise ValueError('批准记录编号必填')
    methods = [x.strip().upper() for x in (input('批准 HTTP 方法 [GET,HEAD]：').strip() or 'GET,HEAD').split(',')]
    config = {'approved': True, 'approval_ref': approval, 'allowed_origins': origins, 'allowed_methods': methods, 'native_runners': {}}
    project = input('Python 项目目录（需要单元测试时填写，可留空）：').strip().strip('"')
    if project:
        folder = Path(project).resolve()
        if not folder.is_dir(): raise ValueError('项目目录不存在')
        config['native_runners']['project-pytest'] = {'cwd': str(folder),
            'argv': [str(Path(sys.executable).resolve()), '-m', 'pytest', '-q', '-p', 'no:cacheprovider'],
            'executable_sha256': sha(sys.executable), 'timeout_s': 300}
    write(WORKSPACE / 'bindings/execution.json', config)
    print('测试环境绑定已保存。CAT/DB 仍需由行内适配器与授权绑定；缺失时会明确阻塞。')



def browser_teaching():
    from urllib.parse import urlsplit
    from aitest_runtime.canonical_runtime import runtime_status
    missions = runtime_status(WORKSPACE).get('missions', [])
    if not missions:
        print('请先进入对话创建测试 Mission。'); return
    for i, item in enumerate(missions): print(i + 1, item['mission_id'])
    mission = missions[int(input('选择教学对应 Mission [1]：') or '1') - 1]['mission_id']
    config = read(WORKSPACE / 'bindings/browser.json', {})
    if not config:
        print('首次绑定浏览器：请填写已批准的测试页面。4A 由您在浏览器内操作。')
        url = input('开始页面地址：').strip()
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('请填写不含凭据的 HTTP(S) 页面地址')
        origin = f'{parsed.scheme}://{parsed.netloc}'
        origins = [origin] + [x.strip().rstrip('/') for x in input('其他已批准的页面源地址（多个用逗号分隔，可留空）：').split(',') if x.strip()]
        if any(urlsplit(x).scheme not in ('http','https') or not urlsplit(x).hostname or urlsplit(x).username or urlsplit(x).path for x in origins):
            raise ValueError('额外地址需仅含协议、主机和端口')
        approval = input('批准记录编号：').strip()
        if not approval: raise ValueError('批准记录编号必填')
        print('由行内页面负责人提供以下页面标记；留空可先进行教学，自动恢复将等待绑定。')
        checks = {key: input(label).strip() for key, label in [('authenticated_selector','登录成功标记：'), ('page_selector','当前页面标记：'), ('business_selector','业务就绪标记：')]}
        paths = [x.strip() for x in input('允许采集已脱敏 JSON 响应的路径（可留空，多个用逗号分隔）：').split(',') if x.strip()]
        if any(not x.startswith('/') or '?' in x or '#' in x for x in paths): raise ValueError('响应路径不可含查询参数')
        config = {'approved': True, 'approval_ref': approval, 'allowed_origins': origins, 'start_url': url,
                  'cdp_endpoint': 'http://127.0.0.1:9222', 'resume_checks': checks, 'response_body_paths': paths}
        write(WORKSPACE / 'bindings/browser.json', config)
    print('浏览器由您操作。当前任务触发人工接管后会自动观察；操作完成后回到对话输入“完成”，系统验证并续跑。')
    return subprocess.call([sys.executable, '-m', 'aitest_runtime.recovery_browser', '--workspace-root', str(WORKSPACE), '--mission-id', mission, '--gate-only'], cwd=WORKSPACE, env=prepare())


def select_mission():
    from aitest_runtime.canonical_runtime import runtime_status
    missions=runtime_status(WORKSPACE).get('missions',[])
    if not missions:raise ValueError('请先创建测试任务。')
    for i,item in enumerate(missions):print(i+1,item['mission_id'])
    return missions[int(input('选择任务 [1]：') or '1')-1]['mission_id']


def review_knowledge():
    from aitest_runtime.canonical_runtime import create_canonical_runtime
    from aitest_runtime.recovery_knowledge import review
    mission=select_mission();runtime=create_canonical_runtime(WORKSPACE)
    state=runtime.replay_composed(mission).extension_state('r3_e1_durable_knowledge_substrate')
    versions=[v for v in state.versions if v.status in {'CANDIDATE','SOURCE_VERIFIED','RUNTIME_VERIFIED'}]
    if not versions:print('当前任务没有待审核知识。');return
    for i,v in enumerate(versions):print(i+1,v.payload.get('kind'),v.payload.get('summary'),v.status)
    chosen=versions[int(input('选择审核条目：'))-1]
    from aitest_runtime.g4.contracts import EXTENSION_ID
    evidence=[f for f in runtime.replay_composed(mission).extension_state(EXTENSION_ID).by_kind('EXECUTION_STEP_RESULT') if f.payload.get('oracle_result')=='PASS']
    if not evidence:raise ValueError('尚无通过的执行证据；知识保持候选状态。')
    for i,f in enumerate(evidence):print(i+1,f.payload.get('step_id'),f.payload.get('oracle_reason'))
    proof=evidence[int(input('选择已核对并支持该知识的执行证据：'))-1]
    approval=input('审核批准记录编号：').strip()
    if not approval:raise ValueError('需要批准记录编号。')
    days=int(input('审核有效天数 [1]：') or '1')
    if not 1<=days<=30:raise ValueError('有效天数必须为 1–30。')
    item={'version_id':chosen.version_id,'payload_digest':chosen.payload_digest,'evidence_ref':proof.fact_id,
      'approved':True,'reviewer':getpass.getuser(),'approval_ref':approval,
      'expires_at':(datetime.now(timezone.utc)+timedelta(days=days)).isoformat()}
    path=WORKSPACE/'bindings/knowledge-reviews.json';entries=read(path,[])
    entries=[e for e in entries if e['version_id']!=chosen.version_id]+[item];write(path,entries)
    result=review(runtime,WORKSPACE,mission,chosen.version_id)
    print('知识审核：'+result['lifecycle']+'；仅在相符任务范围和有效期内检索，G6 仍为 HOLD。')


def replay_teaching():
    from aitest_runtime.canonical_runtime import create_canonical_runtime
    from aitest_runtime.g3.service import G3TestingIntelligenceService
    from aitest_runtime.recovery_browser import CDPBrowserProvider
    from aitest_runtime.recovery_teaching import validate_replay
    from playwright.sync_api import sync_playwright
    import re
    mission=select_mission();runtime=create_canonical_runtime(WORKSPACE)
    candidates=[f for f in G3TestingIntelligenceService(runtime).state(mission).by_kind('TEACHING_ASSET') if f.payload.get('mode')=='PLAYWRIGHT_CANDIDATE']
    if not candidates:print('当前任务尚无可回放的教学候选。先在任务触发的人工接管中示教。');return
    for i,f in enumerate(candidates):print(i+1,'步骤数',len(f.payload['actions']),'来源任务',f.payload['execution_lineage']['task_id'])
    chosen=candidates[int(input('选择回放候选：'))-1]
    for i,a in enumerate(chosen.payload['actions']):print(i+1,a['action'],a['locator'],a.get('value',''))
    approval=input('核对上述操作及测试环境后，输入批准记录编号（留空取消）：').strip()
    if not approval:return
    variables={name:input('测试数据 '+name+'（不要填写密码或验证码）：') for name in sorted(set(re.findall(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}',json.dumps(chosen.payload['actions']))))}
    config=read(WORKSPACE/'bindings/browser.json',{})
    config.setdefault('replay_approvals',[]).append({'approved':True,'approval_ref':approval,'candidate_ref':chosen.fact_id,'program_sha256':chosen.payload['program_sha256']})
    write(WORKSPACE/'bindings/browser.json',config)
    provider=CDPBrowserProvider(WORKSPACE,runtime=runtime);ref=provider.context_ref()
    with sync_playwright() as driver:
        browser=driver.chromium.connect_over_cdp(provider.endpoint)
        pages=[p for p in browser.contexts[0].pages if provider.allowed(p.url)]
        for i,page in enumerate(pages):print(i+1,page.title())
        page=pages[int(input('选择已准备好回放的受控页面 [1]：') or '1')-1]
        result=validate_replay(runtime,mission,chosen.fact_id,page=page,variables=variables,
          evidence_root=DATA/'evidence/teaching-replay',approval_ref=approval,context_ref=ref.to_dict())
    print('真实回放结果：'+result['payload']['replay_status']+'。证据已保存；未提升为全局技能。')


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--doctor', action='store_true'); parser.add_argument('--self-check', action='store_true'); parser.add_argument('--export-evidence', action='store_true')
    args = parser.parse_args(); verify_daily_install()
    if verify_files(): raise RuntimeError('INSTALLED_RUNTIME_INTEGRITY_FAILED')
    prepare()
    if args.doctor: return 1 if display_doctor()['status'] == 'FAIL' else 0
    if args.self_check:
        result = start_conversation(check_only=True); print(json.dumps(result)); return 0
    if args.export_evidence: evidence_export(); return 0
    while True:
        print('\nAITest V1.13.0 Recovery · Windows 行内验证\n1 开始/继续测试对话\n2 能力自检\n3 导入需求/SST 附件\n4 导入 Current Release / Starlink 批准导出\n5 宿主 OpenCode 模型说明\n6 导出证据\n7 绑定测试环境\n8 浏览器人工教学 / 4A\n9 审核任务知识\n10 教学候选回放\n0 退出')
        choice = input('请选择 [1]：').strip() or '1'
        try:
            if choice == '0': return 0
            if choice == '1': start_conversation()
            elif choice == '2': display_doctor()
            elif choice == '3': import_asset()
            elif choice == '4': import_asset(True)
            elif choice == '5': model_settings()
            elif choice == '6': evidence_export()
            elif choice == '7': execution_settings()
            elif choice == '8': browser_teaching()
            elif choice == '9': review_knowledge()
            elif choice == '10': replay_teaching()
        except Exception as exc: print('未完成：' + str(exc))


if __name__ == '__main__':
    try: raise SystemExit(main())
    except KeyboardInterrupt: raise SystemExit(130)
