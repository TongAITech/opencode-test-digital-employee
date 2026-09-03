import { tool } from "@opencode-ai/plugin"
import path from "path"

type ToolContext = { directory?: string; worktree?: string | null }

const ACTION = "human_gate_user_turn_resume"

async function canonicalWorkspace(context: ToolContext): Promise<string> {
  const required = [
    "PFC_R1_R4_INSTALLATION.json",
    "ai-test/runtime/aitest_runtime/canonical_runtime.py",
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

async function resolveHumanGate(
  context: ToolContext,
  missionId: string,
  userText: string,
  actorId: string,
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
  const payload = {
    mission_id: missionId,
    user_text: userText,
    actor_id: actorId || "opencode-user-turn",
  }
  const proc = Bun.spawn([
    python,
    "-m",
    "aitest_runtime.product_entry",
    "g4",
    "--role",
    "DIRECTOR",
    "--action",
    ACTION,
    "--payload",
    JSON.stringify(payload),
  ], { cwd: workspace, env, stdout: "pipe", stderr: "pipe" })
  const stdout = await new Response(proc.stdout).text()
  const stderr = await new Response(proc.stderr).text()
  const code = await proc.exited
  if (code !== 0) throw new Error((stderr || stdout || `AITEST HumanGate resume exited ${code}`).trim().slice(0, 6000))
  let result: unknown
  try { result = JSON.parse(stdout) } catch { throw new Error("AITEST_HUMAN_GATE_RESUME_NOT_JSON") }
  if ((result as Record<string, unknown>).truth_source !== "R1_EVENT_STREAM") {
    throw new Error("AITEST_HUMAN_GATE_RESUME_TRUTH_CONTRACT_FAILED")
  }
  return result
}

export const resume = tool({
  description: "Deterministic HumanGate completion-verification surface for a NEW OpenCode User Turn. human_gate_user_turn_resume treats phrases such as 完成/好了/已登录 only as REQUEST_TO_VERIFY_COMPLETION; exact compatible gate selection comes from R1 and fresh Browser Runtime verification is the only completion authority. Multiple compatible gates fail closed.",
  args: {
    mission_id: tool.schema.string().describe("Current durable Mission id resolved from R1 truth, never conversation memory."),
    user_text: tool.schema.string().describe("Current new User Turn text. It is a request to verify completion, never completion truth."),
    actor_id: tool.schema.string().default("opencode-user-turn"),
  },
  async execute(args, context) {
    return resolveHumanGate(context as ToolContext, args.mission_id, args.user_text, args.actor_id)
  },
})
