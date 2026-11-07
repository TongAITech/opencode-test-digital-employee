# RC7.2 P0 第一轮施工：暂存分支与单次完整验收合同

状态：CONSTRUCTION_IN_PROGRESS / FULL_CI_NOT_ADMITTED / PACKAGE_BUILD_FORBIDDEN

## 问题和决定

2026-11-07 的 PR #76 原施工方法每次更新 PR HEAD 会触发多条
pull_request CI（ABCD-v3/v4、C07、C04、N8、RC7 继承回归等）。
Q2 与 Portable Transport 本身已经是 `workflow_dispatch` + `final_qualification`，
无需重复增加离线 ZIP 构建。

**现在禁止将每一个 P0 代码修复提交到 PR #76 的 head 分支。**

- 冻结待集成 PR：`work/rc7.2-p0-field-guards-20261107`，PR #76 保持 Draft。
- 中途代码、测试、审查：只提交到 `work/rc7.2-p0-stage-20261107`。
- 暂存分支 push 只运行 `.github/workflows/rc7.2-p0-staging-fast.yml`，
  单一 Python 3.8 语法/编译检查，无软件包构建、无浏览器下载、无完整回归。
- 暂存分支不发 PR、不触发其他工作流；在进入最终验收前不推进 PR #76 HEAD。
- 不能为了节约 CI 而删掉任何验收场景、测试用例或 Gate。

## 第一轮 P0 完工的强制条件（全部完成后才允许集成）

1. **GAP-01**：可信 `SCRIPT_READY_ADMITTED` 生产者或正式迁移路径已接入实际 Host。
   不得通过仅非空证据串调用 legacy gate；缺证据明确 HOLD，旧 Mission 无假恢复。
2. **GAP-02**：正式 ReleaseBatch Mission Host 在实际 DSH AgentTeams Captain
   创建、租约、身份、工具调用与 R1 上同一作用域；支持冷启动、接管、失效拒绝。
3. **P1-5**：冻结 Case → ETU → WorkItem → Attempt，全分母/幂等/正负例均有 R1 校验。
   任何缺失、重复、篡改拒绝执行，不跳过 Layer、Case、断言。
4. **P1-6**：真实 Runner + 独立 Reviewer + 文件/证据摘要 + 版本 + 签名 + NodeGate
   端到端核验；失败的 Attempt 不得被标记 PASS，重启恢复不得重复银行操作。

各项均须有：生产代码、定向正例、对抗负例、复现/重启/幂等测试和失败证据。
还必须完成同一 Mission 的整合检查，而非把 4 个独立组件通过当作 P0 关闭。

## 只在第一轮代码完全完成后统一验收与构建

1. 冻结暂存分支单一 SOURCE_COMMIT（完整 40 位）并记录 commit diff；
   先跑**一次** Python 3.8/3.11 定向集成检查和同 HEAD 完整回归。
2. 全部验收通过后，**仅一次**快进 PR #76 head 至最终源码提交，集中执行正式
   PR 工程资格门禁；不能再因代码小改反复发布或重新构建包。
3. 若 CI 失败，只修源码和目标失败测试，在暂存分支做快检，之后安排
   **一次**新冻结 HEAD 的正式验收；不得修改历史 FAIL 或伪造 PASS。
4. 同一最终合格 SHA 合入 `work/rc7.2`；从最终源码运行既有
   `rc7.2-windows-clean-unpack.yml` / `rc7.2-portable-transport.yml`
   的手动 `final_qualification=true`，**最后才执行一次 Windows ZIP 构建**。
5. 离线包只有 SOURCE_COMMIT、SHA256、完整负面/正面测试及行内 Q3–Q9
   Evidence 均合格才可称为已验收；BANK_FINAL 始终由现场真实验收决定。

## 不得混淆

- 中途“语法编译通过”不代表功能/跨平台/银行现场通过；
- 现有 PR #76 已触发的排队 CI 属于旧提交流水线，不是暂存分支新增任务；
- Q2/Portable Transport 是手动建包，保持这一设计；
- 不为了节约时间取消其他人的主线构建或修改其他施工分支的规则。
