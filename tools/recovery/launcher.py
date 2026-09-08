"""V1.12.0 one-entry offline Windows package launcher."""
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
WORKSPACE = BUNDLE / 'workspace-template'
DATA = BUNDLE / 'data'
OPENCODE = WORKSPACE / 'runtime/opencode/opencode.exe'
VERSION = '1.12.0'
# Capture paths before prepare() isolates XDG; discovery never reads their content.
HOST_CONFIG_ENV = {key: os.environ[key] for key in ('XDG_CONFIG_HOME', 'OPENCODE_CONFIG', 'OPENCODE_CONFIG_DIR') if key in os.environ}
sys.path.insert(0, str(Path(__file__).resolve().parent))
import host_provider


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()


def read(path, default=None):
    return json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).is_file() else default


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def prepare():
    for key in ('OPENCODE_CONFIG', 'OPENCODE_CONFIG_DIR', 'OPENCODE_CONFIG_CONTENT'):
        os.environ.pop(key, None)
    for name in ('state', 'logs', 'evidence', 'imports', 'exports'): (DATA / name).mkdir(parents=True, exist_ok=True)
    (WORKSPACE / 'bindings').mkdir(exist_ok=True)
    sys.path.insert(0, str(WORKSPACE / 'ai-test/runtime'))
    provision_opencode_config()
    os.environ.update(AITEST_WORKSPACE_ROOT=str(WORKSPACE), AITEST_RUNTIME_SPINE_DB=str(DATA / 'state/runtime-spine.db'),
        PFC_LOCAL_STATE_ROOT=str(DATA), PYTHONPATH=str(WORKSPACE / 'ai-test/runtime'), PYTHONNOUSERSITE='1', PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
        PYTHONDONTWRITEBYTECODE='1', AITEST_G4_PROVIDER_FACTORY='aitest_runtime.recovery_executors:provider_bundle',
        AITEST_CONTROL_LOOP_HEARTBEAT_PATH=str(DATA / 'state/control-loop-heartbeat.json'),
        OPENCODE_DISABLE_AUTOUPDATE='1', OPENCODE_DISABLE_MODELS_FETCH='1', OPENCODE_DISABLE_DEFAULT_PLUGINS='1',
        OPENCODE_DISABLE_LSP_DOWNLOAD='1', OPENCODE_DISABLE_SHARE='1', PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD='1',
        PIP_NO_INDEX='1', NPM_CONFIG_OFFLINE='true', npm_config_offline='true', CODEGRAPH_SKIP_MODEL_FETCH='1', NO_PROXY='localhost,127.0.0.1,::1', no_proxy='localhost,127.0.0.1,::1',
        XDG_DATA_HOME=str(DATA / 'opencode-data'), XDG_CONFIG_HOME=str(DATA / 'opencode-config'),
        XDG_CACHE_HOME=str(DATA / 'opencode-cache'), XDG_STATE_HOME=str(DATA / 'opencode-state'),
        OPENCODE_TEST_HOME=str(DATA / 'opencode-home'), BUN_INSTALL_CACHE_DIR=str(DATA / 'bun-cache'))
    portable_bins = [WORKSPACE / 'runtime' / item for item in ('python', 'opencode', 'tools/rg', 'tools/k6', 'tools/java/bin', 'tools/ffmpeg', 'tools/adb')]
    os.environ['PATH'] = os.pathsep.join([str(p) for p in portable_bins if p.is_dir()] + [os.environ.get('PATH', '')])
    java = WORKSPACE / 'runtime/tools/java'
    if java.is_dir(): os.environ['JAVA_HOME'] = str(java)
    from aitest_runtime.canonical_runtime import create_canonical_runtime
    create_canonical_runtime(WORKSPACE)
    return dict(os.environ)


def provision_opencode_config():
    # OpenCode 1.18.3 waits for per-config dependency checks before plugin/tools.
    # Satisfy its offline fast path from the shipped, hash-verified dependency
    # tree; this is local materialization, never pip/npm/Bun installation.
    import shutil
    source = WORKSPACE / '.opencode'
    target = DATA / 'opencode-config/opencode'
    target.mkdir(parents=True, exist_ok=True)
    if not (source / 'node_modules').is_dir(): return
    for name in ('package.json', 'package-lock.json'):
        if (source / name).is_file() and not (target / name).is_file():
            shutil.copy2(source / name, target / name)
    if not (target / 'node_modules').is_dir():
        shutil.copytree(source / 'node_modules', target / 'node_modules')


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
    oc_status = exists('runtime/opencode/opencode.exe')
    if oc_status == 'READY' and os.name == 'nt':
        try:
            value = subprocess.check_output([str(OPENCODE), '--version'], timeout=30, text=True).strip()
            if value != '1.18.3': oc_status = 'FAIL'
        except Exception: oc_status = 'FAIL'
    binding_status = provider_configuration()[1]
    matrix = {
        'Runtime': 'READY' if runtime.get('truth_source') == 'R1_EVENT_STREAM' else 'FAIL',
        'OpenCode': oc_status,
        'Model': binding_status['auth'],
        'HostProvider': binding_status['qualification'],
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
            'host_provider_discovery': host_provider.discover(HOST_CONFIG_ENV),
            'provider_binding': binding_status}


def display_doctor(full=True):
    result = doctor(full)
    print('\nAITest V1.12.0 · 能力自检')
    for key, value in result['matrix'].items(): print(f'  {key:15} {value}')
    print('G1-G5 CLOSED/FROZEN；G6 HOLD。行内结果需要现场验证。')
    write(DATA / 'logs/doctor.json', result)
    return result


def model_settings():
    print('1 REUSE_APPROVED_HOST_PROVIDER · 复用已批准宿主 provider / 本地插件')
    print('2 PACKAGE_LOCAL_PROVIDER_BINDING · 包内模型绑定')
    print('3 AUTH_REQUIRED · 清除绑定，仍可启动 OpenCode')
    choice = input('选择 [1]：').strip() or '1'
    if choice == '3':
        write(DATA / 'provider-binding.json', {'mode': 'AUTH_REQUIRED'})
        write(DATA / 'model.json', {})
        return
    if choice == '1':
        discovery = host_provider.discover(HOST_CONFIG_ENV)
        for item in discovery['candidates']: print('发现配置（尚未读取内容）：' + item['path'])
        default_path = discovery['candidates'][0]['path'] if discovery['candidates'] else ''
        path = input('批准复用的宿主配置完整路径 [' + default_path + ']：').strip().strip('"') or default_path
        print('此选择明确授权读取该配置并执行其中现有本地 provider / 插件。')
        print('仅复用选定模型；不读取宿主 auth.json，不复制密钥，不改宿主文件。')
        print('内联密钥和文件密钥引用会拒绝；已有环境变量引用可直接复用。')
        approval = input('批准记录编号（必填）：').strip()
        review = host_provider.inspect_approved(path, approval)
        for item in review['models']: print('  ' + item)
        model = input('provider/model [' + str(review['preferred_model'] or '') + ']：').strip() or review['preferred_model']
        write(DATA / 'provider-binding.json', host_provider.create_binding(path, model, approval))
        print('PARTIAL_BANK_BINDING：已保存无密钥引用。真实模型/插件认证待行内验证。')
        return
    if choice != '2': raise ValueError('请选择有效绑定模式')
    print('填写已批准的 OpenAI-compatible 服务；地址按原服务填写，不自动添加 /v1。')
    endpoint = input('服务地址：').strip()
    name = input('模型 ID：').strip()
    approval = input('批准记录编号（必填）：').strip()
    model_configuration({'base_url': endpoint, 'model': name})
    if not approval: raise ValueError('批准记录编号必填')
    write(DATA / 'model.json', {'base_url': endpoint, 'model': name, 'approval_ref': approval})
    write(DATA / 'provider-binding.json', {'mode': 'PACKAGE_LOCAL_PROVIDER_BINDING', 'approval_ref': approval})
    print('密钥仅从当前进程的 AITEST_MODEL_KEY 环境变量读取；不回显、不保存。')


def model_configuration(model, check_only=False):
    # Process startup is independent of model/auth readiness, including the normal
    # conversation path. check_only is retained solely for callers' compatibility.
    config = {'autoupdate': False, 'share': 'disabled', 'enabled_providers': ['bank'] if model else []}
    if model:
        from urllib.parse import urlsplit
        endpoint = str(model.get('base_url', ''))
        parsed = urlsplit(endpoint)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or not model.get('model'):
            raise ValueError('CREDENTIAL_FREE_MODEL_ADDRESS_AND_ID_REQUIRED')
        if not host_provider.IDENTIFIER.fullmatch(str(model['model'])):
            raise ValueError('MODEL_ID_INVALID')
        config.update(model='bank/' + model['model'], small_model='bank/' + model['model'],
            provider={'bank': {'npm': '@ai-sdk/openai-compatible',
            'name': 'Bank approved model', 'options': {'baseURL': endpoint, 'apiKey': '{env:AITEST_MODEL_KEY}'},
            'models': {model['model']: {'name': model['model']}}}})
    return config


def provider_configuration():
    base = model_configuration({})
    status = {'mode': 'AUTH_REQUIRED', 'auth': 'AUTH_REQUIRED',
              'qualification': 'PARTIAL_BANK_BINDING', 'bank_gate': 'BANK_PROVIDER_BINDING_REQUIRED'}
    try:
        binding = read(DATA / 'provider-binding.json', {})
        if not isinstance(binding, dict): raise ValueError('BINDING_OBJECT_REQUIRED')
        status['mode'] = binding.get('mode', 'AUTH_REQUIRED')
        if binding.get('mode') == 'REUSE_APPROVED_HOST_PROVIDER':
            base.update(host_provider.resolve(binding))
            status.update(model=binding['model'], auth='AUTH_VERIFICATION_REQUIRED')
        elif binding.get('mode') != 'AUTH_REQUIRED' or not binding:
            model = read(DATA / 'model.json', {})
            if model:
                base = model_configuration(model)
                status.update(mode='PACKAGE_LOCAL_PROVIDER_BINDING', model=base['model'],
                              auth='AUTH_VERIFICATION_REQUIRED' if os.environ.get('AITEST_MODEL_KEY') else 'AUTH_REQUIRED')
    except (host_provider.BindingRequired, ValueError, OSError, TypeError, KeyError, AttributeError):
        # A missing/changed/unsafe binding is a model gate, never a process gate.
        base = model_configuration({})
        status['binding_error'] = 'BANK_PROVIDER_BINDING_REQUIRED_REVIEW_APPROVED_SOURCE'
    return base, status


def windows_host():
    return os.name == 'nt'


def start_conversation(check_only=False, attach_runner=None):
    if not windows_host(): raise RuntimeError('WINDOWS_HOST_REQUIRED')
    report = display_doctor(True)
    if report['integrity_failures'] or report['matrix']['OpenCode'] != 'READY': raise RuntimeError('交付文件校验失败')
    config, binding_status = provider_configuration()
    env = prepare()
    with socket.socket() as sock: sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    endpoint = f'http://127.0.0.1:{port}'
    env.update(AITEST_OPENCODE_ENDPOINT=endpoint, OPENCODE_SERVER_USERNAME='opencode', OPENCODE_SERVER_PASSWORD=secrets.token_urlsafe(32))
    auth = 'Basic ' + base64.b64encode(('opencode:' + env['OPENCODE_SERVER_PASSWORD']).encode()).decode()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def request(path, payload=None, timeout=5):
        req = urllib.request.Request(endpoint + path, headers={'Authorization': auth, 'Content-Type': 'application/json'},
            data=json.dumps(payload).encode() if payload is not None else None)
        with opener.open(req, timeout=timeout) as response: return json.load(response)
    def stop(process):
        if process and process.poll() is None:
            process.terminate()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
    server = loop = None
    try:
        # A custom bank plugin can fail during config initialization/auth. One
        # bounded retry opens the isolated shell with a visible binding gate.
        for attempt in range(2):
            env['OPENCODE_CONFIG_CONTENT'] = json.dumps(config)
            try:
                with (DATA / 'logs/opencode.log').open('a', encoding='utf-8') as log:
                    server = subprocess.Popen([str(OPENCODE), 'serve', '--hostname', '127.0.0.1', '--port', str(port)], cwd=WORKSPACE, env=env, stdout=log, stderr=subprocess.STDOUT)
                deadline = time.monotonic() + 45
                while True:
                    if server.poll() is not None: raise RuntimeError('OPENCODE_PROCESS_START_FAILED')
                    try:
                        if request('/global/health', timeout=1).get('healthy'): break
                    except Exception: pass
                    if time.monotonic() >= deadline: raise RuntimeError('OPENCODE_PROCESS_START_TIMEOUT')
                    time.sleep(.25)
                with (DATA / 'logs/control-loop.log').open('a', encoding='utf-8') as log:
                    loop = subprocess.Popen([sys.executable, '-m', 'aitest_runtime.control_loop', '--workspace-root', str(WORKSPACE), '--interval', '3'], cwd=WORKSPACE, env=env, stdout=log, stderr=subprocess.STDOUT)
                time.sleep(4)
                if loop.poll() is not None: raise RuntimeError('CONTROL_LOOP_START_FAILED')
                if config.get('model'):
                    catalog = request('/provider', timeout=20)
                    if config['model'].split('/', 1)[0] not in catalog.get('connected', []):
                        raise RuntimeError('PROVIDER_MODEL_ADMISSION_PENDING')
                # Session creation does not require model auth. Reuse the real
                # Director entry Session; the Router still owns Worker Sessions.
                previous = read(DATA / 'state/director-entry-session.json', {})
                session = None
                if isinstance(previous, dict) and previous.get('session_id'):
                    try: session = request('/session/' + previous['session_id'], timeout=20)
                    except Exception: pass
                if not session:
                    title = 'AITest Director'
                    if binding_status['auth'] == 'AUTH_REQUIRED':
                        title += ' · AUTH_REQUIRED：菜单 5 绑定模型；勿在对话输入密钥'
                    session = request('/session', {'title': title}, timeout=20)
                if not isinstance(session, dict) or not session.get('id'): raise RuntimeError('R2_SESSION_ADMISSION_PENDING')
                write(DATA / 'state/director-entry-session.json', {'session_id': session['id'], 'operational_only': True})
                break
            except Exception:
                stop(loop); stop(server); loop = server = None
                if attempt or not config.get('model'): raise
                config = model_configuration({})
                binding_status.update(auth='AUTH_REQUIRED', binding_error='BANK_PROVIDER_BINDING_REQUIRED_PROVIDER_INIT_FAILED')
                print('BANK_PROVIDER_BINDING_REQUIRED：已批准 provider 暂未就绪，继续启动 OpenCode 设置入口。')
        readiness = {'server': 'PASS', 'control_loop_process': 'PASS',
                     'OPENCODE_PROCESS_READY': 'PASS', 'CONTROL_LOOP_START': 'PASS',
                     'AUTH_READY': binding_status['auth'],
                     'PROVIDER_MODEL_READY': 'CONFIGURED_UNVERIFIED' if config.get('model') else 'AUTH_REQUIRED',
                     'LLM_RUNTIME_READY': 'MODEL_TURN_REQUIRED', 'R2_SESSION_READY': 'PASS',
                     'director_session_id': session['id'],
                     'HOST_PROVIDER_DISCOVERY': 'PARTIAL_BANK_BINDING', 'model_turn': 'NOT_EXECUTED',
                     'provider_binding': binding_status, 'operational_only': True}
        write(DATA / 'state/startup-readiness.json', readiness)
        if check_only: return readiness
        if binding_status['auth'] != 'READY':
            print('OpenCode PROCESS_READY；Control Loop RUNNING；模型认证与进程启动分离。')
            print('模型设置 HumanGate：缺少模型时仍可进入 OpenCode，Mission 等待模型就绪。')
            print('OpenCode 会话标题显示认证提示；/aitest-provider-setup 为设置指引。')
            print('在安装入口菜单 5 复用已批准 provider；环境变量认证，禁止在对话输入密钥。')
        print('\n在对话中输入：测试 BLOAN1.9.4。4A 操作只在浏览器中完成，完成后回到对话输入“完成”。')
        return (attach_runner or subprocess.call)([str(OPENCODE), 'attach', endpoint, '--dir', str(WORKSPACE), '--session', session['id']], cwd=WORKSPACE, env=env)
    finally:
        stop(loop); stop(server)


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
    print('浏览器由您操作；完成教学后在此窗口按回车，再回到对话继续。')
    return subprocess.call([sys.executable, '-m', 'aitest_runtime.recovery_browser', '--workspace-root', str(WORKSPACE), '--mission-id', mission], cwd=WORKSPACE, env=prepare())


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
        print('\nAITest V1.12.0 Recovery · Windows 行内验证\n1 开始/继续测试对话\n2 能力自检\n3 导入需求/SST 附件\n4 导入 Current Release / Starlink 批准导出\n5 配置行内模型\n6 导出证据\n7 绑定测试环境\n8 浏览器人工教学 / 4A\n0 退出')
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
        except Exception as exc: print('未完成：' + str(exc))


if __name__ == '__main__':
    try: raise SystemExit(main())
    except KeyboardInterrupt: raise SystemExit(130)
