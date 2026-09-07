"""V1.12.0 one-entry offline Windows package launcher."""
from __future__ import annotations
import argparse
import base64
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
    for name in ('state', 'logs', 'evidence', 'imports', 'exports'): (DATA / name).mkdir(parents=True, exist_ok=True)
    (WORKSPACE / 'bindings').mkdir(exist_ok=True)
    sys.path.insert(0, str(WORKSPACE / 'ai-test/runtime'))
    os.environ.update(AITEST_WORKSPACE_ROOT=str(WORKSPACE), AITEST_RUNTIME_SPINE_DB=str(DATA / 'state/runtime-spine.db'),
        PFC_LOCAL_STATE_ROOT=str(DATA), PYTHONPATH=str(WORKSPACE / 'ai-test/runtime'), PYTHONNOUSERSITE='1',
        PYTHONDONTWRITEBYTECODE='1', AITEST_G4_PROVIDER_FACTORY='aitest_runtime.recovery_executors:provider_bundle',
        AITEST_CONTROL_LOOP_HEARTBEAT_PATH=str(DATA / 'state/control-loop-heartbeat.json'),
        OPENCODE_DISABLE_AUTOUPDATE='1', OPENCODE_DISABLE_MODELS_FETCH='1', OPENCODE_DISABLE_DEFAULT_PLUGINS='1',
        OPENCODE_DISABLE_LSP_DOWNLOAD='1', OPENCODE_DISABLE_SHARE='1', PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD='1',
        PIP_NO_INDEX='1', NO_PROXY='localhost,127.0.0.1,::1', no_proxy='localhost,127.0.0.1,::1',
        XDG_DATA_HOME=str(DATA / 'opencode-data'), XDG_CONFIG_HOME=str(DATA / 'opencode-config'),
        XDG_CACHE_HOME=str(DATA / 'opencode-cache'), BUN_INSTALL_CACHE_DIR=str(DATA / 'bun-cache'))
    java = WORKSPACE / 'runtime/tools/java'
    if java.is_dir(): os.environ['JAVA_HOME'] = str(java)
    from aitest_runtime.canonical_runtime import create_canonical_runtime
    create_canonical_runtime(WORKSPACE)
    return dict(os.environ)


def verify_files():
    manifest = read(BUNDLE / 'FILE_SHA256.json', {})
    if not manifest: return ['FILE_SHA256.json 缺失']
    failures = []
    for relative, expected in manifest.items():
        path = (BUNDLE / relative).resolve()
        if not path.is_relative_to(BUNDLE) or not path.is_file() or sha(path) != expected:
            failures.append(relative)
    return failures


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
    model = read(DATA / 'model.json', {})
    matrix = {
        'Runtime': 'READY' if runtime.get('truth_source') == 'R1_EVENT_STREAM' else 'FAIL',
        'OpenCode': oc_status,
        'Model': 'READY' if model and os.environ.get('AITEST_MODEL_KEY') else 'AUTH_REQUIRED',
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
            'security_scope': 'API_PASSIVE_BASELINE; ZAP payload separate, active scan requires governed binding'}


def display_doctor(full=True):
    result = doctor(full)
    print('\nAITest V1.12.0 · 能力自检')
    for key, value in result['matrix'].items(): print(f'  {key:15} {value}')
    print('G1-G5 CLOSED/FROZEN；G6 HOLD。行内结果需要现场验证。')
    write(DATA / 'logs/doctor.json', result)
    return result


def model_settings():
    print('填写行内已批准模型服务；不执行依赖安装。密钥仅在当前进程内使用。')
    endpoint = input('OpenAI 兼容服务地址（包含 /v1）：').strip()
    name = input('模型 ID：').strip()
    if not endpoint.startswith(('http://', 'https://')) or not name: raise ValueError('地址与模型 ID 必填')
    write(DATA / 'model.json', {'base_url': endpoint, 'model': name})


def start_conversation(check_only=False):
    if os.name != 'nt': raise RuntimeError('WINDOWS_HOST_REQUIRED')
    report = display_doctor(True)
    if report['integrity_failures'] or report['matrix']['OpenCode'] != 'READY': raise RuntimeError('交付文件校验失败')
    env = prepare()
    model = read(DATA / 'model.json', {})
    config = {'autoupdate': False, 'share': 'disabled'}
    if model:
        if not check_only:
            env['AITEST_MODEL_KEY'] = os.environ.get('AITEST_MODEL_KEY') or getpass.getpass('行内模型密钥（不回显、不保存）：')
        config.update(model='bank/' + model['model'], provider={'bank': {'npm': '@ai-sdk/openai-compatible',
            'name': 'Bank approved model', 'options': {'baseURL': model['base_url'], 'apiKey': '{env:AITEST_MODEL_KEY}'},
            'models': {model['model']: {'name': model['model']}}}})
    env['OPENCODE_CONFIG_CONTENT'] = json.dumps(config)
    with socket.socket() as sock: sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    endpoint = f'http://127.0.0.1:{port}'
    env.update(AITEST_OPENCODE_ENDPOINT=endpoint, OPENCODE_SERVER_USERNAME='opencode', OPENCODE_SERVER_PASSWORD=secrets.token_urlsafe(32))
    auth = 'Basic ' + base64.b64encode(('opencode:' + env['OPENCODE_SERVER_PASSWORD']).encode()).decode()
    server = loop = None
    try:
        with (DATA / 'logs/opencode.log').open('a', encoding='utf-8') as log:
            server = subprocess.Popen([str(OPENCODE), 'serve', '--hostname', '127.0.0.1', '--port', str(port)], cwd=WORKSPACE, env=env, stdout=log, stderr=subprocess.STDOUT)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(120):
            if server.poll() is not None: raise RuntimeError('OpenCode 启动失败，查看 data/logs/opencode.log')
            try:
                req = urllib.request.Request(endpoint + '/session', headers={'Authorization': auth})
                with opener.open(req, timeout=1) as response:
                    if isinstance(json.load(response), list): break
            except Exception: time.sleep(.5)
        else: raise RuntimeError('OpenCode 启动超时')
        with (DATA / 'logs/control-loop.log').open('a', encoding='utf-8') as log:
            loop = subprocess.Popen([sys.executable, '-m', 'aitest_runtime.control_loop', '--workspace-root', str(WORKSPACE), '--interval', '3'], cwd=WORKSPACE, env=env, stdout=log, stderr=subprocess.STDOUT)
        if check_only:
            time.sleep(4)
            if loop.poll() is not None: raise RuntimeError('Control Loop 启动失败')
            return {'server': 'PASS', 'control_loop_process': 'PASS', 'model_turn': 'AUTH_REQUIRED'}
        print('\n在对话中输入：测试 BLOAN1.9.4。4A 操作只在浏览器中完成，完成后回到对话输入“完成”。')
        return subprocess.call([str(OPENCODE), 'attach', endpoint, '--dir', str(WORKSPACE)], cwd=WORKSPACE, env=env)
    finally:
        for process in (loop, server):
            if process and process.poll() is None:
                process.terminate()
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired: process.kill(); process.wait()


def evidence_export():
    target = DATA / 'exports' / ('AITest-Evidence-' + time.strftime('%Y%m%d-%H%M%S') + '.zip')
    snapshot = DATA / 'exports/runtime-spine.snapshot.db'
    with sqlite3.connect(DATA / 'state/runtime-spine.db') as source, sqlite3.connect(snapshot) as dest: source.backup(dest)
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
    args = parser.parse_args(); prepare()
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
