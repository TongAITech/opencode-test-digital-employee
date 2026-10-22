# RC8 RC7 Permanent Regression Catalog

Status: FROZEN-CANDIDATE
Purpose: convert RC7 field failures and Reality Audit gaps into permanent RC8 regression scenarios. These scenarios must survive refactors and cannot disappear behind broad capability labels.

## 1. Rule

Each regression item must ultimately have:
- stable regression ID
- triggering condition
- expected invariant
- automated test where feasible
- bank Reality scenario where applicable
- product assertion where user-visible
- linked RC7 gap(s)
- closure evidence

A regression is not closed by documentation alone.

## 2. Governance / truth regressions

| ID | RC7 failure | RC8 invariant / regression expectation | Target |
|---|---|---|---|
| RC7-REG-001 | Director自己完成Worker工作 | Runtime producer must be actual Worker/Tool; Director cannot fabricate execution | W-A/B |
| RC7-REG-002 | Plan/model claim污染runtime truth | Plan/Event planes separated; runtime authorization rejects plan facts | W-A |
| RC7-REG-003 | installed plugin/tool 被误认为 capability verified | Capability state requires real probe + evidence + time | W-A |
| RC7-REG-004 | PLAN_COMPLETE 被当测试完成 | Completion gate requires sufficiency, not plan exhaustion | W-A/B |
| RC7-REG-005 | backend状态与真实执行漂移 | Product projection derives from R1/domain state; replay consistency | W-A/B |
| RC7-REG-006 | 旧证据被新Attempt复用 | evidence snapshot/attempt freshness gates | W-B |
| RC7-REG-007 | FAIL/BLOCKED历史被最终PASS覆盖 | Attempts append-only; history remains visible | W-B |

## 3. Session / context / recovery regressions

| ID | RC7 failure | Expected RC8 behavior |
|---|---|---|
| RC7-REG-010 | DSH上下文膨胀/响应极慢 | bounded worker context + checkpoint + session rotation |
| RC7-REG-011 | DSH session卡死 | mission/work item recover in new session |
| RC7-REG-012 | session文件丢失导致工作丢失 | durable Center/Node checkpoint remains authoritative |
| RC7-REG-013 | 换模型/新会话需要“继续完成”靠历史上下文 | new worker receives task-scoped durable handoff/assets |
| RC7-REG-014 | session knowledge 丢失后API/Auth再次猜 | verified Knowledge reused in new session |
| RC7-REG-015 | Center/Node restart后状态不可信 | deterministic recovery from durable state/R1/local queue |

## 4. Node/package regressions

| ID | RC7/RC8 field failure | Expected behavior |
|---|---|---|
| RC7-REG-020 | Node identity跟版本包目录绑定 | durable state outside package; upgrade preserves identity |
| RC7-REG-021 | 同node-id生成不同identity导致冲突 | launcher detects divergent state before Center registration |
| RC7-REG-022 | 开发机可跑，行内包不可跑 | clean-install bank smoke mandatory |
| RC7-REG-023 | 离线包缺工具/运行时临时下载公网 | manifest completeness + no hidden public-internet dependency |
| RC7-REG-024 | Windows中文输出导致Python解码异常 | byte capture + UTF-8/GB18030/local fallback |
| RC7-REG-025 | Windows Git Bash脚本与Linux行为漂移 | common protocol + platform adapter regression |
| RC7-REG-026 | 升级覆盖数据/状态 | upgrade/rollback preserves Center data/assets/Node state |

## 5. Maven/JUnit/L1 regressions

| ID | RC7 field failure | Expected behavior |
|---|---|---|
| RC7-REG-030 | L1全部BLOCKED_ENVIRONMENT：Maven/JUnit harness unavailable | real environment probe identifies exact Maven/JDK/dependency state |
| RC7-REG-031 | 已指定mvn路径仍报不可用 | probe uses configured command/path and evidence |
| RC7-REG-032 | stale Surefire XML污染Actual | only new/updated XML from current Attempt counts |
| RC7-REG-033 | Maven nonzero但历史绿XML伪PASS | process return code + fresh JUnit required |
| RC7-REG-034 | JUnit全绿被误认为L1充分 | execution green remains separate from L1 sufficiency |
| RC7-REG-035 | 没有JaCoCo/changed coverage仍PASS | L1 sufficiency requires configured changed-code coverage |
| RC7-REG-036 | Coverage不足没有自动补测 | Coverage Gap -> Delta Design -> Targeted Re-run |
| RC7-REG-037 | fail统一视为任务失败 | classify PRODUCT vs test/runtime ownership |
| RC7-REG-038 | PRODUCT bug被修测试脚本跑绿 | product failure preserved; defect route; oracle protected |
| RC7-REG-039 | Case缺前置/步骤/Expected/Assertion仍执行 | ExecutableSpec gate blocks dispatch |

## 6. CodeGraph/code-analysis regressions

| ID | RC7 failure | Expected behavior |
|---|---|---|
| RC7-REG-040 | CodeGraph已安装但代码分析Agent没调用 | Java change policy requires graph evidence |
| RC7-REG-041 | CodeGraph只探活/查询一次就称代码分析完成 | tool state separate from semantic/sufficiency state |
| RC7-REG-042 | graph evidence来自旧代码快照 | snapshot stale gate rejects |
| RC7-REG-043 | query失败后模型猜调用链 | required structural query fail-closed |
| RC7-REG-044 | 代码分析一遍过 | sufficiency evaluator generates follow-up query loop |
| RC7-REG-045 | 代码分析只有LLM一段话 | structured change/impact/risk/test-impact/evidence projection |

## 7. Requirement/design regressions

| ID | RC7 field failure | Expected behavior |
|---|---|---|
| RC7-REG-050 | 需求分析一遍过、无法证明充分 | independent sufficiency + delta analysis |
| RC7-REG-051 | BR/SR/TR后管为0/不可见 | durable analysis projection + requirement detail |
| RC7-REG-052 | SST只生成很少case仍直接完成 | case count never equals design sufficiency |
| RC7-REG-053 | TestCase Design没有循环优化 | Coverage Gap -> Delta Design loop |
| RC7-REG-054 | 用例未关联Risk/VP | canonical Risk->Intent->VP->Case trace required |
| RC7-REG-055 | Expected/Oracle来源不清 | oracle provenance required |

## 8. Test data/precondition regressions

| ID | RC7 failure | Expected behavior |
|---|---|---|
| RC7-REG-060 | Worker因没数据直接BLOCKED | attempt data discovery/build before declaring gap |
| RC7-REG-061 | 前置条件靠人工隐式准备 | explicit Precondition/TestData assets |
| RC7-REG-062 | 数据被多个任务冲突占用 | Resource Lease |
| RC7-REG-063 | 执行后数据不清理/不可复用 | release/cleanup/revalidation lifecycle |
| RC7-REG-064 | DB副作用没有readback | state/readback evidence where oracle requires |

## 9. 4A/Auth regressions

| ID | RC7 failure | Expected behavior |
|---|---|---|
| RC7-REG-070 | 4A回退历史cookie | stale-cookie path forbidden; fresh auth required |
| RC7-REG-071 | 默认“等待人工登录” | runtime skill first; Human Lease only for unavoidable challenge |
| RC7-REG-072 | auth过期后任务直接失败 | expiry detection + re-auth + same WorkItem resume |
| RC7-REG-073 | auth在新session失去已验证知识 | auth knowledge/version reused, credential runtime kept secure |

## 10. Route/API regressions

| ID | RC7 failure | Expected behavior |
|---|---|---|
| RC7-REG-080 | Agent猜API地址产生大量404 | no-route-guess policy |
| RC7-REG-081 | 正确route只留在session | Center route knowledge with provenance |
| RC7-REG-082 | 旧route永久复用 | freshness/stale/revalidation |
| RC7-REG-083 | API PASS无request/response/assertion | L3 evidence contract |
| RC7-REG-084 | 只测200不测业务副作用 | backend readback/log oracle where relevant |

## 11. L2 regressions

| ID | RC7 failure | Expected behavior |
|---|---|---|
| RC7-REG-090 | L2看似EXECUTED_PASS但不清楚测什么 | explicit component/DB ExecutableSpec + evidence |
| RC7-REG-091 | SQL成功被误当L2充分 | transaction/constraint/readback/risk coverage evaluator |
| RC7-REG-092 | mock-only替代真实DB集成 | required real DB boundary cannot be replaced by mock |

## 12. L3 regressions

| ID | RC7 failure | Expected behavior |
|---|---|---|
| RC7-REG-100 | L3 PASS无清晰步骤/断言 | per-step request/Expected/Actual/assertion/evidence |
| RC7-REG-101 | auth/route问题统一报API失败 | failure classifier routes AUTH/ROUTE separately |
| RC7-REG-102 | unexpected 5xx未作为关键失败 | required API scope has explicit server-error policy |

## 13. L4 regressions

| ID | RC7 failure | Expected behavior |
|---|---|---|
| RC7-REG-110 | awaiting ui worker dispatch却判PASS | no execution without real worker/tool provenance |
| RC7-REG-111 | zero-step UI case判EXECUTED_PASS | meaningful UI action count >0 required |
| RC7-REG-112 | 浏览器能打开就算L4 | Expected/Actual/assertion required |
| RC7-REG-113 | UI证据只有最终截图 | step/network/trace evidence where configured |

## 14. L5 regressions

| ID | RC7 failure | Expected behavior |
|---|---|---|
| RC7-REG-120 | L3/L4分开绿冒充E2E | one coherent correlated journey required |
| RC7-REG-121 | E2E无最终业务状态readback | final business oracle required |
| RC7-REG-122 | 跨应用交接不可追踪 | shared journey correlation + evidence |

## 15. L6 regressions

| ID | RC7 failure | Expected behavior |
|---|---|---|
| RC7-REG-130 | 无NFR也给PASS | BASELINE_ONLY when threshold absent |
| RC7-REG-131 | 单次短压测冒充性能充分 | workload/duration/threshold/resource contract |
| RC7-REG-132 | 只看平均响应 | percentile/error/throughput evidence |

## 16. L7 regressions

| ID | RC7 failure | Expected behavior |
|---|---|---|
| RC7-REG-140 | scanner不可用导致L7全BLOCKED | authz/role/negative tests remain independently executable |
| RC7-REG-141 | scanner finding直接当Confirmed | PROBE->CANDIDATE->CONFIRMED lifecycle |
| RC7-REG-142 | 权限矩阵无角色/对象边界 | explicit horizontal/vertical privilege coverage |

## 17. Evidence/report/product regressions

| ID | RC7 failure | Expected behavior |
|---|---|---|
| RC7-REG-150 | 用户看不出“测了什么” | report/task page answers scope/risk/steps/results/evidence |
| RC7-REG-151 | 查看完整报告跳转但内容弱 | structured report data first; export secondary |
| RC7-REG-152 | 页面只显示最终PASS | Attempts/gaps/coverage/history visible |
| RC7-REG-153 | Backend有1.2.0但页面BR/SR/TR/code/case/execution为0 | projection consistency and scope linkage |
| RC7-REG-154 | 假缺陷/无真实证据 | defect requires Expected/Actual/Assertion/Evidence/RCA |
| RC7-REG-155 | 系统配置不能表达环境/DB/帐号 | System Information domain + product surface |

## 18. Knowledge/skill regressions

| ID | RC7 failure | Expected behavior |
|---|---|---|
| RC7-REG-160 | 高质量分析随session消失 | verified central Knowledge |
| RC7-REG-161 | Skill文件存在就认为能力可用 | skill/package presence separate from capability qualification |
| RC7-REG-162 | 新知识覆盖旧稳定知识无证据 | candidate/verify/version/stale lifecycle |
| RC7-REG-163 | 全知识塞进上下文导致膨胀 | task-scoped resolver/cache |

## 19. Autonomous loop regressions

| ID | RC7 failure | Expected behavior |
|---|---|---|
| RC7-REG-170 | Node-local self-loop不可证明 | at least one real Gap->Repair->Re-evaluate chain |
| RC7-REG-171 | 后阶段Gap无法回正确前阶段 | Gap Router + route evidence |
| RC7-REG-172 | 修上游但下游旧绿不失效 | Dependency/Invalidation engine |
| RC7-REG-173 | 一次全绿直接TEST_SUFFICIENT | dedicated multi-dimensional sufficiency gate |
| RC7-REG-174 | Retry替代诊断 | failure classification required before retry |

## 20. Regression execution tiers

### Tier 1 - CI Contract
Deterministic unit/integration tests with doubles/fakes where appropriate. Proves rules/protocols only.

### Tier 2 - Local Reality
Real local subprocess/browser/db/tool where environment supports.

### Tier 3 - Bank Reality
Actual bank tool/system/project/environment. Required for BANK_REALITY_VERIFIED.

### Tier 4 - Mission Regression
End-to-end autonomous mission proving cross-stage route-back, recovery and product projection.

## 21. Release rule

Any future implementation that reintroduces a Critical/P0/P1 catalog regression blocks affected slice closure. Regression catalog results must be referenced from Capability Closure Matrix and Wave Delivery Gate reports.