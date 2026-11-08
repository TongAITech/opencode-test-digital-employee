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

## 第二轮运行时防重放施工

- Runtime Profile 名称严格限定自定义单目录，拒绝绝对路径、父目录与 symlink 指向受保护 profile。
- R1 Captain handoff 首次 takeover 写入唯一接管事实，相同新 Captain 冷重入返回同一接管事实，旧 Captain 与争抢者拒绝。
- DSH Worker 记录 WORKER_STARTED 后，重启重用同 Assignment 时拒绝重新调用工具；429/502/STREAM_CLOSED 的原始输出和 UNKNOWN 作用进入 R1，而非自动重放。
- 第二轮需要实际 DSH AgentTeams 成员与行内模型/授权真实证据，不能用模拟事件冒充 Field PASS。
- 既有 C12 独立 run #42444200781 真实结果：SHA + 解包通过，但独立完整性审计为 HOLD，原因 DSH_MAIN_NOT_CARRIED_AND_CHECKSUMMED（离线包缺少签名/校验的 dsh.exe）。绝不降低 C12 检查或重复构建未修复的源码包。

## C12 实体阻断的第二轮施工（未冒充完成）

- 已验证的旧包物理事实：独立 Windows C12 run #42444200781 在真实下载、SHA-256/干净解压后 `HOLD`，原因为 `DSH_MAIN_NOT_CARRIED_AND_CHECKSUMMED`。旧包不可追认 PASS。
- 新增 `rc7_release/rc72_dsh_main_payload.py`：必须提供获批 Windows x64 原生 `dsh.exe`，从保密 HTTPS 来源或授权本地文件获取，并与独立批准的 SHA-256 核对；不准用插件或伪造可执行物；拒绝非 PE32+/AMD64、错误 SHA、符号链接、冲突目标，写入包内受最终清单覆盖的位置。
- `rc7.2-portable-transport.yml` 在 GB 级运行时物化前执行获批 DSH 的强制前置门禁，之后由原 `_rewrite_manifest` 与 `CHECKSUMS.sha256` 一并封存。CI 配置依赖 Repository Secret `RC72_DSH_MAIN_URL`、Repository Variable `RC72_DSH_MAIN_SHA256`，可选 Secret `RC72_DSH_MAIN_AUTHORIZATION`。缺失则 fail-closed；这些字段的合法字节/核准来源尚无法在公开仓库代替银行授权提供。
- `AITEST.sh` 在正式启动（非 Q2 probe）时拒绝无包内 DSH，不会退回系统 PATH。独立 QA 进一步检查 x64/PE32+ 和清单/checksum。
- 第二轮来源拥有独立 `rc7.2-p1-one-shot-portable.yml`：只在实际 PR 合入、同源 11 项资格加四平台暂存 CI 都证明后，才允许专用分支一次性触发重建；原 P0 one-shot 和旧包不修改。C12 新增 `source_round=p1` 时仅接受该真实 P1 PR/工作流/分支/SHA，绝不把旧 P0 制品当作新包。
- **施工状态：C12_BUILD_CONTRACT_IMPLEMENTED / APPROVED_DSH_BYTES_PENDING / SECOND_ROUND_ZIP_NOT_BUILT / FIELD_PENDING / BANK_FINAL=false**。

## C05/C08 与 N7-N10 正式闭环施工

- 正式 `create_mission_driver` 已组合 N8 ProductRecovery、N10 NativeCoverageRepair + NativeCoverageRerun，保留真实原始 Attempt/Case/ETU 分母和独立终审，不采用测试 fixture 替代产品入口。
- 本轮新修复 `rc72_release_driver.py`：N9 READY/RUNNING 不再直接调用普通 `AcceptedScopeN9Service.complete`，而是复用唯一的 `_complete_gate('N9_DEFECT',batch)`，因此已批准专业复现存在时不得绕过专业处置门禁。新增 AST 反旁路测试，以及正式 factory/N8/N10 源级产品回归。
- 同期 Worker/Captain/Profile 可靠性代码维持原 Stage 状态：真实未知业务副作用、429/502/STREAM_CLOSED 不重复执行，R1 保留原失败。
- 四平台 No-ZIP 暂存 CI 新增 C12、N8 多轮、N9 专业 Gate、N10 产品组合测试；随后还需冻结同 SHA 运行 PR 全量资格。未有真正的银行 DSH Host、Q3–Q9、业务 R1 证据，不可将任何纯测试 PASS 当作字段核销。
- **施工状态：C05_C08_SOURCE_HARDENING / ENGINEERING_CI_PENDING / FIELD_PENDING / BANK_FINAL=false**。

## 最终执行顺序与不重复构建约束

1. 所有源码修改及回归先落在 `work/rc7.2-p1-stage-20261108`；CI 只能测试源码，不生成新离线 ZIP。
2. 确认同 SHA 暂存回归和 PR 继承矩阵，通过后仅一次合并主线。
3. 配置有批准记录的 DSH 主程序二进制 URL/独立 SHA，使用专用最终构建分支一次触发完整包；缺少二进制只能维持阻断，禁止伪造 PASS。
4. 新 P1 ZIP 再经独立 C12 `source_round=p1` 复验，随后到银行 PC 做真实 Q3–Q9；每项 R1 和缺陷验证保留旧失败记录。
