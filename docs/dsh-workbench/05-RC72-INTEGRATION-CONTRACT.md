# RC7.2 执行内核集成契约
状态：W0_DESIGN_IN_PROGRESS / W0_NOT_FROZEN；W0 候选合同待 A01/A03/F00 正式签署；W1–W4 实现与现场 QA 未运行；A02 BLOCKED_LICENSE
参照：docs/rc7.2/01-AUTONOMOUS-TEST-RUNTIME-DESIGN.md、04-ADAPTIVE-TASK-DECOMPOSER-CONTRACT.md；W0 不修改这些冻结文件。

## 实体边界
ReleaseBatch→ReleaseBatchMission→MissionGraph(N1–N10)→NodeDelivery/SufficiencyGate→TestObligation→ETU→WorkItem→Attempt→Evidence→R1→NodeGate/Transitions→N10 Convergence。
工作台只承载查询与受控命令，不创建另一套 Mission 或 R1。原版 QA 本地质量任务是产品呈现，映射至 RC7.2 正式资产；数据不重复写回两个事实存储。

## 能力来源
N1 环境、部署、4A、模型/工具；N2 需求业务规则；N3 CodeGraph 变更影响；N4 用例/义务与充分度；N5 测试数据；N6 执行就绪；N7 L1–L7 真实执行；N8 失败诊断/重试；N9 缺陷复现/修复回归；N10 投产质量收敛。
不能强制所有 N 节点依次伪通过；按正式状态机合法边、回边与审批执行。真实记录中的 BLOCKED/NEEDS_REVISION/HUMAN_GATE 原样展示。

## 任务颗粒度
ETU 默认为 3–8 个同质用例、一个主要业务目标、代码切片、测试层级、数据策略、Oracle 家族和执行工具，预计不超过 15 分钟；例外必须有解释及证据。任务按事实变化增量重规划，不能一批大任务一直挂在单会话。

## 工具和证据
现有 BSK、BrowserSkill、L1–L7、CAT、DB、CodeGraph、Libra、API/部署路由保持兼容。可选 ZSeven QA 探索/回放经资源互斥租约和 CapabilityBroker 准入；预发行版 Node>=24.11及单独驱动需专门验收。
工作台 PASS/FAIL/INCONCLUSIVE/BLOCKED 必须映射标准执行结果和已验证证据；不能用模型说法、任务派发成功或浏览器截图冒充执行 PASS。

## 当前缺口
RC7 admin 的 rc7_admin/server.py 已有读 API、Mission detail/overview、用例写入等，但正式控制命令仍需明确协议、身份、权限与幂等；不能把拟议 API 视为已存在。
