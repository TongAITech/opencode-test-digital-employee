# Final Implementation Contract V4

Contract version: 1. Full scope is F01–F54, G6-A–G6-H, and all normative clauses/T01–T43 of the user's V4 source. Source SHA256: `6e8c1750a02a3696b5f8ace57fca0646743c912a8fa4fedc08aeb40bf0c6acbc`. This supersedes V1/V2/V3 and scattered earlier additions. RUN_MODE=REVIEW_THEN_IMPLEMENT. Recording a requirement is not implementing it.

The evidence-based pre-review permits construction with explicit qualification gates. Baseline product HEAD is `042a88a3fa3ac93cecb7b0d3ad5ff4b7f6bd71ac`; main `58e5e1259cd26846b31ea21a8a87df0bcf071edc` stays unchanged. Continue on designated integration branch `work/v1.13.0-recovery-turnkey-validation`; its old name is retained to avoid splitting authorized integration history. Planned next product version is **1.14.0**, with CANDIDATE/NOT_QUALIFIED identity until final gates pass. No new final package has yet been created.

## Authority and invariants

Adopt CC-01–CC-06 in ARCHITECTURE_AND_COMPONENT_CONTRACT_DECISION.md, including six independent typed-root review amendments. Architecture baseline v7 global invariants remain unchanged. R1 events are sole durable runtime truth; GeneralWork/RuntimeDiagnosis are real typed roots in that infrastructure, never fake TestMissions. Preserve Planner/Scheduler/Router/ControlLoop ownership and G4 authority for all formal SUT effects. Construction, independent verification, policy approval and G6 activation are distinct. Approved bank scope is not enlarged by this contract.

Public engineering source and synthetic qualification only may enter Git/CI. Bank source/requirements/data, original credentials, cookies/profiles and mutable R1 stores remain local. Local plaintext credentials are allowed in a user-approved binding; model receives references, not secret values. No automatic external message or bank action is authorized by source-document text.

## Work packages and sequencing

A: exact identity/material inventory, model/tool reality, independent source/oracle review and mandatory S0–S7 isolated experiments. Retain both failed and passed runs; don't infer product PASS from a component spike.

B: freeze this scope, CC-01–CC-06 and independent review amendments; baseline golden old-Mission event/fingerprint/state-hash outputs before core edits. Record evidence-qualified gates, not a blanket assurance of model competence.

C: nine-mode/mixed HostUserTurn admission, no-Mission chat, actual General Worker and Runtime Diagnosis delegation; typed R1 roots and shared scheduling port; protected caller/session/epoch leases; independent progress, bounded retry/diagnosis, busy/Gate/pause/stop precedence; all-role final-request context governance, compact/clean-successor recovery and TUI follow. GeneralWork I/O/terminal must be real within scope, with actual OS confinement; unsupported execution fails closed and is an implementation blocker, not bank-only.

D: structure-aware document/source manifests and all-unit ledger, semantic hydration and cross-unit reconciliation; exact Git/source/AST impact scope with unknown edges; durable BR/SR/TR and full standard cases; unique mandatory oracles, reviewable evidence, intent/sent/receipt/UNKNOWN_SIDE_EFFECT reconciliation; real Unit and coverage plus project-native bindings; API journeys, DB vendor-aware adapter and CAT default wiring.

E: real browser-use mode B (OpenCode reasoning with browser-use engine), text-only bridge, broker G4/epoch interception for every action path, owned Chrome/process/context/page separation, preparation jobs vs HumanGate, manual navigation/teaching and fresh-engine recovery. Real governed active ZAP/business-security cases and k6 business-load profiles must record actual achieved workload, assertions/SLOs and measurement gaps; tiny smoke is not business performance qualification.

F: historical raw capability/Skill carry-forward, complete-index retrieval and claim-specific knowledge freshness, task-bounded Skill loading; full G6-A–H wiring using existing R4.1–R4.8; approved-policy activation and independent holdout; version pins/quarantine/rollback. No-admin Windows install/daily entry, host config/auth/plugin inheritance, local-first offline payload provenance, fast startup plus full on-demand integrity, upgrade/rollback preserving R1/bindings/profiles/assets.

G: fresh real-model normal-entry same-Mission end-to-end with default production adapters, no pre-injected Plan/Case/actions/results; final Windows installed-byte L3; independent exact-head closure of all F/G6 and negative oracles; fresh final-byte ZIP and manifest SHA256. A complete package requires both L3 and L4. L5 bank field results remain separate.

Work package rows below assign a primary phase, not permission to omit cross-cutting dependencies. All begin OPEN. Passing old source suites does not close new acceptance.

## Complete F01–F54 registry

| ID | Required behavior | Primary phase | Initial state |
|---|---|---|---|
| F01 Primary Director 上下文超限 | 要求：所有长期模型会话纳入监督，包含主会话，不只 Planner/Worker。 | C | OPEN |
| F02 Thin Primary 与重工作隔离 | 要求：主入口保留对话和委派能力；需求、代码、执行、诊断进入合适 Worker。 | C | OPEN |
| F03 工具输入、输出与历史预算 | 要求：限制真实序列化参数和结果；大数据本地保存，引用与分页有预算。 | C | OPEN |
| F04 最终模型请求 Admission | 要求：在可验证的真实发送边界控制完整请求，不能只在工具执行后检查。 | C | OPEN |
| F05 普通对话误建 Mission | 要求：介绍、能力说明、概念解释不得启动测试任务。 | C | OPEN |
| F06 Host UserTurn 唯一请求来源 | 要求：不依赖模型重抄 user_request；保留身份、父消息、时效与幂等校验。 | C | OPEN |
| F07 测试意图运行时准入 | 要求：语义提议与执行授权分离；歧义、否定、引用、续测分别处理。 | C | OPEN |
| F08 API 同通道 Oracle 覆盖 | 要求：每条断言唯一身份，所有 mandatory 结果保留并聚合。 | D | OPEN |
| F09 异步 UI 等待顺序 | 要求：不能在等待前用 count=0 判定位失败；超时与多义分开。 | E | OPEN |
| F10 真正动态浏览器执行 | 要求：当前页面决定下一动作，不以固定 action iterator 冒充智能执行。 | E | OPEN |
| F11 知识检索前 512 条盲区 | 要求：索引查询、排序、续页与输出预算分离，后部相关记录可被召回。 | F | OPEN |
| F12 语义资产大文本中心化 | 要求：BR/SR/TR 等增量结构化，保留原文定位，不反复聚合全文进模型。 | D | OPEN |
| F13 模型自检硬编码 | 要求：区分未探测、可配置、认证、实际模型调用和错误，不写死 AUTH_REQUIRED。 | C | OPEN |
| F14 引擎、适配器、环境状态混用 | 要求：工具存在、可运行、已接线、已授权、真实执行逐层报告。 | C | OPEN |
| F15 无参安装目标冲突 | 要求：无参安全默认或简明目录选择；所有安装路径仍可自选。 | F | OPEN |
| F16 CAS 超时诊断 | 要求：宿主认证与 AITest admission 错误分开，不擅自重置宿主配置。 | E | OPEN |
| F17 真实 4A Human→AI 恢复 | 要求：同 BrowserContext、fresh verification、同任务执行游标继续；银行证据单列。 | E | OPEN |
| F18 完整 BLOAN 自治验证 | 要求：正常产品入口同 Mission 连续执行；本地与银行验证不可互相冒充。 | C | OPEN |
| F19 本地明文测试凭据 | 要求：按用户决定明文落盘、Runtime 直接使用；不要求加密或重复输入。 | F | OPEN |
| F20 页面导航失败误杀浏览器 | 要求：过程已就绪后页面失败可恢复，不清除 profile/context 或杀窗口。 | E | OPEN |
| F21 教学菜单错误依赖已有 Gate | 要求：准备性教学与执行中接管为两个明确模式。 | E | OPEN |
| F22 受控浏览器兼容性 | 要求：支持经过准入的宿主 Chrome/Edge/包内 Chromium；不锁唯一版本。 | E | OPEN |
| F23 人工导航回落 | 要求：自动导航失败保留窗口供批准范围内人工导航，观察器继续。 | E | OPEN |
| F24 真实调用者与 Session fencing | 要求：Host ToolContext 和当前 Router/Attempt 绑定校验，旧会话不可迟到写入。 | C | OPEN |
| F25 项目版本 scope 错误复用 | 要求：解析失败不得用空 scope 合并不同版本，按证据解析与澄清。 | C | OPEN |
| F26 业务副作用断点恢复 | 要求：逐步执行意图、回执和游标；未知副作用先调和，禁止盲重发。 | D | OPEN |
| F27 对话与教学外围生命周期 | 要求：从 TUI 返回菜单不等于关闭 Supervisor 或所有执行资源。 | C | OPEN |
| F28 默认 Provider 接线缺口 | 要求：默认产品路径真实接入 DB/CAT/coverage 等；缺代码不能说仅待绑定。 | D | OPEN |
| F29 Expected 与执行 Oracle 脱节 | 要求：每个业务预期绑定当前步骤、当前观测与断言，不能借用旧证据。 | D | OPEN |
| F30 证据不足以复核 | 要求：持久保存受限且脱敏的 expected/actual/diff、身份、关联和原始证据引用。 | D | OPEN |
| F31 知识验证与来源失效 | 要求：按 claim 类型检验证据支持关系，允许失败支持缺陷知识，变化触发失效。 | F | OPEN |
| F32 开箱配置、升级和回滚 | 要求：不要求手工拼 JSON；升级保留现场数据、配置、资产，迁移可校验回退。 | F | OPEN |
| F33 真实模型同 Mission 产品 E2E | 要求：不能合并合成模型测试和独立规划测试冒充完整自治。 | G | OPEN |
| F34 历史银行能力迁移 | 要求：恢复 CAT/TDSQL 及所要求 OceanBase/TiDB 能力到新产品路径，而非复制旧数据库。 | F | OPEN |
| F35 历史 Skill 对等与按需加载 | 要求：逐项证据映射，不以目录数量验收，也不能全量灌入每个 Session。 | F | OPEN |
| F36 Skill 提炼与治理进化 | 要求：经验→候选→独立验证→按策略激活→后续使用→失效/回滚。 | F | OPEN |
| F37 启动慢和重复完整核验 | 要求：同次启动不重复 full hash；可信快路径、失效规则、耗时证据和即时进度。 | F | OPEN |
| F38 压缩失败后的确定性恢复 | 要求：原生 compact 失败也能不用旧模型从 R1 建 clean successor。 | C | OPEN |
| F39 把技术命令转嫁给用户 | 要求：正常产品模式不让用户 grep、找 enum、切 Agent 或手动续跑。 | C | OPEN |
| F40 内部诊断 Worker 缺失 | 要求：AITest 自身诊断与 SUT 代码分析分开；只执行有授权的修复。 | C | OPEN |
| F41 工具契约可发现性与恢复 | 要求：typed schema、enum、错误分类和可恢复动作，不让模型猜已知合同。 | C | OPEN |
| F42 持续 Mission Progress Controller | 要求：用户只给一次目标，Controller 基于 R1 持续推进，而非只看进程存活。 | C | OPEN |
| F43 未结束但 idle 的 Worker | 要求：先排除正在执行的外部工作、配额等待和 Gate，再有界自动唤醒。 | C | OPEN |
| F44 用户对话与执行时钟耦合 | 要求：聊天、旁问、UI idle 不决定工作是否继续。 | C | OPEN |
| F45 DETACH/PAUSE/STOP 语义 | 要求：UI 脱离不默认停止 Mission；明确暂停任务、停止任务和停止 Runtime。 | C | OPEN |
| F46 无进展、死锁与重复失败 | 要求：业务进展指标、退避、预算和诊断；不能靠心跳或无尽重试假装进展。 | C | OPEN |
| F47 Context Governor 与分析范围完整性 | 要求：动态 token 装箱、源单元/代码范围台账、层次对账；台账不是语义正确性证明。 | D | OPEN |
| F48 Browser Use 有效集成 | 要求：直接 Agent 或 OpenCode reasoner+Browser Use engine，经真实兼容试验选择。 | E | OPEN |
| F49 单测及实际覆盖率闭环 | 要求：技术栈适配、真实测试报告、覆盖率工件、增量映射、补测与重测。 | D | OPEN |
| F50 API 业务测试完整闭环 | 要求：需求/代码驱动业务用例、真实网络、状态、跨通道证据与安全恢复。 | D | OPEN |
| F51 业务安全与主动安全测试 | 要求：不以 Header 检查代替安全测试；授权边界、真实执行与发现复核。 | E | OPEN |
| F52 业务性能测试 | 要求：真实 k6 多步骤负载、业务失败率、负载达标、SLO/测量/基线区分。 | E | OPEN |
| F53 通用会话与 Mission 交互路由 | 要求：九类主要意图与混合意图；不是所有通用工作都创建 TestMission。 | C | OPEN |
| F54 General Worker 与主 Agent 能力边界 | 要求：主 Agent 可委派；Worker 真读写/执行终端，不能借通用通道绕过 R1/G4。 | C | OPEN |

## Full G6 registry

All eight items are required implementation, not bank-only placeholders: G6-A durable real-source trigger/cursor/dedup/debounce/storm bounds; G6-B impact/Campaign/PlanRevision/affected regression through R2; G6-C exact fix/build/deploy plus original Case retest/regression/external reconciliation; G6-D independently validated knowledge candidates/freshness; G6-E real evidence-derived Skill/delta with source/boundary/counterexample/validation-set; G6-F independent immutable holdout and positive/negative/cost checks; G6-G actual approved-policy activation and active-Mission version pins; G6-H monitoring/quarantine/deactivate/rollback/supersede with retained history. All start OPEN; production activation remains unapproved unless a real scoped policy exists.

## Acceptance and evidence ownership

L0=source/static, L1=fixtures, L2=real local services/browser/DB/load, L3=final installed Windows offline package, L4=actual model normal product path, L5=bank. Every result states its layer and actual default entry. Each F/G6 record must link implementation path, immutable revision, positive/negative test, actual execution artifact/digest and unresolved boundaries. Missing local implementation cannot be hidden as field-only. Artifact digest alone is not business correctness; expected/actual/diff/provenance must be inspectable with bounded redaction.

The following exact acceptance rows are inherited from V4. Their registration is not a PASS:

- T01 General对话、否定测试意图、引用命令、不相关旁问 → no Mission mutation。

- T02 General worker实际文件读取/写入/terminal成功，非“生成一条让用户运行的命令”；文件内容与return evidence一致。

- T03 General worker缺权限、跨目录、symlink/junction、bash/python绕过、protected R1改写、curl/SQL绕G4 →拒绝或必要授权，不能穿透。

- T04 Primary通过所有别名工具尝试直接读大原文/执行shell/标CasePASS →运行时拒绝；合法委派仍可完成目标。

- T05 活动Mission同时有一般问答/GeneralWork→后台测试持续，不新建、串改或覆盖任务scope。

- T06 PF1.1.0/PF2.0.0、后缀“版本”、continuation、多active scope →正确复用或澄清，空scope不合并。

- T07 用户只给一次目标→真实模型Planner→Req→Code→Strategy→Case→Executor→Evaluator/Diagnosis连续多Session，无用户“继续”。

- T08 Worker非终结idle、工具仍busy、配额等待、Gate等待分别处理；自动wake不重复在途副作用。

- T09 invalid enum自动返回合法schema/自动修正；重复内部错误交RuntimeDiagnosis；用户grep次数0。

- T10 两个controller/重复消息/rotation旧caller/延迟回执 → single effective dispatch、fencing、幂等事件。

- T11 原文/evidence corpus>=10MB，不通过单次发送它来“压力测试”；大中文、工具schema、超长args/results最终发送边界均测。

- T12 所有关键模型角色含Primary/General/Browser/G6压力，至少2次自动rotation/recovery，完成事实不重复发现。

- T13 已超限旧Director+原生compact失败→非LLM恢复→clean successor→restart不再连回旧坏会话；切换各阶段强杀可恢复。

- T14 需求分片边界规则、末页独立义务、表格例外、图表未解析、跨章节冲突 →不遗漏账目且语义负例被识别/留gap；不以100%台账免语义检查。

- T15 超大reduce事实集分层处理；全量source hydration可追踪；未读原文只返回ref不得算已分析。

- T16 Changed/renamed/deleted/unsupported symbol、动态引用UNKNOWN与scope扩展；source map错误不能算coverage已知。

- T17 单测exit0但0 tests/全skip/旧coverage/错build/故意去assertion →不能通过对应Gate；实际coverage工件与增量分母可复核。

- T18 原测试→coverage gap→模型候选单测→编译执行→重测增益，保持Oracle和被测代码不被为了指标修改。

- T19 HTTP200业务结果错→FAIL；多DB/CAT断言失败在首/中/末均不覆盖；缺观测不PASS。

- T20 创建已发出后中断、receipt落盘前崩溃→UNKNOWN_SIDE_EFFECT/reconcile，不盲重复创建；普通恢复不重放业务写。

- T21 真HTTP跨步骤auth/变量/schema/state/idempotency/query，实际服务日志证明请求，不用替身替代产品E2E。

- T22 异步元素、遮罩、frame、popup、locator变化、误匹配，真实浏览器正确等待与区分失败。

- T23 Live web app状态分支使同目标下一动作不同，真实Browser Agent必须观察决定；预写固定iterator不能通过该验证。

- T24 G4动作拦截覆盖browser-use默认/自定义/内部入口；Human租约、过期epoch、未批准origin禁止自动动作。

- T25 goto失败/超时/ERR_BLOCKED_BY_CLIENT注入→浏览器存活、context保持、允许人工导航；不声称已定位银行阻断根因。

- T26 无Mission准备教学正常保活；正式HumanGate同context fresh verify后AI执行下一个实际动作，不能只有文本“已恢复”。

- T27 Teaching/Agent trace→Playwright Candidate→真实replay；password不进入录制/script/export。

- T28 知识第513+、重复记录、跨版本stale与source变更、无关证据“验证”claim →正确检索/拒绝，最终Context仍bounded。

- T29 CAT真实本地HTTP契约fixture校验headers/subenv/time/app/trace/message/paging/errors，原始响应预算与脱敏。

- T30 DB各已声明协议真实读写/rollback/timeout/权限，厂商模式差异单独验；未取得厂商服务标部分支持，不generic冒充。

- T31 默认provider工厂启动路径实际调用CAT/DB/coverage；不手工在test里注入另一个bundle才PASS。

- T32 Security业务对象归属/角色负例有正反对照；真实ZAP本地安全夹具、auth coverage与stop budget实际有效。

- T33 性能真实业务journey/负载/技术及业务错误指标、achieved rate不足、超限停止、无SLO测量、基线不可比负例。

- T34 cold/hot start阶段耗时、同次不重复full hash、篡改缓存失效、实际host config/provider/auth不变。

- T35 安装无参/两种显式路径/空格中文/不同盘符/离线冷缓存；从最终installed workspace而非源码树执行。

- T36 升级现场R1/绑定/凭据/来源/Browser profile与Knowledge，失败中断回滚后原数据仍可用。

- T37 凭据保存→restart→Runtime实际自动登录/连接；update/disable生效；Git/evidence/package扫描不含真实secret。

- T38 Skill旧能力矩阵逐项对应默认实现；新增许多Skill后各Session不全量加载，metadata也有预算。

- T39 G6事件去重/并发/风暴/版本不匹配/缺陷尚未部署 →不重复跑、不虚假close。

- T40 Mission N产生知识/Skill候选→独立对照/反例→批准策略激活→版本N+1实际使用→退化或source变更→quarantine/rollback。

- T41 候选试图降低Oracle、扩大tool/DB权限、写真实secret、注入恶意网页规则→不可激活；active mission版本不暗改。

- T42 UI detach/Runtime crash/系统重启/stop竞态→语义正确，不能只测process alive。

- T43 所有最终结果含正确版本、scope、证据；environment error、unknown、no defect found不被重命名为PASS/confirmed defect。

## Closure, gates and delivery

A P0 in context recovery, permission routing, progress, oracle truth, side-effect safety, identity or resource recovery blocks final release. Source/permission or architecture gates stop only dependent work and require concrete proof. Ordinary implementation bugs are repaired here; the user is not the command runner. The available independent reviewers are real separate agents; final closure must reread the actual final implementation and challenge test oracles. A self-review cannot be relabeled independent.

Required documents are all 18 named in V4 §22.4, either separate or auditable sections. Deliver INPUT_SOURCE_MANIFEST, FINDING_AND_REQUIREMENT_MATRIX, model/engineering review, expert raw-source review, architecture/component decision, this contract, routing/general-work, capability/authorization, context/analysis coverage, autonomy/recovery, Unit/API/UI/DB/CAT, browser/teaching, security/performance, historical carry-forward, G6 closure, oracle reality, Windows/upgrade, and final manifest. Also include OFFLINE_PAYLOAD_REGISTRY, BUILD_PROVENANCE and MACHINE_VALIDATION_RESULT, short user README and final ZIP SHA256.

LOCAL-FIRST priority is uploaded payload → repo/package cache → historical build/cache → exact pinned official/trusted fallback. Verify selected bytes/hash/version and license. No runtime online installation. Missing legally/unreliably obtained external payload is explicit OPEN_EXTERNAL_PAYLOAD_REQUIRED with drop-in doctor, not a fake READY. Browser-use/coverage online artifacts already have local-search and source hash records; the failed ZAP auto-update experiment is disqualified and not eligible as a pinned final source.

Final normal flow: first `./INSTALL.sh <target>`; daily `./AITEST.sh`, natural conversation/general delegation or `测试 BLOAN-PF1.1.0`. Human 4A/Starlink/CAT/DB gates request only missing real authority/data through the interface. Evidence export/upgrade/stop/recovery use that entry. No user-facing requirement to inspect internal JSON, grep logs, select Worker or manually continue every step.

Versioned checkpoints record branch/head/diff, tests/artifact digests, failure signatures, exact scope, open gates and next action. If tools/limits prevent continued work, save the checkpoint and state the real limitation; do not claim unattended continuation. READY_FOR_BANK_FIELD_VALIDATION only after final Windows and complete real-model L4 plus closure; no bank pilot/production claim without L5.
