// Construction test: execute the actual TS exports with deterministic Bun I/O.
// The real OpenCode host/provider admission is a separate required gate.
// Run with Node >= 22: node --experimental-vm-modules <this file>
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { stripTypeScriptTypes } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const workspace = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const checks = {};
const domain = {
  status: 'PASS', truth_source: 'R1_EVENT_STREAM', conversation_is_not_truth: true,
  mission_id: 'mission-1', plan_id: 'plan-1', task_id: 'task-1', attempt_id: 'attempt-1',
  session_id: 'session-1', human_gate_id: 'gate-1', human_gate_state: 'WAITING_HUMAN',
  durable_references: ['r1:event:7'], error: null, nested: { unicode: '真实状态', values: [false, 0, null] },
};
let output, stderr, code, missing, spawnError, calls;
function reset(value = domain) {
  output = JSON.stringify(value); stderr = ''; code = 0; missing = ''; spawnError = false; calls = [];
}
// tool() is the plugin's identity registration function; schema only records
// descriptions here so every declared action can be exercised without an LLM.
const schema = new Proxy({}, { get: () => () => {
  const field = { description: '', describe(value) { this.description = value; return this; },
    optional() { return this; }, default() { return this; } };
  return field;
} });
const tool = Object.assign(value => value, { schema });
const context = vm.createContext({
  process: { platform: process.platform, cwd: () => '/construction/workspace', env: {
    AITEST_WORKSPACE_ROOT: '/construction/workspace', AITEST_RUNTIME_SPINE_DB: '/construction/state/runtime-spine.db',
  } }, Response, JSON,
  Bun: {
    file: name => ({ exists: async () => missing === 'workspace' ? false : !(missing === 'python' && name.includes('/runtime/python/')) }),
    spawn: (argv, options) => {
      if (spawnError) throw new Error('SPAWN_FAILURE');
      calls.push({ argv, options });
      return { stdout: new Response(output).body, stderr: new Response(stderr).body, exited: Promise.resolve(code) };
    },
  },
});
const dependencies = {
  path: new vm.SyntheticModule(['default'], function () { this.setExport('default', path); }, { context }),
  '@opencode-ai/plugin': new vm.SyntheticModule(['tool'], function () { this.setExport('tool', tool); }, { context }),
};
const modules = {};
for (const filename of ['aitest', 'pfc', 'aitest_human_gate']) {
  const source = readFileSync(path.join(workspace, '.opencode/tools', filename + '.ts'), 'utf8');
  const module = new vm.SourceTextModule(stripTypeScriptTypes(source), { context });
  await module.link(name => { assert.ok(dependencies[name], `Unexpected import ${name}`); return dependencies[name]; });
  await module.evaluate();
  modules[filename] = module.namespace;
}
function decode(result) {
  assert.ok(typeof result === 'string' || (result && typeof result.output === 'string'), 'OpenCode 1.18.3 ToolResult');
  return JSON.parse(typeof result === 'string' ? result : result.output);
}
const invoke = (definition, action) => definition.execute({
  action, target: action, intent: action, payload: { mission_id: 'mission-1' },
  mission_id: 'mission-1', user_text: '完成', actor_id: 'construction-user',
}, { directory: '/construction/workspace' });
let surfaceCount = 0;
for (const [filename, exports] of Object.entries(modules)) {
  for (const [name, definition] of Object.entries(exports)) {
    surfaceCount++;
    const key = `${filename}_${name}`;
    const field = definition.args.action || definition.args.target || definition.args.intent;
    const actions = field ? field.description.split('|') : ['resume'];
    // Unknown actions exercise pending/HOLD routes as well as the declared routes.
    for (const action of [...actions, '__unsupported__']) {
      for (const status of ['PASS', 'HOLD', 'INVALID_TARGET', 'NO_MISSION', 'FAIL']) {
        reset({ ...domain, status });
        const actual = decode(await invoke(definition, action));
        if (calls.length) {
          assert.deepEqual(actual, { ...domain, status }, `${key}/${action} domain fidelity`);
          const { argv, options } = calls[0];
          assert.equal(calls.length, 1);
          assert.equal(argv[0], path.join('/construction/workspace/runtime/python', process.platform === 'win32' ? 'python.exe' : 'python'));
          assert.equal(argv[2], 'aitest_runtime.product_entry');
          assert.equal(options.env.AITEST_RUNTIME_SPINE_DB, '/construction/state/runtime-spine.db');
        } else {
          assert.deepEqual(actual, {
            status: 'HOLD', runtime_truth: 'R1_EVENT_STREAM', legacy_runtime_write: 'FORBIDDEN',
            role: name.toUpperCase(), action, payload_received: true,
            reason: ({ executor: 'G5_DEFECT_TRUTH', worker: 'G4_REAL_EXECUTION', evaluator: 'G4_REAL_EXECUTION', knowledge: 'G6_R4_LEARNING' })[name] + '_CANONICAL_WIRING_PENDING',
          });
        }
      }
    }
    checks[key + '_all_declared_and_pending_actions_preserve_payload'] = true;
    reset(); await invoke(definition, actions[0]);
    if (!calls.length) continue; // Pure pending surface has no subprocess to fail.
    for (const failure of ['exit', 'json', 'truth', 'spawn', 'workspace', 'python']) {
      reset();
      if (failure === 'exit') { code = 9; stderr = 'DOMAIN_FAILURE'; }
      if (failure === 'json') output = 'not-json';
      if (failure === 'truth') output = JSON.stringify({ ...domain, truth_source: 'LEGACY' });
      if (failure === 'spawn') spawnError = true;
      if (failure === 'workspace' || failure === 'python') missing = failure;
      if (filename === 'pfc' && name === 'command' && failure === 'truth') continue; // Command has no truth-query guard.
      await assert.rejects(() => invoke(definition, actions[0]), failure === 'exit' ? /DOMAIN_FAILURE/ : undefined, `${key}/${failure}`);
      if (missing) assert.equal(calls.length, 0, 'No system Python or legacy fallback');
    }
    checks[key + '_failures_remain_failures_without_fallback'] = true;
  }
}
for (const value of [undefined, false, 'true', 1, null]) {
  reset({ ...domain, conversation_is_not_truth: value });
  await assert.rejects(() => invoke(modules.pfc.truth, 'project'), /R1 Event Stream truth contract not satisfied/);
}
checks.pfc_conversation_truth_guard_strict_boolean = true;
assert.equal(surfaceCount, 17, 'Review any newly exported surface');
console.log(JSON.stringify({ status: 'PASS', surface_count: surfaceCount, checks }, null, 2));
