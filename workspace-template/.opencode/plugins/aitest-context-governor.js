// AITest pre-provider Context Governor for OpenCode 1.18.3.
//
// This plugin does not own Mission/Session truth. It observes the model-visible
// request components at OpenCode's pre-provider hook sequence and delegates the
// budget/recovery decision to the Python Runtime. Throwing from chat.params
// prevents LLMRequestPrep.prepare from reaching native-runtime/streamText.

import path from "path"

const sessions = new Map()
const toolRefs = new Map()
let mergedPermission = {}

const utf8 = (value) => new TextEncoder().encode(value).length

function safeJson(value) {
  try {
    const result = JSON.stringify(value)
    if (typeof result !== "string") throw new Error("not serializable")
    return result
  } catch {
    // Context accounting must never turn an unserializable structure into a
    // smaller byte count. Fail closed before provider transport instead.
    throw new Error("AITEST_CONTEXT_GOVERNOR_UNSERIALIZABLE_REQUEST")
  }
}

function sessionID(messages) {
  for (let i = messages.length - 1; i >= 0; i--) {
    const value = messages[i]?.info?.sessionID
    if (typeof value === "string" && value) return value
  }
}

function currentUserText(messages, messageID) {
  const exact = messages.find((row) => row?.info?.id === messageID && row?.info?.role === "user")
  const row = exact ?? [...messages].reverse().find((item) => item?.info?.role === "user")
  if (!row || !Array.isArray(row.parts)) return ""
  return row.parts.filter((part) => part?.type === "text" && typeof part.text === "string")
    .map((part) => part.text).join("\n")
}

function patternsFromPermission(permission) {
  if (!permission || typeof permission !== "object") return []
  return Object.entries(permission)
    .filter(([, action]) => action === "allow" || action === "ask")
    .map(([pattern]) => pattern)
}

async function agentPermissionPatterns(directory, agent) {
  const inherited = [...patternsFromPermission(mergedPermission)]
  const file = Bun.file(path.join(directory, ".opencode", "agents", agent + ".md"))
  if (!(await file.exists())) return ["*"]
  const text = await file.text()
  const lines = text.split(/\r?\n/)
  const patterns = [...inherited]
  let inside = false
  let denyAll = false
  for (const line of lines) {
    if (!inside) {
      if (/^permission:\s*$/.test(line)) inside = true
      continue
    }
    if (/^---\s*$/.test(line) || (/^\S/.test(line) && !/^permission:/.test(line))) break
    const match = line.match(/^\s{2,}["']?([^"'\s][^:"']*?)["']?\s*:\s*(allow|ask|deny)\s*$/)
    if (!match) continue
    const pattern = match[1].trim()
    if (pattern === "*" && match[2] === "deny") denyAll = true
    if (match[2] !== "deny") patterns.push(pattern)
  }
  // Only a project-owned deny-all AITest Agent gives us a closed-world tool
  // set. Any looser/unknown permission shape is budgeted as all captured tools.
  return denyAll ? [...new Set(patterns)] : ["*"]
}

function matches(pattern, value) {
  if (pattern === "*") return true
  const escaped = pattern.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*")
  return new RegExp("^" + escaped + "$").test(value)
}

function toolBytes(patterns) {
  let total = 0
  let count = 0
  for (const [toolID, refs] of toolRefs.entries()) {
    if (!patterns.some((pattern) => matches(pattern, toolID))) continue
    let maximum = 0
    for (const ref of refs) {
      const serialized = safeJson({
        name: toolID,
        description: ref.description ?? "",
        schema: ref.jsonSchema ?? ref.parameters ?? {},
      })
      maximum = Math.max(maximum, utf8(serialized))
    }
    // A tiny per-tool structural reserve covers the final name/function wrapper.
    total += maximum + 128
    count += 1
  }
  return { bytes: total, count }
}

async function portablePython(directory) {
  const root = path.resolve(process.env.AITEST_WORKSPACE_ROOT || directory)
  const executable = path.join(root, "runtime", "python", process.platform === "win32" ? "python.exe" : "python")
  if (!(await Bun.file(executable).exists())) {
    throw new Error("AITEST_CONTEXT_GOVERNOR_PORTABLE_PYTHON_REQUIRED")
  }
  return { root, executable }
}

async function admit(directory, payload) {
  const { root, executable } = await portablePython(directory)
  const runtime = path.join(root, "ai-test", "runtime")
  const env = {
    ...process.env,
    AITEST_WORKSPACE_ROOT: root,
    PYTHONPATH: [runtime, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
    PYTHONUTF8: "1",
    PYTHONNOUSERSITE: "1",
  }
  const proc = Bun.spawn(
    [executable, "-X", "utf8", "-m", "aitest_runtime.context_admission"],
    { cwd: root, env, stdin: "pipe", stdout: "pipe", stderr: "pipe" },
  )
  proc.stdin.write(JSON.stringify(payload))
  proc.stdin.end()
  const stdout = await new Response(proc.stdout).text()
  const stderr = await new Response(proc.stderr).text()
  const code = await proc.exited
  let result
  try { result = JSON.parse(stdout) } catch {
    throw new Error("AITEST_CONTEXT_GOVERNOR_RESULT_NOT_JSON")
  }
  if (code !== 0 || result.status === "ERROR") {
    const reason = String(result.error || stderr || "RUNTIME_ERROR").slice(0, 200)
    throw new Error("AITEST_CONTEXT_GOVERNOR_ERROR:" + reason)
  }
  return result
}

export const AITestContextGovernor = async ({ directory }) => ({
  config(cfg) {
    mergedPermission = cfg?.permission && typeof cfg.permission === "object" ? cfg.permission : {}
  },

  "experimental.chat.messages.transform": async (_input, output) => {
    const sid = sessionID(output.messages || [])
    if (!sid) return
    if (!sessions.has(sid) && sessions.size >= 512) sessions.delete(sessions.keys().next().value)
    const state = sessions.get(sid) || {}
    // Retain the reference. Later plugins mutate this same output before the
    // separate chat.params trigger, so serialization there sees final history.
    state.messages = output.messages
    sessions.set(sid, state)
  },

  "experimental.chat.system.transform": async (input, output) => {
    if (!input.sessionID) return
    const state = sessions.get(input.sessionID) || {}
    state.system = output.system
    state.contextLimit = input.model?.limit?.context
    sessions.set(input.sessionID, state)
  },

  "tool.definition": async (input, output) => {
    const refs = toolRefs.get(input.toolID) || []
    refs.push(output)
    if (refs.length > 8) refs.splice(0, refs.length - 8)
    toolRefs.set(input.toolID, refs)
  },

  "chat.params": async (input, output) => {
    if (!input.agent?.startsWith("aitest-")) return
    if (!sessions.has(input.sessionID) && sessions.size >= 512) sessions.delete(sessions.keys().next().value)
    const state = sessions.get(input.sessionID) || {}
    // Keep the live params reference. OpenCode awaits the entire chat.params
    // plugin chain before starting chat.headers, so the next hook observes the
    // final params after any later plugin mutation.
    state.params = output
    state.agent = input.agent
    state.model = input.model
    state.messageID = input.message?.id
    sessions.set(input.sessionID, state)
  },

  "chat.headers": async (input, _output) => {
    if (!input.agent?.startsWith("aitest-")) return
    const state = sessions.get(input.sessionID) || {}
    const messages = state.messages || []
    const system = state.system || []
    const contextLimit = Number(input.model?.limit?.context ?? state.contextLimit)
    if (!Number.isInteger(contextLimit) || contextLimit <= 0) {
      throw new Error("AITEST_CONTEXT_GOVERNOR_MODEL_LIMIT_UNKNOWN")
    }
    const patterns = await agentPermissionPatterns(directory, input.agent)
    const tools = toolBytes(patterns)
    const current = currentUserText(messages, input.message?.id ?? state.messageID)
    const params = state.params || {}
    const configuredOutput = Number(params.maxOutputTokens)
    const advertisedOutput = Number(input.model?.limit?.output)
    const advertisedInput = Number(input.model?.limit?.input)
    // chat.headers runs after the entire chat.params plugin chain in OpenCode
    // 1.18.3, so params.maxOutputTokens is the effective provider request
    // value. The model limit is only a fail-closed fallback when params omit it.
    const outputReserve =
      Number.isInteger(configuredOutput) && configuredOutput > 0
        ? configuredOutput
        : (Number.isInteger(advertisedOutput) && advertisedOutput > 0 ? advertisedOutput : 0)
    const inputLimit = Number.isInteger(advertisedInput) && advertisedInput > 0 ? advertisedInput : null
    const payload = {
      session_id: input.sessionID,
      agent: input.agent,
      provider_id: input.model?.providerID,
      model_id: input.model?.id,
      context_limit: contextLimit,
      input_limit: inputLimit,
      max_output_tokens: outputReserve || null,
      system_bytes: utf8(safeJson(system)),
      messages_bytes: utf8(safeJson(messages)),
      tools_bytes: tools.bytes,
      extra_bytes: 1024 + utf8(safeJson(params.options || {})),
      message_count: messages.length,
      tool_count: tools.count,
      current_user_text: current,
    }
    let decision
    try {
      decision = await admit(directory, payload)
    } finally {
      // messages/system/params are only a transient pre-provider snapshot.
      // Keeping them after admission would pin large histories in the OpenCode
      // process and could itself create the memory pressure we are preventing.
      sessions.delete(input.sessionID)
    }
    if (decision.status === "BLOCK") {
      // Recovery has already been durably initiated/completed by Runtime. The
      // old Session must not reach provider transport.
      const recovery = decision.recovery?.status || "RECOVERY_UNKNOWN"
      throw new Error("AITEST_CONTEXT_ADMISSION_BLOCKED:" + recovery)
    }
  },
})

export default AITestContextGovernor
