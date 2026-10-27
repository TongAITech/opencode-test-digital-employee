// RC7.1 Field Runtime tool policy.
//
// INTERACTIVE_CONTROL is a coordinator/field-validation session. Its authority
// is the exact live DSH tool registry for the current agent. It never grants
// wildcard names and it does not manufacture Worker lease authority.
//
// LEASE_BOUND_WORKER remains fail-closed and uses only the exact signed-lease
// tool list projected by Rc7AuthorizedDshHeadlessWorkerLauncher. A complete
// Worker projection always wins over an inherited interactive session mode, so
// Field access cannot leak into AgentTeams/headless Workers.
export const name = 'rc7-tool-policy'

const SESSION_MODE_ENV = 'PFC_RC7_DSH_SESSION_MODE'
const INTERACTIVE_CONTROL = 'INTERACTIVE_CONTROL'
const LEASE_BOUND_WORKER = 'LEASE_BOUND_WORKER'

const workerProjectionKeys = [
  'PFC_RC7_MCP_MISSION_ID',
  'PFC_RC7_MCP_TASK_ID',
  'PFC_RC7_MCP_WORKER_ID',
  'PFC_RC7_MCP_LEASE_ID',
  'PFC_RC7_MCP_SCOPE_REF',
]

const capabilityAliases = new Set([
  'filesystem', 'git', 'codegraph', 'pytest', 'junit', 'api', 'browser',
  'database', 'cat', 'runtime_status', 'truth_query', 'read_text',
  'artifact_record', 'git_show_revision', 'git_diff', 'codegraph_probe',
  'codegraph_query', 'codegraph_mcp_tools', 'codegraph_mcp_call',
  'executable_spec_build', 'automation_reuse_resolve', 'script_build',
  'script_validate', 'case_prepare_plan', 'case_prepare_execute',
  'runner_execute', 'attempt_cat_query', 'failure_diagnose',
  'recovery_decide', 'recovery_execute', 'execution_convergence',
])

function workerProjectionPresent() {
  return workerProjectionKeys.every((key) => String(process.env[key] || '').trim().length > 0)
}

function sessionMode() {
  // Defense in depth: Workers may inherit the parent's environment. A complete
  // lease identity always forces strict Worker semantics regardless of the
  // inherited PFC_RC7_DSH_SESSION_MODE value.
  if (workerProjectionPresent()) return LEASE_BOUND_WORKER
  const raw = String(process.env[SESSION_MODE_ENV] || '').trim().toUpperCase()
  if (raw === INTERACTIVE_CONTROL || raw === LEASE_BOUND_WORKER) return raw
  if (!raw) throw new Error('RC7_DSH_SESSION_MODE_REQUIRED')
  throw new Error(`RC7_DSH_SESSION_MODE_INVALID:${raw}`)
}

function leaseAllowedTools() {
  const raw = process.env.PFC_RC7_DSH_ALLOWED_TOOLS || '[]'
  let parsed
  try {
    parsed = JSON.parse(raw)
  } catch (_error) {
    return []
  }
  if (!Array.isArray(parsed)) return []
  const exact = []
  for (const value of parsed) {
    if (typeof value !== 'string') continue
    const tool = value.trim()
    if (!tool || capabilityAliases.has(tool) || tool.includes('*')) continue
    exact.push(tool)
  }
  return [...new Set(exact)]
}

function registeredSchemas(scope, agent) {
  const schemas = scope.tools.schemas(agent)
  if (!Array.isArray(schemas)) return []
  return schemas.filter((schema) =>
    schema && typeof schema.name === 'string' && schema.name.trim() && !schema.name.includes('*')
  )
}

function audit(mode, toolNames) {
  if (process.env.PFC_RC7_DSH_TOOL_AUDIT !== '1') return
  console.error(`[rc7-tool-policy] auth-mode=${mode} visible-tools=${JSON.stringify(toolNames)}`)
}

function auditPreStep(humanCount, injectedCount) {
  if (process.env.PFC_RC7_DSH_TOOL_AUDIT !== '1') return
  console.error(`[rc7-tool-policy] pre-step-order=${JSON.stringify({ injected: injectedCount, human: humanCount, humanLast: true })}`)
}

function humanRequestLast(decision) {
  if (!decision || decision.kind !== 'enter' || !Array.isArray(decision.messages)) return decision
  const human = []
  const injected = []
  for (const message of decision.messages) {
    if (message && message.source && message.source.kind === 'user') human.push(message)
    else injected.push(message)
  }
  if (human.length === 0 || injected.length === 0) return decision
  auditPreStep(human.length, injected.length)
  return { ...decision, messages: [...injected, ...human] }
}

export function apply(ctx) {
  ctx.on('agent/created', ({ agent }) => {
    const scope = agent.ctx
    const mode = sessionMode()
    const strictAllow = mode === LEASE_BOUND_WORKER ? leaseAllowedTools() : []
    const strictAllowSet = new Set(strictAllow)
    let interactiveAllowSet = null

    if (mode === LEASE_BOUND_WORKER && strictAllow.length === 0) {
      throw new Error('RC7_DSH_ALLOWED_TOOLS_EMPTY')
    }

    scope.on('agent/pre-step', async (_payload, next) => {
      const decision = await next()
      return humanRequestLast(decision)
    }, { prepend: true })

    scope.effect(() => scope.tools.guard((execution) => {
      if (mode === LEASE_BOUND_WORKER) {
        return strictAllowSet.has(execution.name)
          ? undefined
          : `RC7_DSH_TOOL_NOT_AUTHORIZED:${execution.name}`
      }
      if (!(interactiveAllowSet instanceof Set)) {
        return 'RC7_DSH_FIELD_TOOL_REGISTRY_NOT_READY'
      }
      return interactiveAllowSet.has(execution.name)
        ? undefined
        : `RC7_DSH_TOOL_NOT_REGISTERED:${execution.name}`
    }))

    scope.on('system-prompt/assemble', async (assembly, _context, next) => {
      const resolved = await next()
      const live = registeredSchemas(scope, agent)
      const byName = new Map(live.map((schema) => [schema.name, schema]))

      if (mode === LEASE_BOUND_WORKER) {
        const missing = strictAllow.filter((toolName) => !byName.has(toolName))
        if (missing.length > 0) {
          throw new Error(`RC7_DSH_REQUIRED_TOOL_NOT_REGISTERED:${missing.join(',')}`)
        }
        const tools = strictAllow.map((toolName) => byName.get(toolName))
        audit(mode, tools.map((schema) => schema.name))
        return { ...resolved, tools }
      }

      // Field/interactive authority is a snapshot of the live registry, not a
      // hard-coded allowlist. This naturally includes Skill and AgentTeams only
      // when those plugins actually registered executable tools for this agent.
      if (live.length === 0) throw new Error('RC7_DSH_FIELD_REGISTERED_TOOLS_EMPTY')
      interactiveAllowSet = new Set(live.map((schema) => schema.name))
      audit(mode, [...interactiveAllowSet])
      return { ...resolved, tools: live }
    })

    scope.systemPrompt.section({
      name: 'rc7:tool-authority',
      order: 50,
      text: () => mode === LEASE_BOUND_WORKER
        ? `RC7 Worker authority is lease-bound. Use only these exact tools: ${JSON.stringify(strictAllow)}. Do not invent any other tool.`
        : 'RC7 Field interactive authority is registry-bound. Use only executable tools actually exposed in the current system prompt/tool registry; never invent tool names and never treat registry visibility as Worker lease authority.',
    })
    scope.systemPrompt.section({
      name: 'rc7:truth-authority',
      order: 51,
      text: () => 'RC7 canonical runtime truth is runtime-state/r1/event-stream.jsonl. Memento/memory is non-authoritative experience context only and MUST NOT be used to assert execution status, PASS, defect existence, or evidence completion without canonical R1 evidence.',
    })
  })
}
