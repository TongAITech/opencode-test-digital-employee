# G3 R2-0 Code Intelligence Provider Reality Recon

**Repository:** `TongAITech/opencode-test-digital-employee`  
**Canonical starting commit:** `725457e5b475019072ac936fd55756c995ddf69a`  
**Repair branch:** `repair/g3-g4-wave2`  
**Authority:** `docs/governance/00.8_PLANNING_ALIGNMENT_AND_G3_G4_REPAIR_WAVE_2_AUTHORIZATION.md`

## Baseline reality

The canonical Git baseline confirms:

1. `g3/code_intelligence.py` directly composed Git, ripgrep and language logic.
2. `CODEGRAPH` was hard-coded `UNAVAILABLE`; there was no injectable/resolvable CodeGraph provider seam in G3 product code.
3. Python had AST-based enclosing-symbol mapping.
4. Java/JavaScript/TypeScript/Vue used regex fallback and completeness was not accounted per changed executable line.
5. A mapped declaration line could therefore coexist with an unmapped method-body line without the file being forced to retain an exact missing-symbol obligation.
6. The historical Construction GitNexus runtime README is not present in canonical Git source and is therefore not a source authority or activatable provider contract.
7. Repository-root `runtime-lock.json` already pins the selected structural payload as `codegraph-ai/CodeGraph` v0.20.1 / Windows x64 / `graph-only`, SHA256 `aa1b6108217c119af6ac444b8652a0eadcfe2c343bff78ead2edd15b6b7b15b1`. The binary is a derived offline payload and is intentionally excluded from Git.

## R2-1 implementation contract

The repair implements a provider-neutral `ChangeIntelligenceBroker`:

```text
GitChangeTruthProvider (mandatory exact changed file/line truth)
  + CodeGraphProvider (optional structural enrichment)
  + LanguageStructuralProvider (AST/structural fallback; regex last-resort)
  + ripgrep reference enrichment
  + API/Schema/Config surface provider
  -> canonical CodeIntelligenceEnvelope + durable provider provenance
```

Invariants:

- Git output is computed first and remains immutable Change Truth.
- CodeGraph only receives Git-established changed executable lines.
- CodeGraph availability is resolved from the pinned runtime-lock profile and verified binary SHA; missing binary is `UNAVAILABLE`, invalid profile/SHA is `BLOCKED`.
- No CodeGraph binary, graph index or cache is committed to Git.
- Every relevant changed executable line is classified independently as `MAPPED_TO_SYMBOL` or `UNMAPPED`.
- Every `UNMAPPED` line creates an exact `MISSING_SYMBOL_MAPPING` coverage/risk obligation.
- Regex mappings never make the composite structural result `COMPLETE` by themselves.
- ripgrep and API/Schema/Config enrich impact only; neither can mutate changed-line truth.
- CodeGraph is not Actual Coverage authority. Bank Incremental Code Coverage Platform remains the only Actual Coverage authority.

## Construction evidence before commit

Focused fresh checks:

- Repair Wave 2 provider/mapping adversarial suite: `29/29 PASS`.
- Existing G3 product-path regression: `50/50 PASS`.
- The adversarial suite includes real temporary Git repositories for Java, TypeScript and Vue mixed declaration/body changes.
- A construction-only fake executable, pinned by a temporary runtime-lock SHA, proves the real resolver invokes the CodeGraph adapter as `--graph-only --run-tool codegraph_get_ai_context` without committing any runtime binary.
- Missing CodeGraph binary is proven `UNAVAILABLE`, not fake `AVAILABLE`.
- Injected structural provider failure retains complete Git changed-file/line truth.
- Provider health/provenance, per-line mapping and exact missing-symbol obligations survive R1 write, process restart/replay and `runtime.verify_projection()`.

This recon does not claim real bank-host CodeGraph binary execution or bank source graph parity; those remain offline payload / Field Validation facts.
