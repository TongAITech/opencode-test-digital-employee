import { tool } from "@opencode-ai/plugin"
import path from "path"

type PfcToolContext = {
  directory?: string
  worktree?: string | null
}

async function isCanonicalWorkspace(candidate: string): Promise<boolean> {
  const required = [
    "PFC_R1_R4_INSTALLATION.json",
    "AGENTS.md",
    "opencode.json",
    "ai-test/runtime/aitest_runtime/canonical_runtime.py",
    "ai-test/runtime/aitest_runtime/autonomous_orchestration.py",
    "ai-test/runtime/aitest_runtime/product_entry.py",
    ".opencode/agents/aitest-director.md",
  ]
  const checks = await Promise.all(required.map((item) => Bun.file(path.join(candidate, item)).exists()))
  return checks.every(Boolean)
}

function candidateRoots(context: PfcToolContext): string[] {
  const values = [process.env.AITEST_WORKSPACE_ROOT, context.directory, context.worktree, process.cwd()]
  const result: string[] = []
  const seen = new Set<string>()
  for (const value of values) {
    if (!value) continue
    const normalized = path.normalize(value)
    for (const candidate of [normalized, path.dirname(normalized)]) {
      const key = candidate.toLowerCase()
      if (seen.has(key)) continue
      seen.add(key)
      result.push(candidate)
    }
  }
  return result
}

async function resolvePfcWorkspace(context: PfcToolContext): Promise<string> {
  for (const candidate of candidateRoots(context)) {
    if (await isCanonicalWorkspace(candidate)) return candidate
  }
  throw new Error(`PFC_CANONICAL_RUNTIME_PATH_NOT_FOUND; candidates=${candidateRoots(context).join("|")}`)
}

async function pythonCommand(workspace: string): Promise<string[]> {
  const win = process.platform === "win32"
  const local = path.join(workspace, "runtime", "python", win ? "python.exe" : "python")
  if (await Bun.file(local).exists()) return [local]
  throw new Error(`PFC_PORTABLE_PYTHON_NOT_FOUND; expected=${local}`)
}

async function runPfc(context: PfcToolContext, args: string[]): Promise<unknown> {
  const workspace = await resolvePfcWorkspace(context)
  const py = await pythonCommand(workspace)
  const runtime = path.join(workspace, "ai-test", "runtime")
  const env = {
    ...process.env,
    AITEST_WORKSPACE_ROOT: workspace,
    ...(process.env.AITEST_RUNTIME_SPINE_DB ? { AITEST_RUNTIME_SPINE_DB: process.env.AITEST_RUNTIME_SPINE_DB } : {}),
    PYTHONPATH: [runtime, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
  }
  const proc = Bun.spawn([...py, "-m", "aitest_runtime.product_entry", ...args], {
    cwd: workspace,
    env,
    stdout: "pipe",
    stderr: "pipe",
  })
  const stdout = await new Response(proc.stdout).text()
  const stderr = await new Response(proc.stderr).text()
  const code = await proc.exited
  if (code !== 0) throw new Error((stderr || stdout || `PFC canonical runtime exited ${code}`).trim().slice(0, 4000))
  let parsed: unknown
  try {
    parsed = JSON.parse(stdout)
  } catch {
    throw new Error("PFC_CANONICAL_TRUTH_QUERY_FAILED; canonical result was not JSON")
  }
  if (args[0] === "interactive-truth") {
    const record = parsed as Record<string, unknown>
    if (record.truth_source !== "R1_EVENT_STREAM" || record.conversation_is_not_truth !== true) {
      throw new Error("PFC_CANONICAL_TRUTH_QUERY_FAILED; R1 Event Stream truth contract not satisfied")
    }
  }
  return parsed
}

export const truth = tool({
  description: "Read PFC canonical runtime truth from the R1 Event Stream. Never reconstruct runtime state from conversation memory or the legacy aitest.db store.",
  args: {
    target: tool.schema.string().describe("status|orchestration|project|requirement|coverage|cases|mission|execution|defects|human_actions|all"),
    requirement_id: tool.schema.string().optional().describe("Optional business Requirement ID, for example STBB19-234"),
    case_id: tool.schema.string().optional().describe("Optional StandardTestCase ID for a case-specific read"),
  },
  async execute(args, context) {
    return runPfc(context as PfcToolContext, [
      "interactive-truth",
      "--target",
      args.target,
      ...(args.requirement_id ? ["--requirement-id", args.requirement_id] : []),
      ...(args.case_id ? ["--case-id", args.case_id] : []),
    ])
  },
})

export const command = tool({
  description: "Compatibility PFC request surface. Read-only show is canonical; G2 Mission/Plan/Scheduler mutations must use aitest_director/planner/scheduler tools, while G3-G6 mutations remain HOLD. Never falls back to the legacy runtime.",
  args: {
    intent: tool.schema.string().describe("show|select_requirement|continue|hold|review_reject|execute_approved|rerun_failed|cat|database_status|defect_assessment"),
    requirement_id: tool.schema.string().optional().describe("Optional explicit business Requirement scope"),
    case_id: tool.schema.string().optional().describe("Optional StandardTestCase ID"),
    note: tool.schema.string().optional().describe("Human review note; never include secrets or credentials"),
  },
  async execute(args, context) {
    return runPfc(context as PfcToolContext, [
      "interactive-command",
      "--intent",
      args.intent,
      ...(args.requirement_id ? ["--requirement-id", args.requirement_id] : []),
      ...(args.case_id ? ["--case-id", args.case_id] : []),
      ...(args.note ? ["--note", args.note] : []),
    ])
  },
})
