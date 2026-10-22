# RC8 Code Analysis Reality Gate

Status: ACTIVE / W2 vertical slice

## Goal

CodeGraph 可用不等于完整代码分析完成。本 Gate 要证明：

`Git Java change -> CodeGraph 多轮结构证据 -> 结构充分度评估 -> DSH 语义分析 -> evidence-bound claims -> semantic sufficiency -> Artifact -> R1 -> Center`

## Truth boundaries

1. Git 是代码版本、diff、working tree、snapshot 的事实源。
2. CodeGraph 是 callers/callees/dependency/impact 的结构证据源。
3. 规则引擎只允许生成 `HYPOTHESIS/CANDIDATE`，不能冒充 AI 业务结论。
4. 完整代码分析结论必须来自语义分析 Worker，并且每个 claim 至少引用一个当前分析允许的 `evidence_ref`。
5. `STRUCTURAL PASS != CODE_ANALYSIS_SUFFICIENT`。
6. 只有 `structural_sufficiency=PASS` 且 `semantic.sufficiency.state=PASS` 才允许 `code-analysis=VERIFIED`。

## Structural loop

Runner 初始只选择少量 Java 变更点：

1. `codegraph_get_ai_context`
2. `codegraph_get_callers`
3. `codegraph_get_callees`
4. `codegraph_get_dependency_graph`
5. `codegraph_analyze_impact`

然后评估：

- 每个变更 Java 文件是否至少有一个 query point；
- 所有 required structural calls 是否成功；
- source snapshot 是否从分析开始到发布保持不变。

若不足，则扩大 query points 后重跑。源码变化则 fail-close，必须重新分析。

## Structural-only result

未提供语义分析时，即使所有 CodeGraph 查询成功，也只能得到：

```text
classification = CODE_ANALYSIS_STRUCTURAL_EVIDENCE_SUFFICIENT_SEMANTIC_PENDING
overall_sufficiency = SEMANTIC_PENDING
capability_state = PROBING
exit_code = 30
```

这是正确状态，不是失败，也绝不能升级为完整 Code Analysis PASS。

## DSH semantic input

DSH Worker 应读取本轮 `analysis/code-analysis.json`。其中包含：

- `source_change`
- 当前 `snapshot_id`
- changed Java files
- structural findings
- callers/callees/dependency/impact payload
- risk hypotheses（仅候选）
- test impact candidates（仅候选）
- `evidence_refs`

DSH 必须输出一个 UTF-8 JSON 对象，至少包含：

```json
{
  "summary": "代码变更与整体影响摘要",
  "changes": [
    {
      "file": "...",
      "symbol": "...",
      "change": "..."
    }
  ],
  "impact_chains": [
    {
      "entry": "...",
      "path": ["Controller", "Service", "Repository"],
      "impact": "..."
    }
  ],
  "risks": [
    {
      "type": "BUSINESS_RULE|API_CONTRACT|DATA_ACCESS|AUTHORIZATION|REGRESSION|...",
      "description": "...",
      "severity": "HIGH|MEDIUM|LOW"
    }
  ],
  "test_impacts": [
    {
      "layer": "L1|L2|L3|L4|L5|L6|L7",
      "target": "...",
      "reason": "..."
    }
  ],
  "unknowns": [
    {
      "question": "...",
      "reason": "...",
      "next_query": "..."
    }
  ],
  "claims": [
    {
      "claim": "每一个可作为正式结论的陈述",
      "evidence_refs": ["必须来自 code-analysis.json/evidence_refs"]
    }
  ],
  "sufficiency": {
    "state": "PASS|INSUFFICIENT",
    "reason": "..."
  }
}
```

## Semantic validation

RC8 会拒绝：

- 缺少 summary/changes/impact_chains/risks/test_impacts/unknowns/sufficiency；
- claims 不是数组；
- claim 无 evidence_refs；
- evidence_ref 不属于当前 snapshot 的允许集合；
- sufficiency.state 不是 PASS/INSUFFICIENT。

模型不能通过编造路径、类名、接口或数据库对象来补足未知项。无法从当前证据确认的内容必须进入 `unknowns`。

## Full PASS

完整 PASS 必须同时满足：

```text
structural_sufficiency.state = PASS
semantic_analysis.validation.state = PASS
semantic_analysis.sufficiency.state = PASS
overall_sufficiency = PASS
classification = CODE_ANALYSIS_SUFFICIENT
capability_state = VERIFIED
R1 = PERSISTENCE_VERIFIED
WorkItem = COMPLETED
```

## Runtime command

结构 Reality：

```bash
bash packaging/rc8/rc8-code-analysis-reality.sh \
  --center http://127.0.0.1:4098 \
  --node-id office-pc-01 \
  --operator test-user \
  --state-dir "$RC8_NODE_STATE" \
  --project-dir /d/PFC/bloan-prod-factory-cfg-center \
  --codegraph /path/to/real/codegraph.exe \
  --base-ref HEAD~1 \
  --head-ref HEAD
```

得到 `SEMANTIC_PENDING` 后，让 DSH 基于生成的 `analysis/code-analysis.json` 形成 `semantic-analysis.json`，然后重跑同一 snapshot：

```bash
bash packaging/rc8/rc8-code-analysis-reality.sh ... \
  --semantic-json /path/to/semantic-analysis.json
```

在 DSH 自动 Worker 接线完成前，此两阶段流程用于验证契约；不得把人工提供的 semantic JSON 宣称为“自主 Code Analysis Agent 已验证”。
