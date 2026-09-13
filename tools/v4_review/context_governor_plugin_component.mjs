import assert from "node:assert/strict"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { pathToFileURL } from "node:url"

const repo = path.resolve(process.cwd())
const workspace = path.join(repo, "workspace-template")
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "aitest-context-plugin-"))
const python = path.join(tmp, "runtime", "python", process.platform === "win32" ? "python.exe" : "python")
fs.mkdirSync(path.dirname(python), { recursive: true })
fs.writeFileSync(python, "")

const captured = []
const encoder = new TextEncoder()

function fakeProcess(decide) {
  let input = ""
  let outController
  let errController
  let resolveCode
  const stdout = new ReadableStream({ start(controller) { outController = controller } })
  const stderr = new ReadableStream({ start(controller) { errController = controller } })
  const exited = new Promise((resolve) => { resolveCode = resolve })
  return {
    stdin: {
      write(value) { input += String(value) },
      end() {
        const payload = JSON.parse(input)
        captured.push(payload)
        const result = decide(payload)
        outController.enqueue(encoder.encode(JSON.stringify(result)))
        outController.close()
        errController.close()
        resolveCode(0)
      },
    },
    stdout,
    stderr,
    exited,
  }
}

globalThis.Bun = {
  file(file) {
    return {
      async exists() { return fs.existsSync(file) },
      async text() { return fs.promises.readFile(file, "utf8") },
    }
  },
  spawn() {
    return fakeProcess((payload) => {
      if (payload.current_user_replay_safe === false) {
        return { status: "ERROR", error: "PRIMARY_CONTEXT_REPLAY_NON_TEXT_UNSUPPORTED" }
      }
      return payload.messages_bytes > 5000
        ? { status: "BLOCK", recovery: { status: "ROTATED" } }
        : { status: "ALLOW", recovery: null }
    })
  },
}

process.env.AITEST_WORKSPACE_ROOT = tmp
const pluginPath = path.join(workspace, ".opencode", "plugins", "aitest-context-governor.js")
const mod = await import(pathToFileURL(pluginPath).href + "?component=" + Date.now())
assert.equal(typeof mod.default, "function")
const hooks = await mod.default({ directory: workspace })

hooks.config({ permission: { "*": "deny" } })

const allowedTool = { description: "director-v1", jsonSchema: { type: "object", properties: { action: { type: "string" } } } }
const deniedTool = { description: "shell-must-not-count", jsonSchema: { type: "object", properties: { argv: { type: "array" } } } }
await hooks["tool.definition"]({ toolID: "aitest_director" }, allowedTool)
await hooks["tool.definition"]({ toolID: "shell" }, deniedTool)
// Simulate a plugin loaded after AITest mutating the same definition object.
allowedTool.description += "-late-plugin-expansion-" + "x".repeat(256)

const messages = [{
  info: { id: "usr1", sessionID: "ses_component", role: "user" },
  parts: [{ type: "text", text: "hello" }],
}]
await hooks["experimental.chat.messages.transform"]({}, { messages })

const system = ["base-system"]
await hooks["experimental.chat.system.transform"](
  { sessionID: "ses_component", model: { limit: { context: 128000 } } },
  { system },
)
// The governor retains references, so later hook mutations must be visible at chat.params.
system.push("late-system-" + "s".repeat(128))
messages.push({
  info: { id: "asst1", sessionID: "ses_component", role: "assistant" },
  parts: [{ type: "text", text: "late-message" }],
})

const firstParams = { maxOutputTokens: 8192, options: { base: true } }
const firstInput = {
  sessionID: "ses_component",
  agent: "aitest-director",
  model: { providerID: "fixture", id: "fixture-model", limit: { context: 128000, input: 64000, output: 32768 } },
  message: { id: "usr1" },
}
await hooks["chat.params"](firstInput, firstParams)
// Simulate a plugin after AITest in the chat.params chain.
firstParams.maxOutputTokens = 16384
firstParams.options.late = "p".repeat(256)
await hooks["chat.headers"](firstInput, { headers: {} })
assert.equal(captured.length, 1)
assert.equal(captured[0].session_id, "ses_component")
assert.equal(captured[0].current_user_text, "hello")
assert.equal(captured[0].current_user_replay_safe, true)
assert.deepEqual(captured[0].current_user_part_types, ["text"])
assert.equal(captured[0].tool_count, 1, "deny-all agent must not budget unrelated shell tool")
assert.ok(captured[0].tools_bytes > 256, "late tool-definition mutation must be included")
assert.ok(captured[0].system_bytes > 128, "late system mutation must be included")
assert.equal(captured[0].message_count, 2)
assert.equal(captured[0].max_output_tokens, 16384, "final provider maxOutputTokens must override the advertised model maximum")
assert.equal(captured[0].input_limit, 64000, "independent model input limit must reach Runtime admission")
assert.ok(captured[0].extra_bytes > 1200, "final chat.params options must be included before admission")

messages.push({
  info: { id: "tool-heavy", sessionID: "ses_component", role: "assistant" },
  parts: [{
    type: "tool",
    tool: "aitest_director",
    state: {
      input: { payload: "参".repeat(2200) },
      output: "果".repeat(2200),
    },
  }],
})
messages.push({
  info: { id: "usr2", sessionID: "ses_component", role: "user" },
  parts: [{ type: "text", text: "继续测试 BLOAN" }],
})
let blocked = false
try {
  const secondInput = {
    sessionID: "ses_component",
    agent: "aitest-director",
    model: { providerID: "fixture", id: "fixture-model", limit: { context: 128000, input: 64000, output: 32768 } },
    message: { id: "usr2" },
  }
  // Each OpenCode provider request reruns messages/system transforms. The
  // governor must not depend on retaining a prior request snapshot.
  await hooks["experimental.chat.messages.transform"]({}, { messages })
  await hooks["experimental.chat.system.transform"](
    { sessionID: "ses_component", model: secondInput.model },
    { system },
  )
  await hooks["chat.params"](secondInput, { maxOutputTokens: 8192, options: {} })
  await hooks["chat.headers"](secondInput, { headers: {} })
} catch (error) {
  blocked = String(error).includes("AITEST_CONTEXT_ADMISSION_BLOCKED:ROTATED")
}
assert.equal(blocked, true, "BLOCK decision must abort the old pre-provider path")
assert.equal(captured.length, 2)
assert.ok(captured[1].messages_bytes > 5000, "large Chinese tool args/results must enter final history budget")
assert.equal(captured[1].current_user_text, "继续测试 BLOAN")
assert.equal(captured[1].current_user_replay_safe, true)

messages.push({
  info: { id: "usr3", sessionID: "ses_component", role: "user" },
  parts: [
    { type: "text", text: "分析附件" },
    { type: "file", mime: "application/pdf", filename: "spec.pdf", url: "file:///tmp/spec.pdf" },
  ],
})
let nonTextRejected = false
try {
  const thirdInput = {
    sessionID: "ses_component",
    agent: "aitest-director",
    model: { providerID: "fixture", id: "fixture-model", limit: { context: 128000, input: 64000, output: 32768 } },
    message: { id: "usr3" },
  }
  await hooks["experimental.chat.messages.transform"]({}, { messages })
  await hooks["experimental.chat.system.transform"](
    { sessionID: "ses_component", model: thirdInput.model },
    { system },
  )
  await hooks["chat.params"](thirdInput, { maxOutputTokens: 8192, options: {} })
  await hooks["chat.headers"](thirdInput, { headers: {} })
} catch (error) {
  nonTextRejected = String(error).includes("PRIMARY_CONTEXT_REPLAY_NON_TEXT_UNSUPPORTED")
}
assert.equal(nonTextRejected, true, "non-text Primary turn must fail closed before lossy successor replay")
assert.equal(captured.length, 3)
assert.equal(captured[2].current_user_replay_safe, false)
assert.deepEqual(captured[2].current_user_part_types, ["text", "file"])

console.log(JSON.stringify({
  status: "PASS",
  classification: "OPENCODE_1_18_3_PLUGIN_HOOK_COMPONENT_NO_REAL_MODEL",
  captured_requests: captured.length,
  final_reference_mutation_visible: true,
  denied_tool_excluded: true,
  blocked_old_provider_path: true,
  non_text_primary_replay_fails_closed: true,
}))
