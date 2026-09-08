停止按照旧 REC.3 Contract 继续零散修补。

执行：

REC3_FINAL_TURNKEY_PRODUCT_CONVERGENCE_CONTRACT_REISSUE

本次 Contract 覆盖此前 REC.3 中关于安装目录、bundled OpenCode、
host provider copy、exact OpenCode version pin 等旧要求。

不得重新设计 Architecture。
不得重做 G1-G5。
不得修改 canonical main。
必须保留当前 G1-G5 Runtime 能力。

Conversation != Project Truth。

Canonical repository =
TongAITech/opencode-test-digital-employee

Canonical main =
58e5e1259cd26846b31ea21a8a87df0bcf071edc

Active Recovery branch =
work/v1.12.0-recovery-turnkey-validation

Authorized starting HEAD =
6e1dd3dcfa2a8ad3f00e144c4550fe51791e8d11

ArchitectureBaseline =
v7 / FROZEN / UNCHANGED

R1 Event Stream =
sole durable Runtime Truth

legacy aitest.db Product Truth =
FORBIDDEN

G1-G5 =
PRESERVE / CLOSED / FROZEN

G6 =
HOLD

━━━━━━━━━━━━━━━━━━━━
A. Historical Raw Source Authority
━━━━━━━━━━━━━━━━━━━━

本 WorkItem 必须首先读取用户提供的：

1.
opencode-ai-test-digital-employee-v1.6.1-opencode-1.14.22(1).zip

2.
V1.9.4 surviving base package + patches

不得根据 Conversation 猜 V1.6 安装/启动方式。

必须从 V1.6 Raw Source 重建并登记：

V1_6_INSTALL_RUNTIME_LIFECYCLE_RAW_SOURCE_TRUTH

已知目标语义必须通过 Raw Source 再验证：

Distribution Package
→ install.sh
→ workspace-template materialized as final Workspace Root
→ cd installed Workspace
→ use host-installed OpenCode
→ OpenCode loads .opencode / AGENTS.md
→ natural-language test work

不得把 transport/package root 当正式 Runtime root。

━━━━━━━━━━━━━━━━━━━━
B. Installation topology repair
━━━━━━━━━━━━━━━━━━━━

V1.12 当前：

<install-root>/workspace-template/...

作为运行 Workspace 的拓扑必须取消。

正确安装结果必须是：

<USER_SELECTED_WORKSPACE_ROOT>/
    .opencode/
    AGENTS.md
    ai-test/
    runtime/
    tools/
    bindings/
    data/
    AITEST.sh
    installation metadata

即：

workspace-template/*
→ materialize directly into Workspace Root

正式运行 Workspace 根下不得再嵌套：

workspace-template/

安装目录不得锁死。

支持类似 V1.6：

./INSTALL.sh <parent> [workspace-name]

同时可以保留：

./INSTALL.sh --target <absolute-target>

默认目录只允许是 convenience default，
不得成为 Product Contract。

INSTALL_TARGET_USER_SELECTABLE = REQUIRED

安装程序必须：

- Windows Git Bash only
- offline
- 不启动 OpenCode
- 不要求 Model auth
- 不要求 4A
- 不要求 Starlink/CAT/DB
- 校验 package SHA256
- 安装 portable Python / Browser / CodeGraph / k6 / Java/ZAP 等本项目依赖
- 初始化 data/state/log/evidence/import/export
- 写安装 identity/provenance
- 不把 construction CI/docs/.github 等无关结构复制成 Runtime Workspace

━━━━━━━━━━━━━━━━━━━━
C. OpenCode Runtime policy
━━━━━━━━━━━━━━━━━━━━

银行 Product Runtime：

HOST_NATIVE_OPENCODE = REQUIRED

BUNDLED_OPENCODE_AS_DEFAULT_BANK_RUNTIME = FORBIDDEN

HOST_OPENCODE_EXACT_VERSION_PIN = NONE

不得：

- 强制 OpenCode == 1.18.3
- 因 exact version mismatch 拒绝运行
- 复制 host provider
- 复制 host auth.json
- 复制 token/API key
- 创建第二套 isolated provider/auth 世界
- 使用 package XDG_CONFIG_HOME 覆盖用户行内 OpenCode 环境
- provider 失败后偷偷 fallback 到 bundled OpenCode

AITEST.sh 必须从 installed Workspace Root：

1. capability self-check
2. shell resolve host `opencode`
3. 使用现有行内 OpenCode 自己的 provider/model/auth
4. capability probe，而非 version probe
5. 启动 G2.1 Control Loop
6. 启动/连接 host OpenCode
7. cwd = installed Workspace Root
8. 确认 .opencode / AGENTS.md / agents / tools 已加载

只检查真正需要的能力：

OPENCODE_PROCESS_READY
AITEST_WORKSPACE_LOADED
PROVIDER_READY
MODEL_READY
AUTH_READY
SESSION_CREATE
SESSION_READ
SESSION_MESSAGE
SESSION_STATUS
SESSION_ABORT
CONTROL_LOOP_BINDING

未来 OpenCode API 变化时：

OPENCODE_ADAPTER_COMPATIBILITY_REQUIRED

不得简单 VERSION_MISMATCH。

━━━━━━━━━━━━━━━━━━━━
D. Natural-language autonomous Mission
━━━━━━━━━━━━━━━━━━━━

安装启动后用户只输入：

测试 BLOAN-PF1.1.0

不得要求用户：

/aitest-plan
手工创建 Session
切换 Agent
手工调 Scheduler
手工 rotate

链路必须真实：

User
→ AITest Director
→ durable Mission / Goal
→ Planner Logical Agent
→ real Planner Session
→ semantic Plan
→ validate/freeze
→ Scheduler auto advance
→ G2.1 Session Router
→ Worker Logical Agent
→ real Worker Session
→ Requirement Analyst
→ Code Analyst
→ Test Strategist
→ Case Designer
→ Executor
→ Evaluator
→ Diagnosis / G5
→ convergence

必须证明：

Planner = WHAT
Scheduler = WHEN
Session Router = WHO / WHERE
Control Loop = session health / pressure / rotation / recovery

不得 Director 在一个 Session 内假扮所有 Agent。

━━━━━━━━━━━━━━━━━━━━
E. V1.9.4 Field Finding #1 — Context Explosion
━━━━━━━━━━━━━━━━━━━━

历史真实问题：

BLOAN-PF1.1.0
在单 Session 内快速 context too large，
新 Session 后重新寻找事实、丢失工作进度。

必须保留和强化：

- bounded read
- durable Task/Attempt/Checkpoint
- Session pressure monitor
- proactive automatic rotation
- successor ContextPack
- Mission/Task/LogicalAgent/root Attempt lineage preserved
- raw large Runtime/Evidence direct Read/cat forbidden

知识、日志、Browser trace、network、源码不得整体进入 Prompt。

至少加入 synthetic stress：

>=10MB source/evidence
→ bounded retrieval
→ >=2 automatic rotations
→ successor resumes same Task
→ no re-discovery of durable completed work
→ CONTEXT_TOO_LARGE_ERROR = 0

━━━━━━━━━━━━━━━━━━━━
F. Durable Knowledge / Knowledge Retrieval
━━━━━━━━━━━━━━━━━━━━

不得把“知识库”实现成把所有历史内容塞入 Session。

必须形成四层：

1. Source Truth
2. Durable Knowledge / Test Assets
3. Mission Working Memory
4. Session Context

知识类型至少覆盖：

Requirement
BR
SR
TR
Code Symbol / Code Impact
API
Page
Journey
Standard Case
Automation Asset
Execution Evidence summary
Defect / Root Cause
Historical Regression Signal

必须版本化、source-bound、revision-aware。

Knowledge 生命周期至少：

CANDIDATE
EVIDENCE_BACKED
VERIFIED
STALE
SUPERSEDED
REJECTED

只有 eligible / VERIFIED knowledge 才能进入执行 Context。

必须实现 offline-first：

Knowledge Index
+
structured relation/graph
+
scope filtering
+
revision/freshness
+
task-aware retrieval
+
ranking
+
dedup
+
hard context budget

本 Recovery 不要求为了“知识库”引入重量级在线 Vector DB。

优先使用当前 Runtime/SQLite/structured relation，
可选语义检索不得成为第二 Truth。

每个 Agent 只获取当前 Task 的最小 Knowledge View。

━━━━━━━━━━━━━━━━━━━━
G. Standard Test Case quality
━━━━━━━━━━━━━━━━━━━━

V1.9.4 真实问题：

没有看到有效标准案例，
案例无法支撑真实执行。

保留当前 R3.3 StandardTestCase，
但把 Prompt 约束提升为 Runtime Contract。

至少：

tc_id
requirement/sst
layer
objective
risk
preconditions
test_data
steps
expected_results
postconditions
oracle
evidence_requirements
execution_profile
automation_mapping
result

必须：

STEPS = NON_EMPTY
EXPECTED_RESULTS = NON_EMPTY
ORACLE = NON_EMPTY
EVIDENCE_REQUIREMENTS = NON_EMPTY

preconditions/test_data/postcondition
若确实不需要必须有 explicit reason，
不能用空值掩盖设计缺失。

禁止：

“执行正向数据”
“操作系统”
“符合预期”
“功能正常”

这类低信息占位案例通过 Runtime Validation。

━━━━━━━━━━━━━━━━━━━━
H. API real business-logic testing
━━━━━━━━━━━━━━━━━━━━

当前 HTTP status/json_subset executor 不足。

正式新增：

API_BUSINESS_LOGIC_TESTING = REQUIRED

必须支持：

- multi-step API journey
- request chain
- response extraction
- variable binding
- subsequent request templating
- schema/field assertions
- JSON path assertions
- not-null/range/set assertions
- cross-field business assertions
- safe arithmetic/business expression oracle
- business status/code assertion
- state-transition assertion
- negative/boundary testing
- idempotency testing
- previous-response → next-request
- cross-channel DB/CAT/log oracle when adapter bound
- Evidence per step

不得使用 unrestricted eval。

稳定 API Case 可以生成 pytest/httpx automation asset。

同时支持 AI dynamic API execution，
但两者共享同一个 StandardTestCase Truth。

Windows qualification 必须有真实本地 synthetic business service，
验证的不只是 HTTP 200，
而是业务规则错误能够被检测出来。

━━━━━━━━━━━━━━━━━━━━
I. UI execution — two execution paths
━━━━━━━━━━━━━━━━━━━━

必须同时实现：

1.
PLAYWRIGHT_SCRIPTED_AUTOMATION

2.
AI_BROWSER_INTERACTIVE_EXECUTION

两者都必须从 StandardTestCase 执行，
不得形成第二套 Case Truth。

UI Executor 至少支持：

navigate
click
fill
select
check/uncheck
hover
keyboard
wait_for
frame
popup/new page
assert visible
assert text/value
assert URL
assert state
network observation/assertion
screenshot evidence
multi-step execution

不能只支持：

goto
selector visible
text equality

━━━━━━━━━━━━━━━━━━━━
J. Human Teaching → Playwright asset
━━━━━━━━━━━━━━━━━━━━

V1.9.4 Field Finding：

打开受控浏览器人工操作后，
基本看不到 AI 接管继续。

Human Teaching 必须嵌入当前 ExecutionAttempt，
不是独立演示功能。

流程：

AI Step
→ 4A/unknown operation
→ HumanGate
→ Browser Lease AI→HUMAN
→ Human Drives
→ AI Observes
→ Canonical Action Trace
→ 用户完成
→ fresh verify same BrowserContext
→ HUMAN→AI
→ resume same StepCursor/Attempt
→ AI 自动继续后续步骤

同时把 Human action 生成：

Playwright Candidate

录制至少：

semantic page
action type
target
locator candidates
role/label/testid
frame
navigation
network relation
test-data placeholder

不得简单保存脆弱 nth/css trace。

必须：

recorded action
→ locator stabilization
→ generated Playwright candidate
→ replay validation
→ Automation Asset

自动提升为全局 Skill 仍然 G6 HOLD。

━━━━━━━━━━━━━━━━━━━━
K. AI Browser interactive testing
━━━━━━━━━━━━━━━━━━━━

除 Playwright Script 外，
需要正式 browser tool interface。

AI 根据：

Requirement
BR/SR/TR
Standard Case
Page Intelligence
frontend code
route/component/API code
current browser state

自主执行真实 UI E2E。

Browser tool action 经过 G4 Governance，
不能让模型随意 shell 执行未审计 Playwright。

AI Browser 模式必须可用于：

new feature
exploratory testing
logic boundary testing
Defect Hunter
script not-yet-available cases

━━━━━━━━━━━━━━━━━━━━
L. Login state / 4A Field Finding
━━━━━━━━━━━━━━━━━━━━

必须保留 persistent controlled BrowserContext。

必须验证：

AI launches/reuses controlled Browser
→ Human completes 4A
→ same BrowserContext survives
→ fresh authenticated/page/business verification
→ Human lease returns to AI
→ AI continues actual UI test

不能只验证：

Browser opened

也不能把用户输入“完成”当成登录完成 Truth。

━━━━━━━━━━━━━━━━━━━━
M. Evidence and large-data boundary
━━━━━━━━━━━━━━━━━━━━

Screenshot
DOM
Playwright trace
network log
CAT log
DB rows
large JSON

不得全文注入 Session。

Session 只得到：

summary
structured observations
digest
source_ref
evidence_ref

需要调查时 bounded/paged read。

所有 model-facing tool result 必须有硬大小预算。

━━━━━━━━━━━━━━━━━━━━
N. Validation strategy
━━━━━━━━━━━━━━━━━━━━

不得停在 Design。

执行：

Raw Source Recon
→ reissued installation/runtime contract
→ implementation
→ focused tests
→ G1-G5 regression
→ Windows qualification
→ final ZIP

必须新增真实 Windows tests：

1.
Install to arbitrary target A

2.
Install to different arbitrary target B

证明：
NO_HARDCODED_INSTALL_ROOT

3.
workspace-template materializes as Workspace Root

4.
host `opencode` resolved from PATH
而非 package bundled OpenCode

5.
exact version mismatch is not a gate

6.
host config/auth environment is not overwritten

7.
AITest .opencode/AGENTS/tools load

8.
Control Loop attaches to same OpenCode runtime

9.
Natural-language start_test admission

10.
multiple Session routing/rotation/resume

11.
>=10MB context stress

12.
valid StandardTestCase validation

13.
API multi-step business logic failure detection

14.
UI multi-step Browser execution

15.
Human Teaching → Playwright candidate → replay validation

16.
HumanGate → same BrowserContext → AI resumes

17.
Evidence remains bounded

真实行内：

wizard-local/aicoder-plus
4A
BLOAN
Starlink
CAT
TDSQL
incremental coverage platform

允许：

BANK_FIELD_VALIDATION_REQUIRED

但不得把这些未验证项冒充 PASS。

━━━━━━━━━━━━━━━━━━━━
O. Offline dependency policy
━━━━━━━━━━━━━━━━━━━━

Build machine：

LOCAL_FIRST
→ existing repo/cache/upload
→ trusted online exact-pinned fallback only if genuinely missing

Bank runtime：

OFFLINE_ONLY

所有新增 payload：

version
sha256
provenance
license
registry

不得运行时 pip/npm/playwright install。

━━━━━━━━━━━━━━━━━━━━
P. Version identity
━━━━━━━━━━━━━━━━━━━━

不得继续把旧错误拓扑下的 V1.12.0 ZIP 原样复用。

本次重构完成必须产生新的 package identity。

可以是 patch/minor，
但必须：

NEW_PACKAGE_IDENTITY = REQUIRED

不得让两个不同产品拓扑拥有同一个 final package identity。

━━━━━━━━━━━━━━━━━━━━
Q. Closure gates
━━━━━━━━━━━━━━━━━━━━

只有以下全部 PASS 才允许生成 FINAL ZIP：

V1_6_INSTALL_LIFECYCLE_RESTORED
USER_SELECTABLE_INSTALL_TARGET
WORKSPACE_ROOT_TOPOLOGY
HOST_NATIVE_OPENCODE
NO_EXACT_OPENCODE_VERSION_PIN
HOST_PROVIDER_AUTH_PRESERVED
AITEST_WORKSPACE_LOADED
CONTROL_LOOP_BOUND
NATURAL_LANGUAGE_MISSION_ENTRY
AUTONOMOUS_PLANNER
SCHEDULER_AUTO_ADVANCE
SESSION_ROUTER
AUTO_ROTATION
SUCCESSOR_RESUME
CONTEXT_STRESS
TASK_AWARE_KNOWLEDGE_RETRIEVAL
STANDARD_CASE_RUNTIME_VALIDATION
API_BUSINESS_LOGIC_EXECUTION
UI_MULTI_STEP_EXECUTION
AI_BROWSER_INTERACTIVE
HUMAN_GATE_BROWSER_RESUME
HUMAN_TEACHING_TRACE
PLAYWRIGHT_CANDIDATE_GENERATION
PLAYWRIGHT_REPLAY_VALIDATION
BOUNDED_EVIDENCE
G1_G5_REGRESSION
WINDOWS_FULL_QUALIFICATION
FINAL_ZIP_SEALED

最终必须输出：

FINAL_BRANCH =
FINAL_HEAD =
PACKAGE_VERSION =
WINDOWS_RUN_ID =
WINDOWS_JOB_ID =
FINAL_ZIP =
FINAL_ZIP_SHA256 =
ARTIFACT_ID =

以及：

BANK_FIELD_VALIDATION_REQUIRED = true

执行模式：

不要停在设计。
不要因为普通 implementation failure 回来问 Product Owner。
自主 root-cause / repair / rerun。

只有以下情况才停止问用户：

PRODUCT_OWNER_DECISION_REQUIRED
ARCHITECTURE_CHANGE_REQUIRED
真实银行凭据/4A等 HUMAN_ACTION_REQUIRED
无法从现有 Raw Source / Git Truth 解决的 HARD_DEPENDENCY_FAILURE

其余全部自主推进到 FINAL ZIP。