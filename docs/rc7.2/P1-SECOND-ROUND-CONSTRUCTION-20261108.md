# RC7.2 第二轮 P1 暂存施工与验收账本（2026-11-08）

状态：SECOND_ROUND_CONSTRUCTION / SAME_HEAD_FAST_CI_PENDING / FINAL_PACKAGE_REBUILD_FORBIDDEN

## 已冻结且禁止无必要重建的第一轮

- P0 工程源码：`8c68f727ed4766111e6bdf5e6c8ca7728807aa36`
- PR #76 已合并的主线：`8a94341ae975fe600626cc44d9035f45040870b0`
- 11/11 正式 CI 成功；一次性 Windows ZIP 制品 #13601361916，run #42439374739 成功，SHA/冷解压/包内资格由该运行记录证明。
- 第一轮包不可被第二轮源码回归的 PASS 冒充；BANK_FINAL=false。

## 第二轮独立工作项

| Item | 工程交付 | 产品及异常门禁 | 完成条件 |
| --- | --- | --- | --- |
| P1-C12-SOURCE | C12 修正新打包工作流来源 | 精确 PR #76、source SHA、source branch/path/name、原生 GITHUB repository、成功的真实制品，绝不使用假 bytes | Windows 独立 C12 对既有 1.49GB Artifact 的实际下载、ZIP SHA、预检、解压、独立审计和可追溯的 QA artifacts |
| P1-STATUS | 取用历史 Draft PR #74 最小只读修复 | 空 ReleaseBatch 明确 NOT_BOOTSTRAPPED；重复或非法源拒绝；不写 R1、不创建 Node、绝不假 PASS | 同源码 Python3.8 / Windows/Linux 回归 |
| P1-C05-C08 | 逐项对账剩余原生 N7→N10 闭环 | 不允许 N10 旁路独立 Gate；失败 N8 与新 N7 独立重试，原 Attempt 不覆盖 | 工程完整产品流与原生回归；行内 Q7 另独立验收 |
| FIELD-Q3-Q9 | 真正银行办公 PC、DSH AgentTeams、BrowserSkill、4A、性能与安全 L1–L7 | 不能靠 GitHub Runner 或模型文字补造签名、R1 | 独立 Field evidence，不计入工程 PR 的 PASS |

施工约束：所有中途提交仅推 `work/rc7.2-p1-stage-20261108`，最多运行轻量 Python3.8/定向合同 CI。
独立 C12 在 QA 确认源码后由一次性 `work/rc7.2-p1-c12-verify-20261108` 推进触发，只审核既有 ZIP，不构建新包。
第二轮待完成的 C05/C08 相关生产缺口不得因 P1-C12 和 P1-STATUS 通过而声称完整核销。
