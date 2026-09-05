import { tool } from "@opencode-ai/plugin"
import path from "path"

type ToolContext = { directory?: string; worktree?: string | null }

async function canonicalWorkspace(context: ToolContext): Promise<string> {
  const required = [
    "PFC_R1_R4_INSTALLATION.json",
    "ai-test/runtime/aitest_runtime/canonical_runtime.py",
    "ai-test/runtime/aitest_runtime/autonomous_orchestration.py",
    "ai-test/runtime/aitest_runtime/product_entry.py",
  ]
  const roots = [process.env.AITEST_WORKSPACE_ROOT, context.directory, context.worktree, process.cwd()].filter(Boolean) as string[]
  const seen = new Set<string>()
  for (const raw of roots) {
    for (const candidate of [path.normalize(raw), path.dirname(path.normalize(raw))]) {
      const key = candidate.toLowerCase()
      if (seen.has(key)) continue
      seen.add(key)
      const ok = (await Promise.all(required.map((item) => Bun.file(path.join(candidate, item)).exists()))).every(Boolean)
      if (ok) return candidate
    }
  }
  throw new Error(`AITEST_CANONICAL_RUNTIME_PATH_NOT_FOUND; candidates=${roots.join("|")}`)
}

async function portablePython(workspace: string): Promise<string> {
  const executable = path.join(workspace, "runtime", "python", process.platform === "win32" ? "python.exe" : "python")
  if (await Bun.file(executable).exists()) return executable
  throw new Error(`PFC_PORTABLE_PYTHON_NOT_FOUND; expected=${executable}`)
}

async function orchestrate(
  context: ToolContext,
  role: "DIRECTOR" | "PLANNER" | "SCHEDULER" | "EXECUTOR",
  action: string,
  payload: Record<string, unknown>,
): Promise<unknown> {
  const workspace = await canonicalWorkspace(context)
  const python = await portablePython(workspace)
  const runtime = path.join(workspace, "ai-test", "runtime")
  const env = {
    ...process.env,
    AITEST_WORKSPACE_ROOT: workspace,
    ...(process.env.AITEST_RUNTIME_SPINE_DB ? { AITEST_RUNTIME_SPINE_DB: process.env.AITEST_RUNTIME_SPINE_DB } : {}),
    PYTHONPATH: [runtime, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
  }
  const proc = Bun.spawn([
    python,
    "-m",
    "aitest_runtime.product_entry",
    "orchestrate",
    "--role",
    role,
    "--action",
    action,
    "--payload",
    JSON.stringify(payload ?? {}),
  ], { cwd: workspace, env, stdout: "pipe", stderr: "pipe" })
  const stdout = await new Response(proc.stdout).text()
  const stderr = await new Response(proc.stderr).text()
  const code = await proc.exited
  if (code !== 0) throw new Error((stderr || stdout || `AITEST orchestration exited ${code}`).trim().slice(0, 6000))
  let result: unknown
  try { result = JSON.parse(stdout) } catch { throw new Error("AITEST_CANONICAL_ORCHESTRATION_NOT_JSON") }
  const record = result as Record<string, unknown>
  if (record.truth_source !== "R1_EVENT_STREAM") {
    throw new Error("AITEST_CANONICAL_ORCHESTRATION_TRUTH_CONTRACT_FAILED")
  }
  return result
}


async function g3(
  context: ToolContext,
  role: "DIRECTOR" | "REQUIREMENT_ANALYST" | "CODE_ANALYST" | "TEST_STRATEGIST" | "CASE_DESIGNER" | "EVALUATOR",
  action: string,
  payload: Record<string, unknown>,
): Promise<unknown> {
  const workspace = await canonicalWorkspace(context)
  const python = await portablePython(workspace)
  const runtime = path.join(workspace, "ai-test", "runtime")
  const env = {
    ...process.env,
    AITEST_WORKSPACE_ROOT: workspace,
    ...(process.env.AITEST_RUNTIME_SPINE_DB ? { AITEST_RUNTIME_SPINE_DB: process.env.AITEST_RUNTIME_SPINE_DB } : {}),
    PYTHONPATH: [runtime, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
  }
  const proc = Bun.spawn([python, "-m", "aitest_runtime.product_entry", "g3", "--role", role, "--action", action, "--payload", JSON.stringify(payload ?? {})],
    { cwd: workspace, env, stdout: "pipe", stderr: "pipe" })
  const stdout = await new Response(proc.stdout).text()
  const stderr = await new Response(proc.stderr).text()
  const code = await proc.exited
  if (code !== 0) throw new Error((stderr || stdout || `AITEST G3 exited ${code}`).trim().slice(0, 6000))
  let result: unknown
  try { result = JSON.parse(stdout) } catch { throw new Error("AITEST_G3_NOT_JSON") }
  if ((result as Record<string, unknown>).truth_source !== "R1_EVENT_STREAM") throw new Error("AITEST_G3_TRUTH_CONTRACT_FAILED")
  return result
}


async function g4(
  context: ToolContext,
  role: "DIRECTOR" | "EXECUTOR",
  action: string,
  payload: Record<string, unknown>,
): Promise<unknown> {
  const workspace = await canonicalWorkspace(context)
  const python = await portablePython(workspace)
  const runtime = path.join(workspace, "ai-test", "runtime")
  const env = {
    ...process.env,
    AITEST_WORKSPACE_ROOT: workspace,
    ...(process.env.AITEST_RUNTIME_SPINE_DB ? { AITEST_RUNTIME_SPINE_DB: process.env.AITEST_RUNTIME_SPINE_DB } : {}),
    PYTHONPATH: [runtime, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
  }
  const proc = Bun.spawn([python, "-m", "aitest_runtime.product_entry", "g4", "--role", role, "--action", action, "--payload", JSON.stringify(payload ?? {})],
    { cwd: workspace, env, stdout: "pipe", stderr: "pipe" })
  const stdout = await new Response(proc.stdout).text()
  const stderr = await new Response(proc.stderr).text()
  const code = await proc.exited
  if (code !== 0) throw new Error((stderr || stdout || `AITEST G4 exited ${code}`).trim().slice(0, 6000))
  let result: unknown
  try { result = JSON.parse(stdout) } catch { throw new Error("AITEST_G4_NOT_JSON") }
  if ((result as Record<string, unknown>).truth_source !== "R1_EVENT_STREAM") throw new Error("AITEST_G4_TRUTH_CONTRACT_FAILED")
  return result
}


async function g5(
  context: ToolContext,
  role: "DIAGNOSIS",
  action: string,
  payload: Record<string, unknown>,
): Promise<unknown> {
  const workspace = await canonicalWorkspace(context)
  const python = await portablePython(workspace)
  const runtime = path.join(workspace, "ai-test", "runtime")
  const env = {
    ...process.env,
    AITEST_WORKSPACE_ROOT: workspace,
    ...(process.env.AITEST_RUNTIME_SPINE_DB ? { AITEST_RUNTIME_SPINE_DB: process.env.AITEST_RUNTIME_SPINE_DB } : {}),
    PYTHONPATH: [runtime, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
  }
  const proc = Bun.spawn([python, "-m", "aitest_runtime.product_entry", "g5", "--role", role, "--action", action, "--payload", JSON.stringify(payload ?? {})],
    { cwd: workspace, env, stdout: "pipe", stderr: "pipe" })
  const stdout = await new Response(proc.stdout).text()
  const stderr = await new Response(proc.stderr).text()
  const code = await proc.exited
  if (code !== 0) throw new Error((stderr || stdout || `AITEST G5 exited ${code}`).trim().slice(0, 6000))
  let result: unknown
  try { result = JSON.parse(stdout) } catch { throw new Error("AITEST_G5_NOT_JSON") }
  if ((result as Record<string, unknown>).truth_source !== "R1_EVENT_STREAM") throw new Error("AITEST_G5_TRUTH_CONTRACT_FAILED")
  return result
}

const pending = (role: string, action: string, payload: unknown, nextGate: string) => ({
  status: "HOLD",
  runtime_truth: "R1_EVENT_STREAM",
  legacy_runtime_write: "FORBIDDEN",
  role,
  action,
  payload_received: payload != null,
  reason: `${nextGate}_CANONICAL_WIRING_PENDING`,
})

export const director = tool({
  description: "Canonical AI Test Director. Start/resume Mission truth, autonomously open the Planner Session, read orchestration state, and govern Human Gates. Conversation is never Mission truth.",
  args: {
    action: tool.schema.string().describe("status|start_test|continue_test|intake_mission|open_planner|open_human_gate|decide_human_gate"),
    payload: tool.schema.record(tool.schema.string(), tool.schema.any()).default({}),
  },
  async execute(args, context) { return orchestrate(context as ToolContext, "DIRECTOR", args.action, args.payload) },
})

export const g3_director = tool({
  description: "Canonical G3 TestIntent intake. Persists autonomous/focused testing intent and returns a governed Planner proposal. It never bypasses Mission/Plan/Task/Session governance.",
  args: { action: tool.schema.string().describe("status|work_context|register_intent"), payload: tool.schema.record(tool.schema.string(), tool.schema.any()).default({}) },
  async execute(args, context) { return g3(context as ToolContext, "DIRECTOR", args.action, args.payload) },
})

export const requirement_analyst = tool({
  description: "G3 Requirement Analyst. Converts provenance-bound Requirement/SST/design facts into R3.1 obligations. Unknown business facts become KnowledgeGap/HumanTask; never guess.",
  args: { action: tool.schema.string().describe("status|work_context|analyze_requirement"), payload: tool.schema.record(tool.schema.string(), tool.schema.any()).default({}) },
  async execute(args, context) { return g3(context as ToolContext, "REQUIREMENT_ANALYST", args.action, args.payload) },
})

export const code_analyst = tool({
  description: "G3 Code Analyst. Performs multi-repo static Change Intelligence and reads canonical bank incremental coverage when authenticated. Static truth is never Actual Coverage.",
  args: { action: tool.schema.string().describe("status|work_context|analyze_changes|acquire_coverage"), payload: tool.schema.record(tool.schema.string(), tool.schema.any()).default({}) },
  async execute(args, context) { return g3(context as ToolContext, "CODE_ANALYST", args.action, args.payload) },
})

export const test_strategist = tool({
  description: "G3 Reach+Find strategist. Produces risk/coverage/hypothesis-driven L1-L7 strategy or governed API/UI/Security/Performance profiles. Execution is performed only by the Router-bound G4 Executor.",
  args: { action: tool.schema.string().describe("status|work_context|recommend_next_work|create_strategy|design_test_profile"), payload: tool.schema.record(tool.schema.string(), tool.schema.any()).default({}) },
  async execute(args, context) { return g3(context as ToolContext, "TEST_STRATEGIST", args.action, args.payload) },
})

export const case_designer = tool({
  description: "G3 Standard Case Designer. Builds detailed R3.3 cases with preconditions, test data, ordered steps, expected results, oracle/evidence/postcondition and CaseValueLink.",
  args: { action: tool.schema.string().describe("status|work_context|design_cases"), payload: tool.schema.record(tool.schema.string(), tool.schema.any()).default({}) },
  async execute(args, context) { return g3(context as ToolContext, "CASE_DESIGNER", args.action, args.payload) },
})

export const planner = tool({
  description: "Canonical R2 Planner governance. The AI authors an evidence-bound semantic Plan candidate; R2.3 validates/canonicalizes/freezes it into the R1 Event Stream. Never execute tasks here.",
  args: {
    action: tool.schema.string().describe("status|propose_plan"),
    payload: tool.schema.record(tool.schema.string(), tool.schema.any()).default({}),
  },
  async execute(args, context) { return orchestrate(context as ToolContext, "PLANNER", args.action, args.payload) },
})

export const scheduler = tool({
  description: "Canonical R2 Scheduler. Select dependency-ready Tasks and advance durable orchestration. Session selection/creation/rotation is owned by the G2.1 Runtime Session Router and background Control Loop.",
  args: {
    action: tool.schema.string().describe("status|advance|dispatch_next"),
    payload: tool.schema.record(tool.schema.string(), tool.schema.any()).default({}),
  },
  async execute(args, context) { return orchestrate(context as ToolContext, "SCHEDULER", args.action, args.payload) },
})

export const executor = tool({
  description: "Canonical G2/G4 governed executor. Task outcome remains G2; real execution/cursor/HumanTakeover/evidence/batching are G4 actions and still use G2.1-routed Attempts/Sessions.",
  args: {
    action: tool.schema.string().describe("status|report_task_outcome|record_cursor|recover_cursor|register_capability|validate_executor|execute_capability|capability_human_gate|request_human_takeover|reconcile_human_takeover|complete_human_takeover|record_step_result|create_batch"),
    payload: tool.schema.record(tool.schema.string(), tool.schema.any()).default({}),
  },
  async execute(args, context) {
    if (["status", "report_task_outcome"].includes(args.action)) return orchestrate(context as ToolContext, "EXECUTOR", args.action, args.payload)
    if (["record_cursor", "recover_cursor", "register_capability", "validate_executor", "execute_capability", "capability_human_gate", "request_human_takeover", "reconcile_human_takeover", "complete_human_takeover", "record_step_result", "create_batch"].includes(args.action)) return g4(context as ToolContext, "EXECUTOR", args.action, args.payload)
    return pending("EXECUTOR", args.action, args.payload, "G5_DEFECT_TRUTH")
  },
})

export const g4_director = tool({
  description: "G4 non-LLM test-goal convergence surface. Creates durable goals, consumes bank G3 coverage facts, evaluates/replans, records blockers/iterations/risk acceptance; it never authors cases or confirms defects.",
  args: {
    action: tool.schema.string().describe("status|create_goal|control_tick|coverage_from_g3|blocker_gap|risk_acceptance|record_iteration"),
    payload: tool.schema.record(tool.schema.string(), tool.schema.any()).default({}),
  },
  async execute(args, context) { return g4(context as ToolContext, "DIRECTOR", args.action, args.payload) },
})

export const worker = tool({
  description: "Generic durable worker lifecycle surface for any Session Router-assigned Logical Agent. It can read status or report the exact bound Task outcome; it cannot manage Session lifecycle or execute G4 test capabilities.",
  args: {
    action: tool.schema.string().describe("status|report_task_outcome"),
    payload: tool.schema.record(tool.schema.string(), tool.schema.any()).default({}),
  },
  async execute(args, context) {
    if (["status", "report_task_outcome"].includes(args.action)) {
      return orchestrate(context as ToolContext, "EXECUTOR", args.action, args.payload)
    }
    return pending("WORKER", args.action, args.payload, "G4_REAL_EXECUTION")
  },
})

export const evaluator = tool({
  description: "G3 design Evaluator. Reviews detailed Standard Test Case design via frozen R3.4 and raises Human Review. Real SUT execution is owned by G4; confirmed-defect truth remains G5 HOLD.",
  args: { action: tool.schema.string().describe("status|work_context|evaluate_case_design"), payload: tool.schema.record(tool.schema.string(), tool.schema.any()).default({}) },
  async execute(args, context) {
    if (["status", "work_context", "evaluate_case_design"].includes(args.action)) return g3(context as ToolContext, "EVALUATOR", args.action, args.payload)
    return pending("EVALUATOR", args.action, args.payload, "G4_REAL_EXECUTION")
  },
})

export const diagnosis = tool({
  description: "Canonical G5 Diagnosis/Defect Hunter surface. Test failures remain Observations until durable investigation confirms defect truth. New evidence must return through governed G2/G3/G4 work.",
  args: {
    action: tool.schema.string().describe("status|work_context|record_anomaly|create_candidate|request_evidence_deepening|record_evidence_assessment|correlate_sources|evaluate_reproducibility|assess_false_positive|assess_defect_truth|record_rca|record_checkpoint|handoff_confirmed_defect"),
    payload: tool.schema.record(tool.schema.string(), tool.schema.any()).default({}),
  },
  async execute(args, context) { return g5(context as ToolContext, "DIAGNOSIS", args.action, args.payload) },
})

export const knowledge = tool({
  description: "Canonical governed learning surface. R4 learning/promotion wiring remains HOLD until G6.",
  args: { action: tool.schema.string(), payload: tool.schema.record(tool.schema.string(), tool.schema.any()).default({}) },
  async execute(args) { return pending("KNOWLEDGE", args.action, args.payload, "G6_R4_LEARNING") },
})
