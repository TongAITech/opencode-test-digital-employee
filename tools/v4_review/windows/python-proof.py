"""Real portable Python inside AppContainer; all targets are disposable fixtures."""
import ctypes, json, pathlib, socket, subprocess, sys, time
root=pathlib.Path(sys.argv[1]); sid=sys.argv[2]; port=int(sys.argv[3]); exe=sys.argv[4]
notes=root/'notes'; result={'interpreter':'PORTABLE_PYTHON','version':sys.version,'executable':sys.executable}
advapi=ctypes.WinDLL('advapi32',use_last_error=True); kernel=ctypes.WinDLL('kernel32',use_last_error=True)
advapi.OpenProcessToken.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.POINTER(ctypes.c_void_p)]
advapi.GetTokenInformation.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_uint32,ctypes.POINTER(ctypes.c_uint32)]
token=ctypes.c_void_p(); assert advapi.OpenProcessToken(ctypes.c_void_p(-1),8,ctypes.byref(token))
def info(kind):
 n=ctypes.c_uint32();advapi.GetTokenInformation(token,kind,None,0,ctypes.byref(n));buf=ctypes.create_string_buffer(n.value)
 assert advapi.GetTokenInformation(token,kind,buf,n.value,ctypes.byref(n));return buf
result['appcontainer']=bool(ctypes.c_uint32.from_buffer(info(29)).value)
result['capability_count']=ctypes.c_uint32.from_buffer(info(30)).value
kernel.CloseHandle(token)
(notes/'python-note.txt').write_text('PYTHON_ALLOWED');result['permitted_write']=(notes/'python-note.txt').read_text()=='PYTHON_ALLOWED'
result['permitted_read']=(root/'read/diagnostic.txt').read_text()=='DIAGNOSTIC_FIXTURE'
paths={'protected':root/'protected/runtime-spine.db','outside':root/'outside/outside.txt','readonly_write':root/'read/diagnostic.txt','traversal':notes/'../protected/runtime-spine.db','case':pathlib.Path(str(root/'outside/outside.txt').upper()),'junction':notes/'escape/runtime-spine.db'}
for name,path in paths.items():
 try:path.write_text('PYTHON_UNAUTHORIZED');result[name]={'denied':False,'wrote':True}
 except PermissionError as e:result[name]={'denied':e.winerror==5,'winerror':e.winerror}
 except Exception as e:result[name]={'denied':False,'error':repr(e)}
for name in ('protected','outside'):
 try:paths[name].read_bytes();result[name+'_read']={'denied':False,'read':True}
 except PermissionError as e:result[name+'_read']={'denied':e.winerror==5,'winerror':e.winerror}
 except Exception as e:result[name+'_read']={'denied':False,'error':repr(e)}
with socket.socket() as sock:
 sock.bind(('127.0.0.1',0));sock.settimeout(3)
 net={'local_port':sock.getsockname()[1],'remote_port':port,'denied':False}
 try:sock.connect(('127.0.0.1',port));sock.send(b'PYTHON_UNAUTHORIZED');net['connected']=True
 except OSError as e:net.update(error=repr(e),winerror=getattr(e,'winerror',None),denied=getattr(e,'winerror',None)==10013)
 result['network']=net
p=subprocess.run([exe,'--attack',str(root),sid,str(port),'python-descendant'],capture_output=True,text=True,timeout=20)
result['native_descendant']={'exit':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
(notes/'python-result.json').write_text(json.dumps(result))
