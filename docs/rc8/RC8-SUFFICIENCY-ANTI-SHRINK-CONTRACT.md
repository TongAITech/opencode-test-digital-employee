# RC8 充分度防缩水合同

## 目的

RC8 禁止复现 RC7 类“先缩小分母，再对缩水后的集合计算 100%，最后假通过”的充分度问题。充分度是 Center 根据冻结事实和 Evidence 计算出的确定性结论，不是 Worker/LLM 的自评。

## 冻结分母

每个充分度阶段开始前，Center 必须生成 `FrozenSufficiencyLedger`。Ledger 至少绑定 `TestRun`、被评估 Stage、策略版本、上游事实来源，以及不可为空的 `RequiredDimension` 集合。

分母来源：
- REQUIREMENT_SUFFICIENCY：RequirementRevision + ScopeRevision。
- CODE_SUFFICIENCY：CodeSourceSnapshot + ChangeSet + TraceabilityGraph。
- DESIGN_SUFFICIENCY：RiskTestModel + applicable layers。
- MISSION_SUFFICIENCY：前三层冻结账本 + Execution + Gap。

Worker 不得新增、删除或替换冻结 Required Set。

## 单项状态

每个 RequiredDimension 只有四种状态：
- SATISFIED：必须有 Evidence。
- UNSATISFIED：未满足。
- UNKNOWN：未评估、缺证据或事实未知；默认阻断充分度。
- NOT_APPLICABLE：必须同时有理由和 Evidence；“没找到”不等于“不适用”。

## Fail-closed 规则

1. 冻结分母为空：合同错误，不能 PASS。
2. Worker 未返回某个 RequiredDimension：Center 自动补成 UNKNOWN。
3. Worker 返回冻结集合外的 dimension：拒绝。
4. Worker 重复返回同一 dimension：拒绝。
5. 任一 UNKNOWN/UNSATISFIED：INSUFFICIENT。
6. 任一 active Gap：INSUFFICIENT。
7. Worker 自报 `sufficient=true` 仅用于审计，不能影响 Center 结论。
8. CoverageObservation 的 `total=0` 被拒绝，禁止把“没有建立分母”解释成 100%。
9. 只有所有冻结维度都 SATISFIED/有证据的 NOT_APPLICABLE，且无 active Gap，Center 才能输出 SUFFICIENT。

## RC7 缩水攻击验收

若真实冻结集合为 20 项，而 Worker 只返回 3 项且三项全部满足：

```text
required = 20
SATISFIED = 3
UNKNOWN = 17
effective ratio = 15%
result = INSUFFICIENT
```

绝不允许转换成 `3/3 = 100% -> PASS`。

## 下一层接线要求

本合同的 `CenterSufficiencyDecision` 是权威计算路径。MissionGraph/Center Service 必须进一步收口为：SUFFICIENT 只接受由冻结 Ledger 生成的确定性 Evaluation。直接由 Worker 构造 `SufficiencyEvaluation(result=SUFFICIENT)` 的旧入口必须淘汰或 fail-closed。

完成这一接线并通过 CI 前，不得宣称 RC8 充分度防缩水整体完成。
