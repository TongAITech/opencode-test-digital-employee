# F 独立复验 Mission Scope 阶段一写入身份一致性

接受 PR #259 精确提交 `450d2932cd7261b733cc5832c5fddf8e0b5e5482` 的阶段一结构保留与兼容边界。阶段一的隔离 Scope 数据不授予正式写入权限。

独立临时 R1 探针先保留一个有 batch 字段的历史 Mission，验证使用带空格的同 ID 更新触发 `MISSION_SCOPE_NOT_ADMITTED` 并且 R1 字节不变。随后合法未绑定 Mission 进入更新，在 canonical 查询期间改变原 Mission 的 ID 和引用列表。收到回执的 ID 与原查询一致，冷回放只更新原目标并保留分离的引用列表、状态和传统 release override。历史带批次字段的行完整不变。

隔离工作树运行工作流同源集合 252 项通过、0 跳过。候选测试包括拒绝非标准字段、阻止常规序列化访问非受信复制路径、Scope 字典边界、已有受保护目标、绑定冷回放、打包后的纯模块导入。GitHub [43066853268](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/43066853268) 两任务实际 checkout 同一精确提交，Python 3.8 和 3.11 各 252 通过。

同一精确本地工作树使用 PostgreSQL 17.6/ICU 执行 E01/E02 PostgreSQL 和 HTTP 测试 70 项通过、0 跳过（41.280 秒）。E01 fixture 使用 canonical Mission wire，私有实例字段不进入兼容 R1 数据。GitHub [43066853005](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/43066853005) 的组件回归通过，使用 PR 合成 checkout，精确候选的实库结果以上述本地执行为准。

早期 F262、F266 拒绝仍属于各自原提交。后续正式 creator、R1/008 原子准入、真实宿主及行内运行仍需各自实现和验收。
