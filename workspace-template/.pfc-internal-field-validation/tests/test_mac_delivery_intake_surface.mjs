// Action-specific schema regression using real pinned plugin/Zod declarations.
// Construction proof only; native user-turn provenance requires host acceptance.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { stripTypeScriptTypes } from 'node:module';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import vm from 'node:vm';
const workspace = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const dependencyRoot = process.env.MAC_DELIVERY_PLUGIN_ROOT;
assert.ok(dependencyRoot, 'Supply the verified plugin dependency directory for construction tests');
const pluginDirectory = path.join(dependencyRoot, 'node_modules/@opencode-ai/plugin');
const manifest = JSON.parse(readFileSync(path.join(pluginDirectory, 'package.json'), 'utf8'));
assert.equal(manifest.version, '1.18.3');
const pluginPath = path.join(pluginDirectory, manifest.exports['./tool'].import);
const { tool } = await import(pathToFileURL(pluginPath).href);
const context = vm.createContext({ process, Response, JSON });
const dependencies = {
  path: new vm.SyntheticModule(['default'], function () { this.setExport('default', path); }, { context }),
  '@opencode-ai/plugin': new vm.SyntheticModule(['tool'], function () { this.setExport('tool', tool); }, { context }),
};
const module = new vm.SourceTextModule(stripTypeScriptTypes(readFileSync(path.join(workspace, '.opencode/tools/aitest.ts'), 'utf8')), { context });
await module.link(name => { assert.ok(dependencies[name], `Review dependency ${name}`); return dependencies[name]; });
await module.evaluate();
const schema = tool.schema.object(module.namespace.director.args);
const malformed = schema.safeParse({ action: 'start_test', payload: { operation: 'GUESS', scope: 'free text', source_digest: 'model-guessed-hash' } });
const result = { evidence_type: 'CONSTRUCTION_SCHEMA_DIAGNOSTIC', malformed_start_test_rejected: !malformed.success,
  hosted_turn: 'NOT_RUN', native_session_id: null, product_acceptance: false };
console.log(JSON.stringify(result, null, 2));
assert.equal(malformed.success, false, 'OpenCode-facing start_test must expose an action-specific contract rejecting structurally invalid intake');
