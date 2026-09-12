// Actual installed plugin schema + bridge unit test. Bun spawn is a local spy,
// not an OpenCode host or execution service; no real model/worker is claimed.
import {stripTypeScriptTypes} from 'node:module'
import {readFileSync,writeFileSync,mkdtempSync,rmSync} from 'node:fs'
import {tmpdir} from 'node:os'
import path from 'node:path'
import {pathToFileURL} from 'node:url'
import assert from 'node:assert/strict'
const root=path.resolve(import.meta.dirname,'../..'),plugin=path.resolve(process.argv[2]||'')
assert(process.argv[2],'pass the actual installed @opencode-ai/plugin/dist/index.js')
const tmp=mkdtempSync(path.join(tmpdir(),'aitest-worker-bridge-'))
try {
  const source=readFileSync(path.join(root,'workspace-template/.opencode/tools/aitest.ts'),'utf8')
    .replace('"@opencode-ai/plugin"',JSON.stringify(pathToFileURL(plugin).href))
    .replace('"../lib/model-result.mjs"',JSON.stringify(pathToFileURL(path.join(root,'workspace-template/.opencode/lib/model-result.mjs')).href))
  const compiled=path.join(tmp,'aitest.mjs');writeFileSync(compiled,stripTypeScriptTypes(source))
  const {director,general_worker}=await import(pathToFileURL(compiled).href)
  const calls=[]
  globalThis.Bun={file:()=>({exists:async()=>true}),spawn:(command,options)=>{
    calls.push({command,options});return {stdout:new Response(JSON.stringify({status:'BRIDGE_SPY_ONLY',truth_source:'R1_EVENT_STREAM'})).body,stderr:new Response('').body,exited:Promise.resolve(0)}
  }}
  process.env.AITEST_HOST_SESSION_ID='spoof-session';process.env.AITEST_HOST_MESSAGE_ID='spoof-message';process.env.AITEST_HOST_CALL_ID='spoof-call'
  const host={directory:root,sessionID:'actual-session',messageID:'actual-assistant',callID:'actual-call'}
  const checks={}
  checks.strict_identity_fields=['caller','session_id','epoch','lease','approval','roots'].every(key=>!general_worker.args.payload.safeParse({job_id:'j',[key]:'forged'}).success)
  checks.actions=general_worker.args.action.options.length===8
  await general_worker.execute({action:'read_file',payload:{job_id:'j',path:'notes/a.txt'}},host)
  let captured=calls.at(-1)
  checks.bridge_actual_context=captured.options.env.AITEST_HOST_SESSION_ID==='actual-session'&&captured.options.env.AITEST_HOST_MESSAGE_ID==='actual-assistant'&&captured.options.env.AITEST_HOST_CALL_ID==='actual-call'
  checks.payload_exact=JSON.stringify(JSON.parse(captured.command.at(-1)))===JSON.stringify({job_id:'j',path:'notes/a.txt'})
  await general_worker.execute({action:'status',payload:{job_id:'j'}},{...host,callID:undefined})
  checks.missing_call_clears_inherited=calls.at(-1).options.env.AITEST_HOST_CALL_ID===''
  let denied=0
  for(const [args,ctx] of [[{action:'read_file',payload:{job_id:'j'}},host],[{action:'status',payload:{job_id:'j',lease:'fake'}},host],[{action:'status',payload:{job_id:'j'}},{}]]){
    const before=calls.length
    try{await general_worker.execute(args,ctx)}catch{if(calls.length===before)denied++}
  }
  checks.invalid_before_spawn=denied===3
  await director.execute({action:'interact',payload:{}},host)
  checks.primary_bridge_call_identity=calls.at(-1).options.env.AITEST_HOST_CALL_ID==='actual-call'
  assert(Object.values(checks).every(Boolean),JSON.stringify(checks))
  console.log(JSON.stringify({status:'PASS',proof:'installed plugin schema and bridge unit; spawn spy only',checks},null,2))
} finally {rmSync(tmp,{recursive:true,force:true})}
