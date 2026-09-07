"""Isolated Intel Mac runtime candidate; NOT end-to-end product acceptance."""
from __future__ import annotations
import argparse, base64, hashlib, json, os, platform, secrets, shutil, signal, socket, subprocess, sys, time, urllib.parse, urllib.request
from pathlib import Path
BUNDLE=Path(__file__).resolve().parents[1]
INFO=json.loads((BUNDLE/'BUILD_INFO.json').read_text())
PY=BUNDLE/'runtime/python/bin/python3.12'
OC=BUNDLE/'runtime/opencode/opencode'
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()
def verify():
    if platform.system()!='Darwin' or platform.machine()!='x86_64':raise RuntimeError('本包仅支持 Intel/x86_64 macOS。')
    if sys.version_info[:3]!=(3,12,10):raise RuntimeError('必须使用包内 Python 3.12.10。')
    if sha(OC)!=INFO['opencode_binary_sha256']:raise RuntimeError('OpenCode 校验失败；未执行。')
    if subprocess.check_output([str(OC),'--version'],text=True).strip()!='1.18.3':raise RuntimeError('OpenCode 版本不匹配。')
    for name,digest in json.loads((BUNDLE/'SOURCE_HASHES.json').read_text()).items():
        p=BUNDLE/'workspace-template'/name
        if not p.is_file() or sha(p)!=digest:raise RuntimeError('源模板完整性检查失败：'+name)
def link_owned(path,target):
    if path.is_symlink():
        if path.resolve()!=target.resolve():path.unlink()
        else:return
    elif path.exists():raise RuntimeError('保留已有非本包链接，未覆盖：'+str(path))
    path.symlink_to(target,target_is_directory=True)
def prepare(root):
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(root,0o700)
    workspace=root/'workspace';marker=root/'INSTALLATION.json'
    if workspace.exists():
        if not marker.is_file() or json.loads(marker.read_text()).get('source_commit')!=INFO['source_commit']:raise RuntimeError('目录不是本包管理的实例；未覆盖。')
    else:
        staging=root/'workspace.preparing'
        if staging.exists():raise RuntimeError('保留上次未完成的安装目录，请勿覆盖。')
        shutil.copytree(BUNDLE/'workspace-template',staging,symlinks=True)
        marker.write_text(json.dumps({'source_commit':INFO['source_commit']}))
        staging.rename(workspace)
    (workspace/'runtime').mkdir(exist_ok=True)
    link_owned(workspace/'runtime/python',BUNDLE/'runtime/python')
    link_owned(workspace/'.opencode/node_modules',BUNDLE/'runtime/plugin/node_modules')
    install=workspace/'PFC_R1_R4_INSTALLATION.json'
    if not install.exists():install.write_text(json.dumps({'schema':'pfc.r1-r4.installation.v2','package_id':'MAC_RUNTIME_CANDIDATE_ONLY','build_identity':'NOT_WINDOWS_PACKAGE_TRUTH','workspace_root':str(workspace)}))
    for name in ['state','logs']:(root/name).mkdir(exist_ok=True,mode=0o700)
    env=os.environ.copy()
    env.update(AITEST_WORKSPACE_ROOT=str(workspace),AITEST_RUNTIME_SPINE_DB=str(root/'state/runtime-spine.db'),PYTHONPATH=str(workspace/'ai-test/runtime'),PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1',OPENCODE_DISABLE_AUTOUPDATE='1',OPENCODE_DISABLE_MODELS_FETCH='1',NO_PROXY='localhost,127.0.0.1,::1',no_proxy='localhost,127.0.0.1,::1')
    model=env.get('AITEST_MODEL','opencode/big-pickle')
    env['OPENCODE_CONFIG_CONTENT']=json.dumps({'model':model,'autoupdate':False})
    ca=Path.home()/'aitest-runtime/certs/macos-trusted.pem'
    if ca.is_file() and not env.get('NODE_EXTRA_CA_CERTS'):env['NODE_EXTRA_CA_CERTS']=str(ca)
    if not env.get('HTTPS_PROXY') and not env.get('https_proxy'):
        try:
            with socket.create_connection(('127.0.0.1',2080),timeout=.2):pass
            env['HTTP_PROXY']=env['HTTPS_PROXY']='http://127.0.0.1:2080'
        except OSError:pass
    return workspace,env,model
def check(root):
    workspace,env,_=prepare(root);results={}
    for name,args in [('director',['orchestrate','--role','DIRECTOR','--action','status','--payload','{}']),('project',['interactive-truth','--target','project'])]:
        p=subprocess.run([str(PY),'-m','aitest_runtime.product_entry',*args],cwd=workspace,env=env,capture_output=True,text=True,timeout=60)
        if p.returncode:raise RuntimeError(p.stderr or p.stdout)
        value=json.loads(p.stdout)
        if value.get('truth_source')!='R1_EVENT_STREAM' or value.get('conversation_is_not_truth') is not True:raise RuntimeError('Canonical truth envelope 检查失败。')
        results[name]=value
    print(json.dumps({'status':'SUBSTRATE_CHECK_PASS','evidence_type':'DIRECT_PYTHON_NOT_REAL_USER_TURN','results':results,'M_S02':'KNOWN_BLOCKED','MAC_CORE_PASS':False},ensure_ascii=False,indent=2))
def server(root,check_only=False):
    workspace,env,model=prepare(root)
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    endpoint=f'http://127.0.0.1:{port}';env['AITEST_OPENCODE_ENDPOINT']=endpoint
    env['OPENCODE_SERVER_USERNAME']='opencode';env['OPENCODE_SERVER_PASSWORD']=secrets.token_urlsafe(32)
    auth='Basic '+base64.b64encode(('opencode:'+env['OPENCODE_SERVER_PASSWORD']).encode()).decode()
    log=root/'logs/server.log'
    with log.open('a') as f:
        child=subprocess.Popen([str(OC),'serve','--hostname','127.0.0.1','--port',str(port)],cwd=workspace,env=env,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for _ in range(120):
                if child.poll() is not None:raise RuntimeError('服务未启动，日志：'+str(log))
                try:
                    q=urllib.parse.urlencode({'directory':str(workspace)})
                    req=urllib.request.Request(endpoint+'/session?'+q,headers={'Authorization':auth})
                    with opener.open(req,timeout=1) as r:
                        payload=json.load(r)
                        if r.status==200 and isinstance(payload,list):break
                except Exception:time.sleep(.5)
            else:raise RuntimeError('服务启动超时；未连接用户已有服务。')
            if check_only:
                help_text=subprocess.check_output([str(OC),'attach','--help'],env=env,text=True,stderr=subprocess.STDOUT)
                if '--dir' not in help_text:raise RuntimeError('attach --dir 不受支持。')
                print(json.dumps({'status':'NATIVE_SERVER_BOOT_PASS','session_api':'AUTHENTICATED','model_turn':'NOT_EXECUTED','product_acceptance':False},indent=2));return 0
            print('\n仅诊断模式；新测试入口仍有阻塞，不要提交真实银行数据。\n模型：'+model+'\n工作目录：'+str(workspace)+'\n日志：'+str(log))
            return subprocess.call([str(OC),'attach',endpoint,'--dir',str(workspace)],cwd=workspace,env=env)
        finally:
            if child.poll() is None:
                os.killpg(child.pid,signal.SIGTERM)
                try:child.wait(timeout=8)
                except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
def main():
    p=argparse.ArgumentParser();p.add_argument('--self-check',action='store_true');p.add_argument('--server-check',action='store_true');p.add_argument('--check-root',type=Path);a=p.parse_args()
    os.umask(0o077);verify()
    root=a.check_root or Path.home()/'Library/Application Support/AITestMac'/INFO['source_commit'][:12]
    if a.self_check:check(root);return 0
    if a.server_check:return server(root,True)
    print('OpenCode 测试数字员工 · Intel Mac 运行底座候选包\n\n不是已验收的开箱即用成品。自然语言新测试入口仍有代码阻塞。\n不修改 Documents 旧工程、系统 Python 或 Homebrew。\n\n1. 底座自检（不是产品场景验收）\n2. 诊断对话（已知入口阻塞）\n0. 退出')
    value=input('\n请选择 [默认退出]：').strip()
    if value=='1':check(root)
    elif value=='2':return server(root)
    return 0
if __name__=='__main__':
    try:code=main()
    except KeyboardInterrupt:code=130
    except Exception as e:print('\n未启动 / 已停止：'+str(e),file=sys.stderr);code=1
    if sys.stdin.isatty() and '--self-check' not in sys.argv and '--server-check' not in sys.argv:
        try:input('\n按回车关闭。')
        except (EOFError,KeyboardInterrupt):pass
    raise SystemExit(code)
