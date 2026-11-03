"""The actual Node preload denies connections and package-manager fallback."""
import shutil,socket,subprocess
import pytest
from rc7_release.rc72_execution_node_qualification import FENCE,qualify


def test_actual_node_socket_and_runtime_package_manager_are_fenced(tmp_path):
    node=shutil.which('node')
    if not node:pytest.skip('actual Windows copied-runtime workflow supplies Node')
    fence=tmp_path/'network fence.cjs';fence.write_text(FENCE)
    server=socket.socket();server.bind(('127.0.0.1',0));server.listen(1);server.settimeout(.1)
    code="""const assert=require('node:assert');
assert.throws(()=>require('node:net').connect({host:'127.0.0.1',port:PORT}),/RC72_COMPONENT_NETWORK_FORBIDDEN/);
assert.throws(()=>require('node:child_process').spawnSync('npm',['--version']),/RUNTIME_INSTALL_OR_DOWNLOAD_FORBIDDEN/);
console.log('ACTUAL_FENCE_PASS');""".replace('PORT',str(server.getsockname()[1]))
    try:
        child=subprocess.run([node,'--require',str(fence),'-e',code],capture_output=True,text=True,timeout=20)
        assert child.returncode==0,child.stderr
        assert child.stdout.strip()=='ACTUAL_FENCE_PASS'
        with pytest.raises(socket.timeout):server.accept()
    finally:server.close()


def test_missing_packaged_node_cannot_fall_back_to_host_node(tmp_path):
    with pytest.raises(RuntimeError,match='PACKAGE_NODE_REQUIRED'):qualify(tmp_path/'empty package',tmp_path/'evidence')
