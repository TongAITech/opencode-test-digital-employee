#!/usr/bin/env node

/**
 * Dependency-free bank live gate for Yuxi -> OpenCode -> bank LLM.
 * Node 20+ only; uses built-in fetch and Web Streams.
 *
 * This mirrors the production Python adapter protocol closely enough to decide
 * whether the exact bank model can serve as Yuxi's model backend through the
 * OpenCode Session API. It never executes a Yuxi tool and disables every
 * OpenCode-owned tool on every model request.
 */

import process from "node:process"
import { Buffer } from "node:buffer"

const PLAIN_MARKER = "YUXI_OC_PLAIN_7F3A"
const SYSTEM_MARKER = "YUXI_OC_SYSTEM_91C2"
const STREAM_MARKER = "YUXI_OC_STREAM_4D8E"
const PROBE_TOOL = "yuxi_probe_add"
const SESSION_PREFIX = "yuxi-model-gateway"

const GATEWAY_SYSTEM = `You are the model behind a stateless inference gateway.
The caller (Yuxi/LangGraph), not OpenCode, owns conversation state and tool execution.
Never call OpenCode tools, never modify the workspace, never create subagents, and never treat this scratch session as durable state.
The user payload contains a serialized conversation. Continue that conversation by producing the next assistant turn only.`

const TOOL_PROTOCOL = `Yuxi has bound external tools, but those tools are NOT OpenCode tools.
Choose either a final answer or one or more Yuxi tool calls and output EXACTLY one JSON object with no Markdown fence and no prose outside it.
Allowed envelopes:
1. {"kind":"final","content":"assistant text"}
2. {"kind":"tool_calls","tool_calls":[{"id":"non-empty unique id","name":"tool name","args":{}}]}
Only call a tool whose name appears in YUXI_TOOL_SCHEMAS. Arguments must match its JSON schema. Do not invent tool names.`

function parseArgs(argv) {
  const out = {
    baseUrl: process.env.OPENCODE_SERVER_URL || "http://127.0.0.1:4096",
    providerId: null,
    modelId: null,
    agent: "yuxi-model-provider-proxy",
    directory: null,
    timeoutMs: 120000,
    basicUser: process.env.OPENCODE_SERVER_USERNAME || "opencode",
  }
  for (let i = 0; i < argv.length; i += 1) {
    const key = argv[i]
    const value = argv[i + 1]
    switch (key) {
      case "--base-url": out.baseUrl = value; i += 1; break
      case "--provider-id": out.providerId = value; i += 1; break
      case "--model-id": out.modelId = value; i += 1; break
      case "--agent": out.agent = value; i += 1; break
      case "--directory": out.directory = value; i += 1; break
      case "--timeout-ms": out.timeoutMs = Number(value); i += 1; break
      default: throw new Error(`Unknown argument: ${key}`)
    }
  }
  if (!Number.isFinite(out.timeoutMs) || out.timeoutMs <= 0) throw new Error("--timeout-ms must be positive")
  out.baseUrl = out.baseUrl.replace(/\/+$/, "")
  return out
}

function safeError(error) {
  return String(error?.message || error || "unknown error").replace(/[\r\n]+/g, " ").slice(0, 500)
}

function authHeaders(args) {
  const headers = {}
  const password = process.env.OPENCODE_SERVER_PASSWORD
  if (password) {
    const token = Buffer.from(`${args.basicUser}:${password}`, "utf8").toString("base64")
    headers.Authorization = `Basic ${token}`
  }
  if (args.directory) headers["x-opencode-directory"] = args.directory
  return headers
}

async function request(args, path, options = {}) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(new Error(`timeout calling ${path}`)), args.timeoutMs)
  try {
    const headers = { ...authHeaders(args), ...(options.headers || {}) }
    if (options.body !== undefined) headers["content-type"] = "application/json"
    return await fetch(`${args.baseUrl}${path}`, {
      ...options,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      headers,
      signal: controller.signal,
    })
  } finally {
    clearTimeout(timer)
  }
}

async function jsonRequest(args, path, options = {}) {
  const response = await request(args, path, options)
  if (!response.ok) throw new Error(`${options.method || "GET"} ${path} -> HTTP ${response.status}`)
  if (response.status === 204) return null
  const text = await response.text()
  return text ? JSON.parse(text) : null
}

function providerInventory(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return { providers: [], connected: [], defaults: null }
  const rawProviders = Array.isArray(payload.all) ? payload.all : (Array.isArray(payload.providers) ? payload.providers : [])
  const connected = Array.isArray(payload.connected) ? payload.connected.filter((x) => typeof x === "string") : []
  const providers = []
  for (const provider of rawProviders) {
    if (!provider || typeof provider !== "object") continue
    const providerId = provider.id || provider.providerID || provider.provider_id
    if (typeof providerId !== "string" || !providerId) continue
    const modelIds = []
    const models = provider.models
    if (models && typeof models === "object" && !Array.isArray(models)) {
      modelIds.push(...Object.keys(models))
    } else if (Array.isArray(models)) {
      for (const model of models) {
        if (typeof model === "string") modelIds.push(model)
        else if (model && typeof model === "object") {
          const id = model.id || model.modelID || model.model_id
          if (typeof id === "string" && id) modelIds.push(id)
        }
      }
    }
    providers.push({
      provider_id: providerId,
      name: typeof provider.name === "string" ? provider.name : null,
      connected: connected.includes(providerId),
      model_ids: [...new Set(modelIds)].sort(),
    })
  }
  return { providers, connected: [...new Set(connected)].sort(), defaults: payload.default ?? null }
}

function defaultModelFor(defaults, providerId) {
  if (!defaults || typeof defaults !== "object" || Array.isArray(defaults)) return null
  const direct = defaults[providerId]
  if (typeof direct === "string" && direct) return direct.includes("/") && direct.startsWith(`${providerId}/`) ? direct.slice(providerId.length + 1) : direct
  return null
}

function chooseModel(inventory, requestedProvider, requestedModel) {
  let providerId = requestedProvider?.trim() || null
  let modelId = requestedModel?.trim() || null
  const byId = new Map(inventory.providers.map((p) => [p.provider_id, p]))

  if (providerId && modelId) return { provider_id: providerId, model_id: modelId, reason: "explicit" }
  if (!providerId) {
    const connected = inventory.providers.filter((p) => inventory.connected.includes(p.provider_id))
    if (connected.length === 1) providerId = connected[0].provider_id
    else if (inventory.providers.length === 1) providerId = inventory.providers[0].provider_id
    else return { provider_id: null, model_id: modelId, reason: "provider-selection-required" }
  }
  const provider = byId.get(providerId)
  if (!provider) return { provider_id: providerId, model_id: modelId, reason: "provider-not-present-in-inventory" }
  if (modelId) return { provider_id: providerId, model_id: modelId, reason: "explicit-model" }

  const configuredDefault = defaultModelFor(inventory.defaults, providerId)
  if (configuredDefault) return { provider_id: providerId, model_id: configuredDefault, reason: "opencode-default-model" }
  if (provider.model_ids.length === 1) return { provider_id: providerId, model_id: provider.model_ids[0], reason: "single-model-auto-selected" }
  return { provider_id: providerId, model_id: null, reason: "model-selection-required" }
}

function agentNames(payload) {
  if (!Array.isArray(payload)) return []
  return [...new Set(payload.map((x) => x && typeof x === "object" ? (x.name || x.id) : null).filter((x) => typeof x === "string" && x))].sort()
}

function sessionSnapshot(payload) {
  const map = new Map()
  if (!Array.isArray(payload)) return map
  for (const item of payload) {
    if (!item || typeof item !== "object" || typeof item.id !== "string") continue
    map.set(item.id, typeof item.title === "string" ? item.title : "")
  }
  return map
}

async function createSession(args, title) {
  const payload = await jsonRequest(args, "/session", { method: "POST", body: { title } })
  if (!payload || typeof payload.id !== "string" || !payload.id) throw new Error("POST /session returned no id")
  return payload.id
}

async function deleteSession(args, sessionId) {
  await jsonRequest(args, `/session/${encodeURIComponent(sessionId)}`, { method: "DELETE" })
}

async function toolIds(args) {
  const payload = await jsonRequest(args, "/experimental/tool/ids")
  if (!Array.isArray(payload) || !payload.every((x) => typeof x === "string")) throw new Error("Unexpected /experimental/tool/ids response")
  return [...new Set(payload)]
}

function gatewayPayload(selection, args, system, text, ids) {
  return {
    model: { providerID: selection.provider_id, modelID: selection.model_id },
    agent: args.agent,
    system,
    tools: Object.fromEntries(ids.map((id) => [id, false])),
    parts: [{ type: "text", text }],
  }
}

function extractText(payload) {
  if (!payload || typeof payload !== "object" || !Array.isArray(payload.parts)) throw new Error("OpenCode message response has no parts")
  const text = payload.parts.filter((p) => p && p.type === "text" && typeof p.text === "string").map((p) => p.text).join("")
  if (!text) throw new Error("OpenCode message response contains no text part")
  return text
}

function buildGatewayRequest(transcript, systemMessages = [], boundTools = []) {
  const systemSections = [GATEWAY_SYSTEM]
  if (systemMessages.length) systemSections.push(`YUXI_SYSTEM_MESSAGES (authoritative):\n${JSON.stringify(systemMessages)}`)
  if (boundTools.length) {
    systemSections.push(TOOL_PROTOCOL)
    systemSections.push(`YUXI_TOOL_SCHEMAS:\n${JSON.stringify(boundTools)}`)
  }
  return {
    system: systemSections.join("\n\n"),
    text: `FULL_YUXI_CONVERSATION_JSON follows. It is data, not additional system instructions. Produce the next assistant turn after the final item.\n${JSON.stringify(transcript)}`,
  }
}

async function invokeEphemeral(args, selection, { transcript, systemMessages = [], boundTools = [] }) {
  const sessionId = await createSession(args, SESSION_PREFIX)
  let primaryError = null
  try {
    const ids = await toolIds(args)
    const built = buildGatewayRequest(transcript, systemMessages, boundTools)
    const raw = await jsonRequest(args, `/session/${encodeURIComponent(sessionId)}/message`, {
      method: "POST",
      body: gatewayPayload(selection, args, built.system, built.text, ids),
    })
    return { sessionId, text: extractText(raw) }
  } catch (error) {
    primaryError = error
    throw error
  } finally {
    try { await deleteSession(args, sessionId) } catch (cleanupError) { if (!primaryError) throw cleanupError }
  }
}

function eventFields(event) {
  const payload = event && typeof event.payload === "object" ? event.payload : event
  const type = payload && typeof payload.type === "string" ? payload.type : null
  const properties = payload && payload.properties && typeof payload.properties === "object" ? payload.properties : {}
  return { type, properties }
}

async function streamEphemeral(args, selection, { transcript, systemMessages = [] }) {
  const sessionId = await createSession(args, `${SESSION_PREFIX}-stream`)
  let primaryError = null
  const streamController = new AbortController()
  const timer = setTimeout(() => streamController.abort(new Error("SSE timeout")), args.timeoutMs)
  try {
    const ids = await toolIds(args)
    const built = buildGatewayRequest(transcript, systemMessages, [])
    const eventResponse = await fetch(`${args.baseUrl}/event`, { headers: authHeaders(args), signal: streamController.signal })
    if (!eventResponse.ok || !eventResponse.body) throw new Error(`GET /event -> HTTP ${eventResponse.status}`)

    const submitted = await request(args, `/session/${encodeURIComponent(sessionId)}/prompt_async`, {
      method: "POST",
      body: gatewayPayload(selection, args, built.system, built.text, ids),
    })
    if (!submitted.ok) throw new Error(`POST prompt_async -> HTTP ${submitted.status}`)

    const reader = eventResponse.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ""
    const deltas = []
    let doneForSession = false
    while (!doneForSession) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n")
      let boundary
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        const data = block.split("\n").filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart()).join("\n")
        if (!data) continue
        let event
        try { event = JSON.parse(data) } catch { throw new Error("Invalid JSON in OpenCode SSE") }
        const { type, properties } = eventFields(event)
        if (properties.sessionID !== sessionId) continue
        if (type === "message.part.delta" && properties.field === "text" && typeof properties.delta === "string") deltas.push(properties.delta)
        if (type === "session.error") throw new Error(`OpenCode session.error: ${JSON.stringify(properties.error || {})}`)
        if (type === "session.idle") { doneForSession = true; break }
      }
    }
    if (!doneForSession) throw new Error("SSE ended before session.idle")
    return deltas
  } catch (error) {
    primaryError = error
    throw error
  } finally {
    clearTimeout(timer)
    streamController.abort()
    try { await deleteSession(args, sessionId) } catch (cleanupError) { if (!primaryError) throw cleanupError }
  }
}

function parseToolEnvelope(text, allowedNames) {
  const candidate = text.trim()
  if (candidate.startsWith("```")) throw new Error("Tool envelope is Markdown-wrapped")
  let payload
  try { payload = JSON.parse(candidate) } catch { throw new Error("Tool envelope is not valid JSON") }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) throw new Error("Tool envelope is not an object")
  if (payload.kind === "final") {
    if (typeof payload.content !== "string") throw new Error("Final envelope has no string content")
    return { kind: "final", content: payload.content, tool_calls: [] }
  }
  if (payload.kind !== "tool_calls" || !Array.isArray(payload.tool_calls) || payload.tool_calls.length === 0) throw new Error("Invalid tool_calls envelope")
  const seen = new Set()
  const calls = []
  for (const call of payload.tool_calls) {
    if (!call || typeof call !== "object") throw new Error("Tool call is not an object")
    if (typeof call.id !== "string" || !call.id || seen.has(call.id)) throw new Error("Tool call id missing/duplicate")
    if (typeof call.name !== "string" || !allowedNames.has(call.name)) throw new Error(`Unknown tool: ${call.name}`)
    if (!call.args || typeof call.args !== "object" || Array.isArray(call.args)) throw new Error("Tool args are not an object")
    seen.add(call.id)
    calls.push({ id: call.id, name: call.name, args: call.args })
  }
  return { kind: "tool_calls", content: "", tool_calls: calls }
}

async function run(args) {
  const report = {
    probe: "YUXI_OPENCODE_PROVIDER_NODE20_BANK_GATE",
    base_url: args.baseUrl,
    directory_configured: Boolean(args.directory),
    auth_configured: Boolean(process.env.OPENCODE_SERVER_PASSWORD),
    checks: {},
  }
  const checks = report.checks

  try {
    let healthStatus = "FAIL"
    let version = null
    try {
      const health = await jsonRequest(args, "/global/health")
      healthStatus = health && health.healthy === false ? "FAIL" : "PASS"
      version = typeof health?.version === "string" ? health.version : null
    } catch {
      await jsonRequest(args, "/session")
      healthStatus = "PASS"
    }
    checks.server_health = { status: healthStatus, version }

    const providerRaw = await jsonRequest(args, "/provider")
    const inventory = providerInventory(providerRaw)
    checks.provider_inventory = {
      status: inventory.providers.length ? "PASS" : "FAIL",
      connected_provider_ids: inventory.connected,
      providers: inventory.providers,
      default_present: inventory.defaults !== null,
    }

    const ids = await toolIds(args)
    checks.opencode_tool_enumeration = { status: "PASS", tool_count: ids.length }

    const agents = agentNames(await jsonRequest(args, "/agent"))
    checks.provider_proxy_agent = { status: agents.includes(args.agent) ? "PASS" : "FAIL", agent: args.agent, available: agents.includes(args.agent) }

    const before = sessionSnapshot(await jsonRequest(args, "/session"))
    const selection = chooseModel(inventory, args.providerId, args.modelId)
    report.selection = selection

    if (!selection.provider_id || !selection.model_id) {
      report.gate = "NEEDS_MODEL_SELECTION"
      report.next_action = "Re-run with --provider-id and --model-id from the secret-free inventory."
      return { code: 2, report }
    }
    if (Object.values(checks).some((item) => item.status === "FAIL")) {
      report.gate = "FAIL_PRECONDITION"
      return { code: 1, report }
    }

    const plain = await invokeEphemeral(args, selection, { transcript: [{ role: "user", content: `Reply with exactly this token: ${PLAIN_MARKER}` }] })
    checks.plain_chat = { status: plain.text.includes(PLAIN_MARKER) ? "PASS" : "FAIL", marker_seen: plain.text.includes(PLAIN_MARKER) }

    const system = await invokeEphemeral(args, selection, {
      systemMessages: [`Your response must contain the exact token ${SYSTEM_MARKER}.`],
      transcript: [{ role: "user", content: "Return the required token and nothing else." }],
    })
    checks.system_prompt = { status: system.text.includes(SYSTEM_MARKER) ? "PASS" : "FAIL", marker_seen: system.text.includes(SYSTEM_MARKER) }

    const stream = await streamEphemeral(args, selection, { transcript: [{ role: "user", content: `Reply with exactly this token: ${STREAM_MARKER}` }] })
    const streamText = stream.join("")
    checks.streaming = { status: stream.length && streamText.includes(STREAM_MARKER) ? "PASS" : "FAIL", marker_seen: streamText.includes(STREAM_MARKER), chunk_count: stream.length }

    const toolSchema = {
      type: "function",
      function: {
        name: PROBE_TOOL,
        description: "Add two integers. Use this tool when explicitly instructed by the probe.",
        parameters: {
          type: "object",
          properties: { a: { type: "integer" }, b: { type: "integer" } },
          required: ["a", "b"],
          additionalProperties: false,
        },
      },
    }
    const toolUser = { role: "user", content: `Use the ${PROBE_TOOL} tool with a=2 and b=3. Do not calculate it yourself; select the tool.` }
    const rawTool = await invokeEphemeral(args, selection, { transcript: [toolUser], boundTools: [toolSchema] })
    const parsedTool = parseToolEnvelope(rawTool.text, new Set([PROBE_TOOL]))
    const matching = parsedTool.tool_calls.filter((call) => call.name === PROBE_TOOL)
    const callOk = parsedTool.kind === "tool_calls" && matching.length === 1 && matching[0].args.a === 2 && matching[0].args.b === 3
    checks.yuxi_tool_selection = { status: callOk ? "PASS" : "FAIL", tool_call_count: parsedTool.tool_calls.length, expected_tool_seen: matching.length > 0 }

    let continuationOk = false
    if (callOk) {
      const call = matching[0]
      const rawFinal = await invokeEphemeral(args, selection, {
        boundTools: [toolSchema],
        transcript: [
          toolUser,
          { role: "assistant", content: "", tool_calls: [call] },
          { role: "tool", tool_call_id: call.id, name: PROBE_TOOL, content: "5" },
        ],
      })
      const parsedFinal = parseToolEnvelope(rawFinal.text, new Set([PROBE_TOOL]))
      continuationOk = parsedFinal.kind === "final" && parsedFinal.content.includes("5")
    }
    checks.yuxi_tool_result_continuation = { status: continuationOk ? "PASS" : "FAIL", final_answer_mentions_expected_result: continuationOk }

    const after = sessionSnapshot(await jsonRequest(args, "/session"))
    const leftovers = []
    for (const [id, title] of after.entries()) {
      if (!before.has(id) && title.startsWith(SESSION_PREFIX)) leftovers.push(id)
    }
    checks.ephemeral_session_cleanup = { status: leftovers.length ? "FAIL" : "PASS", leftover_probe_session_count: leftovers.length }

    const failures = Object.entries(checks).filter(([, item]) => item.status === "FAIL").map(([name]) => name)
    report.gate = failures.length ? "FAIL" : "PASS"
    if (failures.length) report.failed_checks = failures
    return { code: failures.length ? 1 : 0, report }
  } catch (error) {
    report.gate = "ERROR"
    report.error_type = error?.constructor?.name || "Error"
    report.error = safeError(error)
    return { code: 1, report }
  }
}

let args
try {
  args = parseArgs(process.argv.slice(2))
} catch (error) {
  console.error(JSON.stringify({ gate: "ARGUMENT_ERROR", error: safeError(error) }, null, 2))
  process.exit(2)
}

const { code, report } = await run(args)
console.log(JSON.stringify(report, null, 2))
process.exit(code)
