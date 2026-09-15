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

function currentUserTurn(messages, messageID) {
  // Recovery is a side-effecting action. Never guess the current user turn by
  // falling back to "latest user message"; a missing exact message identity
  // must fail closed rather than replaying a previous instruction.
  if (typeof messageID !== "string" || !messageID) {
    return { text: "", replaySafe: false, partTypes: [], identityExact: false, messageID: null }
  }
  const row = messages.find((item) => item?.info?.id === messageID && item?.info?.role === "user")
  if (!row || !Array.isArray(row.parts)) {
    return { text: "", replaySafe: false, partTypes: [], identityExact: false, messageID: null }
  }
  const partTypes = row.parts.map((part) => String(part?.type || "unknown"))
  const replaySafe = row.parts.every((part) => part?.type === "text")
  const text = row.parts
    .filter((part) => part?.type === "text" && part?.ignored !== true && typeof part.text === "string")
    .map((part) => part.text)
    .join("\n")
  return { text, replaySafe, partTypes, identityExact: true, messageID: row.info.id }
}

function patternsFromPermission(permission) {
  if (!permission || typeof permission !== "object") return []
  return Object.entries(permission)
    .filter(([, action]) => action === "allow" || action === "ask")
    .map(([pattern]) => pattern)
}

async function agentPermissionPatterns(directory, agent) {
  const file = Bun.file(path.join(directory, ".opencode", "agents", agent + ".md"))
  if (!(await file.exists())) return ["*"]
  const text = await file.text()
  const lines = text.split(/\r?\n/)
  const localPatterns = []
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
    if (match[2] !== "deny") localPatterns.push(pattern)
  }
  // A project-owned deny-all AITest Agent is an explicit closed-world
  // boundary. Global allows are defaults for agents that do not override them;
  // they must not widen this Agent's model-visible tool set or its budget.
  if (denyAll) return [...new Set(localPatterns)]
  // Without a local deny-all boundary, conservative accounting budgets every
  // captured tool rather than trying to reproduce OpenCode's permission merge.
  return ["*"]
}

function matches(pattern, value) {
  if (pattern === "*") return true
  const escaped = pattern.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*")
  return new RegExp("^" + escaped + "$").test(value)
}


const effectSchemaCache = new WeakMap()
let effectModulePromise

function isRecord(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function nonFiniteNumber(value) {
  return value === "NaN" || value === "Infinity" || value === "-Infinity"
}

function emptyStructUnion(items) {
  return items.length === 2
    && items.some((item) => isRecord(item) && item.type === "object" && item.properties === undefined)
    && items.some((item) => isRecord(item) && item.type === "array" && item.items === undefined)
}

function flattenableAllOf(allOf, parent) {
  const keys = new Set(Object.keys(parent).filter((key) => key !== "allOf"))
  return allOf.every((item) => Object.keys(item).every((key) => {
    if (keys.has(key)) return false
    keys.add(key)
    return true
  }))
}

function normalizeEffectJsonSchema(value, options = {}) {
  if (Array.isArray(value)) return value.map((item) => normalizeEffectJsonSchema(item))
  if (!isRecord(value)) return value
  const required = Array.isArray(value.required)
    ? new Set(value.required.filter((item) => typeof item === "string"))
    : undefined
  const schema = Object.fromEntries(Object.entries(value).map(([key, item]) => [
    key,
    key === "properties" && isRecord(item)
      ? Object.fromEntries(Object.entries(item).map(([name, property]) => [
          name,
          normalizeEffectJsonSchema(property, { stripNull: !required?.has(name) }),
        ]))
      : normalizeEffectJsonSchema(item),
  ]))
  if (schema.additionalProperties === true) delete schema.additionalProperties
  if (options.stripNull && Array.isArray(schema.anyOf)) {
    const withoutNull = schema.anyOf.filter((item) => !isRecord(item) || item.type !== "null")
    if (withoutNull.length !== schema.anyOf.length) {
      return normalizeEffectJsonSchema({ ...schema, anyOf: withoutNull })
    }
  }
  if (Array.isArray(schema.anyOf)) {
    const number = schema.anyOf.find((item) => isRecord(item) && item.type === "number")
    const nonFinite = schema.anyOf.filter(
      (item) => isRecord(item) && Array.isArray(item.enum) && item.enum.every(nonFiniteNumber),
    )
    if (number && nonFinite.length === schema.anyOf.length - 1) {
      const { anyOf: _ignored, ...rest } = schema
      return normalizeEffectJsonSchema({ ...number, ...rest })
    }
    if (emptyStructUnion(schema.anyOf)) {
      const { anyOf: _ignored, ...rest } = schema
      return normalizeEffectJsonSchema({ type: "object", properties: {}, ...rest })
    }
    if (schema.anyOf.length === 1 && isRecord(schema.anyOf[0])) {
      const { anyOf: _ignored, ...rest } = schema
      return normalizeEffectJsonSchema({ ...schema.anyOf[0], ...rest })
    }
  }
  if (Array.isArray(schema.allOf) && schema.allOf.every(isRecord) && flattenableAllOf(schema.allOf, schema)) {
    const { allOf, ...rest } = schema
    return normalizeEffectJsonSchema({ ...Object.assign({}, ...allOf), ...rest })
  }
  if (schema.type === "integer" && schema.maximum === undefined) {
    return { minimum: Number.MIN_SAFE_INTEGER, ...schema, maximum: Number.MAX_SAFE_INTEGER }
  }
  return schema
}

function inlineLocalReferences(value, definitions, seen = new Set()) {
  if (Array.isArray(value)) return value.map((item) => inlineLocalReferences(item, definitions, seen))
  if (!isRecord(value)) return value
  const localDefinitions = definitions ?? (isRecord(value.$defs) ? value.$defs : undefined)
  if (typeof value.$ref === "string" && localDefinitions) {
    const name = value.$ref.match(/^#\/\$defs\/(.+)$/)?.[1] ?? value.$ref.match(/^#\/definitions\/(.+)$/)?.[1]
    if (name && !seen.has(name)) {
      const target = localDefinitions[name]
      if (target) {
        const { $ref: _ignored, ...rest } = value
        return inlineLocalReferences(
          { ...(isRecord(target) ? target : {}), ...rest },
          localDefinitions,
          new Set(seen).add(name),
        )
      }
    }
  }
  return Object.fromEntries(
    Object.entries(value).map(([key, item]) => [key, inlineLocalReferences(item, localDefinitions, seen)]),
  )
}

function hasLocalReference(value) {
  if (Array.isArray(value)) return value.some(hasLocalReference)
  if (!isRecord(value)) return false
  if (typeof value.$ref === "string"
      && (value.$ref.startsWith("#/$defs/") || value.$ref.startsWith("#/definitions/"))) return true
  return Object.values(value).some(hasLocalReference)
}

function dropResolvedDefinitions(value) {
  if (!isRecord(value) || hasLocalReference(value)) return value
  const { $defs: _defs, definitions: _definitions, ...rest } = value
  return rest
}

async function compactToolSchema(ref) {
  if (ref?.jsonSchema !== undefined && ref?.jsonSchema !== null) return ref.jsonSchema
  const parameters = ref?.parameters
  if (!parameters || (typeof parameters !== "object" && typeof parameters !== "function")) return {}
  if (effectSchemaCache.has(parameters)) return effectSchemaCache.get(parameters)
  try {
    effectModulePromise ||= import("effect")
    const { Schema, JsonSchema } = await effectModulePromise
    const document = Schema.toJsonSchemaDocument(parameters, { additionalProperties: true })
    const normalized = normalizeEffectJsonSchema({
      $schema: JsonSchema.META_SCHEMA_URI_DRAFT_2020_12,
      ...document.schema,
      ...(Object.keys(document.definitions || {}).length > 0 ? { $defs: document.definitions } : {}),
    })
    const compact = dropResolvedDefinitions(inlineLocalReferences(normalized))
    effectSchemaCache.set(parameters, compact)
    return compact
  } catch {
    // If the host exposes an unknown schema representation or Effect is not
    // resolvable, preserve the old fail-conservative raw-object accounting.
    return parameters
  }
}

function admissionBudgetSummary(decision, toolStats) {
  const components = decision?.components && typeof decision.components === "object" ? decision.components : {}
  const numeric = (value) => Number.isFinite(Number(value)) ? Number(value) : -1
  const system = numeric(components.system_bytes)
  const messages = numeric(components.messages_bytes)
  const tools = numeric(components.tools_bytes)
  const extra = numeric(components.extra_bytes)
  const upper = numeric(decision?.request_upper_bound)
  const framing = upper >= 0 && [system, messages, tools, extra].every((value) => value >= 0)
    ? upper - system - messages - tools - extra
    : -1
  return [
    "ctx=" + numeric(decision?.context_limit),
    "input_budget=" + numeric(decision?.input_budget),
    "upper=" + upper,
    "system=" + system,
    "messages=" + messages,
    "tools=" + tools,
    "extra=" + extra,
    "framing=" + framing,
    "output_reserve=" + numeric(decision?.output_reserve),
    "message_count=" + numeric(decision?.message_count),
    "tool_count=" + numeric(decision?.tool_count),
    "tools_latest=" + numeric(toolStats?.latestBytes),
    "tools_min=" + numeric(toolStats?.minBytes),
  ].join(",")
}

async function toolBytes(patterns) {
  let total = 0
  let latestBytes = 0
  let minBytes = 0
  let count = 0
  for (const [toolID, refs] of toolRefs.entries()) {
    if (!patterns.some((pattern) => matches(pattern, toolID))) continue
    const sizes = []
    for (const ref of refs) {
      const schema = await compactToolSchema(ref)
      sizes.push(utf8(safeJson({
        name: toolID,
        description: ref.description ?? "",
        schema,
      })))
    }
    if (sizes.length === 0) continue
    // Covers the provider's function wrapper and bounded provider-specific
    // schema transforms. The converted schema is the same representation
    // OpenCode derives before ProviderTransform.schema().
    const wrapperAndTransformReserve = 512
    total += Math.max(...sizes) + wrapperAndTransformReserve
    latestBytes += sizes[sizes.length - 1] + wrapperAndTransformReserve
    minBytes += Math.min(...sizes) + wrapperAndTransformReserve
    count += 1
  }
  return { bytes: total, latestBytes, minBytes, count }
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
    const tools = await toolBytes(patterns)
    const current = currentUserTurn(messages, input.message?.id ?? state.messageID)
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
      current_user_text: current.text,
      current_user_message_id: current.messageID,
      current_user_replay_safe: current.replaySafe,
      current_user_identity_exact: current.identityExact,
      current_user_part_types: current.partTypes,
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
      // Numbers only: preserve a bounded forensic budget receipt without
      // leaking prompt/system/tool contents or credentials into Host errors.
      throw new Error(
        "AITEST_CONTEXT_ADMISSION_BLOCKED:" + recovery
        + ";BUDGET[" + admissionBudgetSummary(decision, tools) + "]"
      )
    }
  },
})

export default AITestContextGovernor
