"""Actual copied Node/Playwright/GitNexus offline component qualification."""
from __future__ import annotations
import argparse,hashlib,json,os,queue,shutil,subprocess,threading,time
from pathlib import Path
from rc6_runtime.process_environment import scoped_process_environment
from .runtime_delivery_contract import verify_turnkey_npm_package

ALIAS='rc72-offline-graph'
FENCE=r"""const net=require('node:net');
const deny=()=>{throw new Error('RC72_COMPONENT_NETWORK_FORBIDDEN')};
net.Socket.prototype.connect=deny;
require('node:http').request=deny;require('node:http').get=deny;
require('node:https').request=deny;require('node:https').get=deny;
require('node:tls').connect=deny;
if(globalThis.fetch)globalThis.fetch=deny;
const cp=require('node:child_process');
for(const key of ['spawn','spawnSync','exec','execSync','execFile','execFileSync']){
 const original=cp[key];cp[key]=function(...args){
  const command=String(args[0])+' '+JSON.stringify(args[1]||'');
  if(/(?:^|[\\/\s"'])((?:npm|npx|pnpm|yarn|curl|wget)(?:\.cmd|\.exe)?)(?:$|[\s"'])/i.test(command))
   throw new Error('RC72_COMPONENT_RUNTIME_INSTALL_OR_DOWNLOAD_FORBIDDEN');
  return original.apply(this,args);
 };
}
"""


def _json_result(text):
    # Published CLI commands emit both pretty JSON and diagnostic preambles.
    # Consume whole objects so nested objects cannot replace their parent.
    decoder=json.JSONDecoder();values=[];offset=0
    while offset<len(text):
        start=text.find('{',offset)
        if start<0:break
        try:value,length=decoder.raw_decode(text[start:])
        except ValueError:
            offset=start+1;continue
        if isinstance(value,dict):values.append(value)
        offset=start+length
    if not values:raise RuntimeError('EXECUTION_COMPONENT_STRUCTURED_RESULT_REQUIRED')
    return values[-1]


def _resource(node,cli,env,fixture,evidence):
    child=subprocess.Popen([str(node),str(cli),'mcp'],cwd=str(fixture),env=env,
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
    messages=queue.Queue();stdout=[];stderr=[]
    def read(stream,target,enqueue=False):
        for line in stream:
            target.append(line)
            if enqueue:messages.put(line)
    readers=[threading.Thread(target=read,args=(child.stdout,stdout,True),daemon=True),
             threading.Thread(target=read,args=(child.stderr,stderr),daemon=True)]
    for reader in readers:reader.start()
    def request(payload,response_id):
        child.stdin.write(json.dumps(payload)+'\n');child.stdin.flush();end=time.monotonic()+45
        while time.monotonic()<end:
            try:line=messages.get(timeout=min(1,max(.01,end-time.monotonic())))
            except queue.Empty:
                if child.poll() is not None:raise RuntimeError('EXECUTION_COMPONENT_MCP_EXITED')
                continue
            try:value=json.loads(line)
            except ValueError:continue
            if value.get('id')==response_id:
                if 'error' in value:raise RuntimeError('EXECUTION_COMPONENT_MCP_RESOURCE_REJECTED:'+str(value['error']))
                return value['result']
        raise RuntimeError('EXECUTION_COMPONENT_MCP_TIMEOUT')
    try:
        initialized=request(dict(jsonrpc='2.0',id=1,method='initialize',params=dict(protocolVersion='2024-11-05',
            capabilities={},clientInfo=dict(name='rc72-offline-component-probe',version='1'))),1)
        child.stdin.write(json.dumps(dict(jsonrpc='2.0',method='notifications/initialized'))+'\n');child.stdin.flush()
        uri='gitnexus://repo/'+ALIAS+'/context'
        result=request(dict(jsonrpc='2.0',id=2,method='resources/read',params=dict(uri=uri)),2)
        content=result.get('contents') or []
        if not content or not any(isinstance(c.get('text'),str) and c['text'].strip() for c in content):
            raise RuntimeError('EXECUTION_COMPONENT_MCP_CONTEXT_REQUIRED')
        return dict(uri=uri,result=result,protocol_version=initialized['protocolVersion'])
    finally:
        if child.poll() is None:
            child.terminate()
            try:child.wait(timeout=10)
            except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
        for reader in readers:reader.join(timeout=5)
        (evidence/'mcp.stdout.log').write_text(''.join(stdout),encoding='utf-8')
        (evidence/'mcp.stderr.log').write_text(''.join(stderr),encoding='utf-8')


def _windows_outbound_proof(node,env,evidence):
    if os.name!='nt':raise RuntimeError('EXECUTION_COMPONENT_WINDOWS_FIREWALL_REQUIRED')
    script = """$ErrorActionPreference='Stop';
$r=Get-NetFirewallRule -Name 'RC72-Execution-Node-Offline';
$a=$r | Get-NetFirewallApplicationFilter;
@{action=[string]$r.Action; direction=[string]$r.Direction; enabled=[string]$r.Enabled;
program=[string]$a.Program; profiles_enabled=@(Get-NetFirewallProfile | ForEach-Object {[string]$_.Enabled});
service=[string](Get-Service MpsSvc).Status} | ConvertTo-Json -Compress
"""
    child_env=dict(env,RC72_COMPONENT_NODE=str(node))
    # Match the actual workflow shell instead of starting legacy Windows
    # PowerShell 5 in a newly isolated profile for this CIM query.
    shell=shutil.which('pwsh.exe') or shutil.which('powershell.exe')
    if not shell:raise RuntimeError('EXECUTION_COMPONENT_FIREWALL_QUERY_SHELL_REQUIRED')
    for key in ('APPDATA','LOCALAPPDATA'):
        Path(child_env[key]).mkdir(parents=True,exist_ok=True)
    completed=subprocess.run([shell,'-NoProfile','-NonInteractive','-Command',script],env=child_env,
        capture_output=True,text=True,timeout=60)
    (evidence/'firewall-query.stdout.log').write_text(completed.stdout,encoding='utf-8')
    (evidence/'firewall-query.stderr.log').write_text(completed.stderr,encoding='utf-8')
    if completed.returncode:raise RuntimeError('EXECUTION_COMPONENT_FIREWALL_QUERY_FAILED')
    proof=_json_result(completed.stdout)
    if (proof.get('action')!='Block' or proof.get('direction')!='Outbound' or proof.get('enabled')!='True'
            or Path(proof.get('program','')).resolve()!=node.resolve() or proof.get('service')!='Running'
            or len(proof.get('profiles_enabled',[]))!=3 or any(v!='True' for v in proof['profiles_enabled'])):
        raise RuntimeError('EXECUTION_COMPONENT_FIREWALL_NOT_EFFECTIVE')
    return dict(proof,query_shell=shell)


def qualify(package_root,evidence_root,*,require_windows_outbound_block=False,require_full_text_search=False):
    root=Path(package_root).resolve();evidence=Path(evidence_root).resolve();evidence.mkdir(parents=True,exist_ok=True)
    node=root/'workspace-template/runtime/node/node.exe'
    if node.is_symlink() or not node.is_file():raise RuntimeError('EXECUTION_COMPONENT_PACKAGE_NODE_REQUIRED')
    node.resolve().relative_to(root)
    execution=root/'workspace-template/runtime/node-execution'
    graph=execution/'node_modules/gitnexus';metadata=verify_turnkey_npm_package(graph,'gitnexus')
    if metadata['status']!='PASS':raise RuntimeError('EXECUTION_COMPONENT_GRAPH_PAYLOAD_REQUIRED')
    cli=graph/metadata['cli_relative_path']
    lock=execution/'package-lock.json'
    if not lock.is_file():raise RuntimeError('EXECUTION_COMPONENT_DEPENDENCY_LOCK_REQUIRED')
    fence=evidence/'network-fence.cjs';fence.write_text(FENCE,encoding='utf-8')
    env=scoped_process_environment(dict(CI='true',GITNEXUS_HOME=str(evidence/'home/.gitnexus'),
        NODE_OPTIONS='--require='+json.dumps(fence.as_posix()),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',
        GITNEXUS_LBUG_EXTENSION_INSTALL='load-only'),home=evidence/'home')
    fts_manifest=None
    if (execution/'fts-payload/FTS-PAYLOAD.json').is_file():
        from .rc72_gitnexus_search_payload import restore
        fts_manifest=restore(root,evidence/'home')
    elif require_full_text_search:raise RuntimeError('EXECUTION_COMPONENT_FULL_TEXT_PAYLOAD_REQUIRED')
    firewall=_windows_outbound_proof(node,env,evidence) if require_windows_outbound_block else None
    fixture=evidence/'fixture';fixture.mkdir(exist_ok=True)
    (fixture/'math.ts').write_text('export function double(value: number): number { return value * 2; }\n')
    (fixture/'main.ts').write_text('import { double } from "./math";\nexport function run(): number { return double(2); }\n')
    def run(name,command,cwd,timeout=180):
        completed=subprocess.run([str(c) for c in command],cwd=str(cwd),env=env,capture_output=True,text=True,encoding='utf-8',timeout=timeout)
        (evidence/(name+'.stdout.log')).write_text(completed.stdout,encoding='utf-8')
        (evidence/(name+'.stderr.log')).write_text(completed.stderr,encoding='utf-8')
        if completed.returncode:raise RuntimeError('EXECUTION_COMPONENT_COMMAND_FAILED:'+name+':'+completed.stderr[-2000:])
        return completed.stdout
    node_version=run('node',[node,'--version'],execution).strip()
    graph_version=run('gitnexus-version',[node,cli,'--version'],execution).strip()
    playwright=run('playwright',[node,'-e',"console.log(JSON.stringify({version:require('playwright/package.json').version,available:!!require('playwright').chromium}))"],execution)
    if _json_result(playwright).get('available') is not True:raise RuntimeError('EXECUTION_COMPONENT_PLAYWRIGHT_REQUIRED')
    run('analyze-help',[node,cli,'analyze','--help'],fixture)
    run('status-help',[node,cli,'status','--help'],fixture)
    run('analyze',[node,cli,'analyze',fixture,'--skip-git','--index-only','--name',ALIAS,'--workers','1'],fixture,300)
    status=_json_result(run('status',[node,cli,'status','--repo',ALIAS,'--json'],fixture))
    if (status.get('error') or status.get('status')!='registered' or status.get('sourceAvailable') is not True
            or status.get('index',{}).get('runnerIdentityStatus')!='current' or status.get('index',{}).get('incompleteReasons')):
        raise RuntimeError('EXECUTION_COMPONENT_ACTUAL_INDEX_REQUIRED')
    context=_json_result(run('context',[node,cli,'context','double','--repo',ALIAS],fixture))
    if context.get('error') or context.get('partial') is True or context.get('symbol',{}).get('name')!='double':
        raise RuntimeError('EXECUTION_COMPONENT_GRAPH_SYMBOL_REQUIRED')
    calls=context.get('incoming',{}).get('calls',[])
    if not any(c.get('name')=='run' for c in calls):raise RuntimeError('EXECUTION_COMPONENT_ACTUAL_CALL_EDGE_REQUIRED')
    resource=_resource(node,cli,env,fixture,evidence)
    search=None
    if fts_manifest is not None:
        code="""const assert=require('node:assert');
const moduleValue=require('@ladybugdb/core');const lbug=moduleValue.default||moduleValue;
(async()=>{const db=new lbug.Database(process.argv[1],67108864,false,false,1073741824);
const conn=new lbug.Connection(db);
try{await conn.query('LOAD EXTENSION fts');
await conn.query('CREATE NODE TABLE Document(id INT64, text STRING, PRIMARY KEY(id))');
await conn.query("CREATE (:Document {id:1,text:'rc72offline exact callable symbol'})");
await conn.query("CREATE (:Document {id:2,text:'unrelated control content'})");
await conn.query("CALL CREATE_FTS_INDEX('Document','rc72_search',['text'],stemmer := 'none')");
const result=await conn.query("CALL QUERY_FTS_INDEX('Document','rc72_search','rc72offline') RETURN node.id AS id, score");
const rows=await result.getAll();assert(rows.length===1&&String(rows[0].id)==='1'&&Number.isFinite(rows[0].score));
console.log(JSON.stringify({native_fts_query:true,matched_id:String(rows[0].id),score:rows[0].score}));
}finally{await conn.close();await db.close();}})().catch(error=>{console.error(error);process.exitCode=1});"""
        search=_json_result(run('fulltext-query',[node,'-e',code,evidence/'fts-smoke.lbug'],execution))
        if search.get('native_fts_query') is not True:raise RuntimeError('EXECUTION_COMPONENT_NATIVE_FTS_QUERY_REQUIRED')
    # Preserve the actual native extension load diagnosis from this same copied
    # runtime. It is diagnostic evidence, not authority for graph/search PASS.
    doctor=subprocess.run([str(node),str(cli),'doctor'],cwd=str(fixture),env=env,
        capture_output=True,text=True,encoding='utf-8',timeout=180)
    (evidence/'doctor.stdout.log').write_text(doctor.stdout,encoding='utf-8')
    (evidence/'doctor.stderr.log').write_text(doctor.stderr,encoding='utf-8')
    if (fixture/'AGENTS.md').exists() or (fixture/'CLAUDE.md').exists():raise RuntimeError('EXECUTION_COMPONENT_INDEX_ONLY_REQUIRED')
    return dict(schema='RC72_EXECUTION_NODE_COMPONENT_V1',status='PASS',node=node_version,gitnexus=metadata,gitnexus_cli=graph_version,
        fts_search_qualified=search is not None,fts_native_query=search,fts_payload=fts_manifest,embeddings_qualified=False,extension_policy='load-only',
        native_doctor_diagnostic_exit_code=doctor.returncode,
        playwright=_json_result(playwright),index_status=status,symbol_context=context,mcp_context=resource,
        node_javascript_network_calls_denied=True,windows_program_outbound_block=firewall,embeddings_requested=False,change_truth_authority=False,
        dependency_lockfile_sha256=hashlib.sha256(lock.read_bytes()).hexdigest(),
        qualification_scope='COPIED_EXECUTION_NODE_COMPONENT_ONLY',full_product_package=False,field_verified=False,bank_final=False)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--package-root',required=True);parser.add_argument('--evidence-root',required=True);parser.add_argument('--require-windows-outbound-block',action='store_true');parser.add_argument('--require-full-text-search',action='store_true')
    args=parser.parse_args();out=Path(args.evidence_root);out.mkdir(parents=True,exist_ok=True)
    try:result=qualify(args.package_root,out,require_windows_outbound_block=args.require_windows_outbound_block,require_full_text_search=args.require_full_text_search)
    except Exception as exc:result=dict(status='FAIL',error=str(exc),error_type=type(exc).__name__,field_verified=False,bank_final=False)
    (out/'execution-node-capability.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(json.dumps(result,sort_keys=True));return 0 if result['status']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
