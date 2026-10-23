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

## Center 最终裁决权

Worker/LLM 的 `SUFFICIENCY_EVALUATED` 只允许作为候选事实。任何可能解锁下游的 `SUFFICIENT` 都必须经过 Center 的冻结账本重算；原始 Worker 绿结论不得成为 MissionGraph 的恢复或解锁依据。

当前 REQUIREMENT_SUFFICIENCY 已固定 6 个 Center 必需维度：
- requirement-source-assertions
- requirement-atomic-statements
- requirement-traceability
- requirement-evidence
- requirement-normal-path
- requirement-open-question

Worker 少报任一维度时，Center 自动补 `UNKNOWN` 并判 `INSUFFICIENT`。只有 6/6 均满足且没有 active Gap 时，Center 才生成 `evaluator_id=RC8_CENTER_SUFFICIENCY_LEDGER`、`policy_version=center-ledger:*`、带 `ledger:*` Evidence 的权威 Evaluation。

进程重启/状态恢复同样只恢复这种 Center 权威绿结论；持久化的原始 Worker `SUFFICIENT` 不得在重启后解锁下游。

对于 CODE_SUFFICIENCY、DESIGN_SUFFICIENCY、MISSION_SUFFICIENCY，在各自冻结分母构建器尚未落地前，Worker 绿结论必须 fail-closed，禁止为了兼容旧链路继续直接 PASS。

## 当前验证边界

本合同与云端 CI 只能证明代码级确定性防缩水门禁。Requirement Center authority 通过后，仍需继续完成 CODE/DESIGN/MISSION 的冻结账本构建器，并在行内真实 TestRun 中验证实际分母、Evidence、新旧 Snapshot、Gap 与下游解锁关系。

在这些现场证据完成前：

```text
BANK_REALITY_VERIFIED = NO
TEST_SUFFICIENT       = NO
RELEASE_READY         = NO
Release               = HOLD
```
