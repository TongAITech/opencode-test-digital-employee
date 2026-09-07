"""Build a native runtime candidate without modifying frozen product sources."""
from pathlib import Path
import argparse,hashlib,json,os,shutil,subprocess,tarfile,zipfile,stat

OPENCODE_LICENSE='''MIT License

Copyright (c) 2025 opencode

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
'''
def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()

def main():
    p=argparse.ArgumentParser();p.add_argument('--inputs',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();inputs=a.inputs.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    bundle=out/'AITest-Mac-Intel-Runtime-Candidate';bundle.mkdir();source=out/'source';source.mkdir()
    with tarfile.open(inputs/'source.tar.gz') as t:t.extractall(source,filter='data')
    shutil.copytree(source/'workspace-template',bundle/'workspace-template',symlinks=True)
    if digest(inputs/'runtime/python.tar.gz')!='d0d51fa22c0e99b58de1b1b4baeca467d6fd0a1424c7509ea280c0796306c481':raise RuntimeError('Python archive mismatch')
    (bundle/'runtime').mkdir();(bundle/'runtime/opencode').mkdir()
    with tarfile.open(inputs/'runtime/python.tar.gz') as t:t.extractall(bundle/'runtime',filter='data')
    with zipfile.ZipFile(inputs/'runtime/opencode.zip') as z:z.extractall(bundle/'runtime/opencode')
    oc=bundle/'runtime/opencode/opencode';oc.chmod(0o755)
    if digest(oc)!='ba11415d6af7efc9dc0073520d546b869711da5f39076d12e08eeb266ba1279b':raise RuntimeError('OpenCode mismatch')
    (bundle/'runtime/opencode/LICENSE').write_text(OPENCODE_LICENSE)
    (bundle/'runtime/python/python').symlink_to('bin/python3.12')
    shutil.copytree(inputs/'plugin',bundle/'runtime/plugin',symlinks=True)
    (bundle/'app').mkdir();shutil.copy2(Path(__file__).with_name('launcher.py'),bundle/'app/launcher.py')
    commit=(inputs/'source-commit.txt').read_text().strip()
    hashes={str(f.relative_to(bundle/'workspace-template')):digest(f) for f in (bundle/'workspace-template').rglob('*') if f.is_file()}
    (bundle/'SOURCE_HASHES.json').write_text(json.dumps(hashes,ensure_ascii=False,indent=2))
    info={'source_commit':commit,'product_status':'NOT_TURNKEY / M_S02_BLOCKED','target':'macOS Intel x86_64','opencode_version':'1.18.3','opencode_binary_sha256':digest(oc),'python_version':'3.12.10','python_archive_sha256':digest(inputs/'runtime/python.tar.gz'),'browser_included':False,'bank_environment_included':False,'credentials_included':False,'windows_authority':False,'automatic_product_mutation':False}
    (bundle/'BUILD_INFO.json').write_text(json.dumps(info,indent=2))
    entry=bundle/'启动.command';entry.write_text('#!/bin/bash\nset -euo pipefail\nBASE="$(cd -- "$(dirname -- "$0")" && pwd -P)"\nif [ "$(uname -s)" != Darwin ] || [ "$(uname -m)" != x86_64 ]; then\n  echo "本包仅用于 Intel/x86_64 macOS。"; read -r _; exit 1\nfi\nexec "$BASE/runtime/python/bin/python3.12" "$BASE/app/launcher.py" "$@"\n');entry.chmod(0o755)
    (bundle/'先读我.txt').write_text('''这是 Intel macOS 运行底座候选包，不是已验收的开箱即用成品。
双击“启动.command”可打开自检/诊断入口。不需要 pip、npm 或 Homebrew 安装。
不修改 Documents 旧工程，不 reset/clean，不修改系统 Python。
独立数据目录：~/Library/Application Support/AITestMac/<source-commit>/
模型仍需网络及有效的既有授权；包内没有账号、密钥或银行数据。
若系统安全机制阻止打开，请审阅来源后使用系统允许打开流程，不要关闭整体防护。
已内置：OpenCode 1.18.3、Intel Python 3.12.10、插件 1.18.3 及其依赖、exact Git workspace。
未包含：浏览器/Playwright 运行绑定、银行业务环境、完整端到端测试通过证据。
本包不启动后台产品推进循环。默认退出，不自动发起业务测试。
已知阻塞：自然语言 start_test 修复尚未提交；合法 intake 还会在默认 R2.1 resolver 访问旧 truth_snapshots 表时报错。
不得通过初始化旧库或伪造 RESOLVED 来绕过。M-S02 未通过，后续场景未执行。
原生 Mac 自检、服务启动及失败复现证据位于 build-evidence；它们不是完整产品 PASS。
''',encoding='utf-8')
    evidence=bundle/'build-evidence';shutil.copytree(inputs/'evidence',evidence)
    py=bundle/'runtime/python/bin/python3.12'
    def execute(name,command,timeout=180):
        with (evidence/(name+'.stdout')).open('w') as stdout,(evidence/(name+'.stderr')).open('w') as stderr:
            done=subprocess.run([str(x) for x in command],stdout=stdout,stderr=stderr,timeout=timeout)
        if done.returncode:raise RuntimeError(f'{name} failed: {done.returncode}')
    checkroot=out/'native selfcheck with spaces'
    execute('native-substrate-check',[py,bundle/'app/launcher.py','--self-check','--check-root',checkroot])
    execute('native-server-check',[py,bundle/'app/launcher.py','--server-check','--check-root',checkroot])
    execute('default-resolver-probe',[py,Path(__file__).with_name('probe.py'),'--source',source,'--output',evidence])
    for f in bundle.rglob('*'):
        if f.is_file() and f.suffix.lower() in {'.ttf','.otf','.woff','.woff2'}:raise RuntimeError('Unexpected font asset')
        if f.is_file() and f.suffix.lower()=='.db':raise RuntimeError('Runtime DB must not be shipped')
    info['native_checks']={'substrate':'PASS','server_boot':'PASS','default_resolver':'FAIL_REPRODUCED','real_user_turn':'NOT_EXECUTED','full_product':'NOT_PASSED'}
    (bundle/'BUILD_INFO.json').write_text(json.dumps(info,indent=2))
    manifest={str(f.relative_to(bundle)):digest(f) for f in bundle.rglob('*') if f.is_file() and not f.is_symlink()}
    (bundle/'FILE_SHA256.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    archive=out/'AITest-Mac-Intel-Runtime-Candidate.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=4) as z:
        for f in sorted(bundle.rglob('*')):
            relative=str(f.relative_to(out))
            if f.is_symlink():
                item=zipfile.ZipInfo(relative);item.create_system=3;item.external_attr=(stat.S_IFLNK|0o777)<<16;z.writestr(item,os.readlink(f))
            else:z.write(f,relative)
    (out/'SHA256SUMS.txt').write_text(digest(archive)+'  '+archive.name+'\n')
    shutil.copytree(evidence,out/'review-evidence')
    shutil.rmtree(source);shutil.rmtree(checkroot);shutil.rmtree(bundle)
    print(json.dumps({'archive':str(archive),'sha256':digest(archive),'status':'RUNTIME_CANDIDATE_ONLY_NOT_TURNKEY'},indent=2))
if __name__=='__main__':main()
