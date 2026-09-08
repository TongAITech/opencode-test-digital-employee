// Presentation boundary only. Runtime commands and R1 facts remain unchanged.
import { createHash } from "node:crypto"

export const MAX_MODEL_RESULT_BYTES = 16384
const bytes = value => Buffer.byteLength(value, "utf8")
const hash = value => createHash("sha256").update(value).digest("hex")
const pointer = key => String(key).replaceAll("~", "~0").replaceAll("/", "~1")
const identity = key => /(?:^id$|_id$|_ref$|^status$|^outcome$|^truth_source$|^next_offset$|^head_seq$|^reason$|^action$)/.test(key)
const controlKeys = ["status", "truth_source", "mission_id", "task_id", "attempt_id", "session_id", "root_attempt_id", "outcome", "next_offset", "head_seq"]
const controlObjects = new Set(["next", "attempt", "task", "external_session", "intake", "activation", "planner_session", "result", "gate", "resume", "cursor"])
const priority = key => controlKeys.includes(key) ? controlKeys.indexOf(key) : controlObjects.has(key) ? 15 : identity(key) ? 20 : 30

function clip(text, budget) {
  if (bytes(text) <= budget) return text
  // Never split a multi-byte UTF-8 character or count characters as bytes.
  let end = Math.min(text.length, budget)
  while (end > 0 && bytes(text.slice(0, end)) > budget) end--
  if (end > 0 && /[\uD800-\uDBFF]/.test(text[end - 1])) end--
  return text.slice(0, end)
}

export function modelError(message) {
  const text = String(message)
  return new Error(bytes(text) <= MAX_MODEL_RESULT_BYTES - 128 ? text :
    clip(text, MAX_MODEL_RESULT_BYTES - 256) + `\n[error excerpt; omitted=true; source_sha256=${hash(text)}]`)
}

export function boundedTool(factory, definition) {
  return factory({ ...definition, async execute(...args) {
    try {
      const result = await definition.execute.apply(definition, args)
      if (typeof result !== "string") return modelResult(result)
      if (bytes(result) <= MAX_MODEL_RESULT_BYTES) return result
      // Catch accidental future return paths as well as today's explicit
      // projections. The boundary must also catch spawn/parse/SDK exceptions.
      try { return modelResult(JSON.parse(result)) }
      catch { return modelResult({ text: result }) }
    } catch (error) {
      throw modelError(error instanceof Error ? error.message : String(error))
    }
  } })
}

export function modelResult(value) {
  const serialized = JSON.stringify(value)
  if (bytes(serialized) <= MAX_MODEL_RESULT_BYTES) return serialized
  const sourceDigest = hash(serialized)
  const refs = []
  function collect(item, location = "") {
    if (!item || typeof item !== "object" || refs.length >= 12) return
    if (!Array.isArray(item) && typeof item.fact_id === "string") {
      refs.push({ fact_id: item.fact_id, json_pointer: location,
        fact_kind: item.fact_kind || "UNKNOWN",
        ...(["SOURCE_DOCUMENT", "REQUIREMENT_ANALYSIS_ARTIFACT", "CURRENT_RELEASE"].includes(item.fact_kind) ?
          { read_action: "read_intake_source", offset: 0, limit: 1024 } : { read_action: "work_context; select the fact's existing domain read action" }) })
    }
    for (const [key, child] of Object.entries(item)) collect(child, location + "/" + pointer(key))
  }
  collect(value)
  function omitted(item, location) {
    const raw = JSON.stringify(item)
    return { _omitted: true, source_sha256: hash(raw), json_pointer: location,
      source_bytes: bytes(raw), ...(Array.isArray(item) ? { item_count: item.length } : {}) }
  }
  for (const [width, textBytes, depth] of [[12, 512, 8], [6, 256, 6], [3, 128, 5], [1, 64, 4]]) {
    function project(item, location = "", level = 0, key = "") {
      if (typeof item === "string") {
        if (bytes(item) <= (identity(key) ? 2048 : textBytes)) return item
        return { ...omitted(item, location), excerpt: clip(item, textBytes) }
      }
      if (!item || typeof item !== "object") return item
      if (level >= depth) return omitted(item, location)
      if (Array.isArray(item)) return { items: item.slice(0, width).map((v, i) => project(v, location + "/" + i, level + 1)),
        item_count: item.length, ...(item.length > width ? { omitted: omitted(item.slice(width), location + "/" + width) } : {}) }
      const entries = Object.entries(item).sort(([a], [b]) => priority(a) - priority(b))
      const selected = entries.filter(([k], index) => bytes(k) <= 256 && (identity(k) || controlObjects.has(k) || index < width))
      const result = Object.fromEntries(selected.map(([k, v]) => [k, project(v, location + "/" + pointer(k), level + 1, k)]))
      if (selected.length < entries.length) result._omitted_fields = omitted(Object.fromEntries(entries.filter(([k]) => !(k in result))), location)
      return result
    }
    const projected = { ...(value && typeof value === "object" && !Array.isArray(value) ? project(value) : { value: project(value) }),
      _model_projection: { kind: "BOUNDED_PRESENTATION_ONLY", omitted: true, source_sha256: sourceDigest,
        source_bytes: bytes(serialized), max_response_bytes: MAX_MODEL_RESULT_BYTES,
        authority: "R1_EVENT_STREAM; this projection is not a new Runtime fact",
        fact_refs: refs.slice(0, width),
        continuation: "Use the exact Mission and governed Task/Attempt/Session with work_context or intake_context. For SOURCE_DOCUMENT/REQUIREMENT_ANALYSIS_ARTIFACT/CURRENT_RELEASE use read_intake_source with fact_id and next_offset, limit<=1024. Preserve references; never concatenate source pages into a prompt." } }
    const output = JSON.stringify(projected)
    if (bytes(output) <= MAX_MODEL_RESULT_BYTES) return output
  }
  // Exceptional identity-heavy results cannot silently masquerade as complete.
  // Preserve root result controls; the caller must recover a narrower R1 view.
  function controlSummary(item, level = 0) {
    if (!item || typeof item !== "object" || Array.isArray(item) || level > 4) return undefined
    const summary = {}
    for (const [key, child] of Object.entries(item).sort(([a], [b]) => priority(a) - priority(b))) {
      if (bytes(key) > 256) continue
      const selected = controlObjects.has(key) ? controlSummary(child, level + 1) :
        identity(key) && ["string", "number", "boolean"].includes(typeof child) && bytes(JSON.stringify(child)) <= 2048 ? child : undefined
      if (selected !== undefined && bytes(JSON.stringify({ ...summary, [key]: selected })) <= 4096) summary[key] = selected
    }
    return summary
  }
  const controls = {}
  for (const [key, item] of Object.entries(value || {}).sort(([a], [b]) => priority(a) - priority(b))) {
    if (bytes(key) > 256) continue
    const selected = controlObjects.has(key) ? controlSummary(item) :
      identity(key) && ["string", "number", "boolean"].includes(typeof item) && bytes(JSON.stringify(item)) <= 2048 ? item : undefined
    if (selected !== undefined && bytes(JSON.stringify({ ...controls, [key]: selected })) <= 12000) controls[key] = selected
  }
  const fallback = JSON.stringify({ ...controls, _model_projection: { kind: "BOUNDED_PRESENTATION_ONLY", omitted: true,
    source_sha256: sourceDigest, source_bytes: bytes(serialized),
    continuation: "Result exceeds model budget. Recover a narrower Mission/Task/fact through work_context, intake_context or read_intake_source; do not repeat a mutation." } })
  if (bytes(fallback) <= MAX_MODEL_RESULT_BYTES) return fallback
  return JSON.stringify({ _model_projection: { kind: "BOUNDED_PRESENTATION_ONLY", omitted: true,
    source_sha256: sourceDigest, source_bytes: bytes(serialized),
    reason: "IDENTITY_SUMMARY_EXCEEDS_BUDGET; recover a narrower R1 view; do not repeat a mutation" } })
}
