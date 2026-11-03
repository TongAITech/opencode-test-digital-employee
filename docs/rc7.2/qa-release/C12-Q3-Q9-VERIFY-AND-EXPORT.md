# RC7.2 C12 / Q3–Q9 现场资格与 Evidence 导出操作书

状态：**QA TOOLING PREPARED / NO FINAL DELIVERABLE / NO BANK_FINAL**。以下工具仅核对真实文件/导出原始 Evidence，不会自动写 PASS、代替业务 Oracle 或赋予现场签名。

## 1. 必须先确定的身份

全部操作绑定同一 `work/rc7.2` **最终冻结源 SHA** 和完整包的 `SOURCE_COMMIT`。在覆盖 A/B/C/D 最终工程改动前，候选 Artifact 不能成为最终搬运包。先在干净目录解压完整 ZIP 并记录 ZIP SHA256、`CHECKSUMS.sha256`、`PACKAGE_MANIFEST.json`、`FULL-CAPABILITY-INVENTORY.json`、`RC72_RELEASE_IDENTITY.json`、平台版本、启动日志。

候选包已经有 13 个工具载荷库存组，但**库存组列表没有 DSH 主程序条目**；`dsh-plugins` 不是 DSH 主进程。最终 C12 需提供经许可可搬运的 DSH 主程序，在同一 Manifest/Checksum 中有可核对的路径与散列；如行业政策规定 DSH 只能使用预装主程序，则应取得用户签字的设计范围变更，不能私自降级“开箱即用”要求。Git Bash/Windows、目标 Linux bash 也必须分别实测。仅凭工具组存在不能判定 L1–L7 实际驱动成功。

## 2. 独立全载荷物理审核（Python 3.8+）

在 QA 源码仓库运行（不必把审计工具放进受审包以污染其哈希）：

```bash
python tools/rc72_qa_offline_audit.py \
  --package-root "/path/to/clean-extracted/PFC-AITest-DSH-Turnkey-RC7.2-BANK-WIN10" \
  --expected-source-commit "<FINAL_40_HEX_SHA>" \
  --dsh-relpath "workspace-template/runtime/dsh/dsh.exe" \
  --report "/separate/evidence/qa-physical-audit.json"
```

此处 `--dsh-relpath` **是待核实的示例约定，不代表现有包确实有该文件**。必须以实包真实目录为准；不传该参数时明确 `DSH_MAIN_PHYSICAL_BINARY_NOT_ATTESTED`，即使已有 `dsh-plugins` 仍 HOLD。脚本会复核源提交、Manifest/Checksum 文件 SHA256 和大小、13 个组、路径逃逸/符号链接；通过也只返回 `PHYSICAL_CANDIDATE_ONLY`，`field_verified=false`、`bank_final=false`。

还需从解压后包内 Python 实际运行：

```bash
python -m rc7_release.rc72_package verify --package-root .
python -m rc7_release.rc72_complete_payload_inventory --package-root .
python -m rc7_release.runtime_delivery_contract --package-root .
```

三条命令的执行解释器必须记录实际完整路径、SHA256 与 `SOURCE_COMMIT` 一致，禁止无提示降级使用主机 Python/Node/Java/Chromium。这里的 `python` 应是**明确选用的包内可执行解释器**，不是依赖 PATH 的系统 Python。Python 3.8/3.11 是源码工程资格矩阵，不得混淆为包内 Python 自身同时有两版本。

## 3. 现场 Q3–Q9 负面/恢复检查

| Gate | 要做的真实动作 | 不接受的替代 |
|---|---|---|
| Q3 | 在目标**信创 Linux 发行版/CPU 架构**用自身 bash 启动，记录 `uname` / distro / interpreter / bin 摘要、一次真实调用及异常；复核 `Q3-TARGET-LINUX-PROBE.sh` 结果 | GitHub Ubuntu proxy |
| Q4 | 网络断开或不可连接外部源时，干净目录解包、核对每文件 SHA256、本地启动必要工具，记录出站尝试/宿主回退 | 目录存在或 CI 下载阶段成功 |
| Q5 | 真实 BrowserSkill/CDP 录制、回放及 L4/L5 正式 Journey 消费；并发冲突必须被 BrowserLease 拒绝，含 R1/截图/录屏 | 浏览器 mock/直接脚本 happy path |
| Q6 | 由现场授权审批人给精确源/资产版本签署审批证据；故意试验错误版本签章拒绝 | `human_approved=true` fixture |
| Q7 | 完整真实 ReleaseBatch → Requirement/SST/Obligation/L1–L7 → N1–N10，检查原始义务分母、真实 DSH Tool/Skill、Oracle、Libra 与 Usage/UNKNOWN | N1–N10 只在 prompt 或 fixture 中出现 |
| Q8 | 真实 ANALYSIS/DESIGN/DATA/ENV/CAPABILITY/PRODUCT/PROVIDER 故障和 Browser 资源冲突，恢复进入新 Attempt；断电/冷恢复，旧 Evidence 不复活 | 仅组件冷恢复测试 |
| Q9 | QA 基于实际 Q1–Q8、N10 覆盖/缺陷/R1 和正式包签名逐条核销；仅全部通过才签最终放行 | 自动生成 `BANK_FINAL=true` 文本 |

每个 Gate 原始文件应明确操作员、被测环境、源 SHA/包 SHA、时刻、工具版本、命令/输入、调用证据、业务断言、失败类型、恢复后的新 Attempt 与原历史。**人工现场审批/敏感信息处理须走行内授权流程；导出前审核是否包含凭据/业务敏感数据。**

## 4. 不可伪造的 Evidence 导出

完整包已有下列文件之后，从解压根目录运行包内 Python 对脚本：

```bash
python packaging/rc7.2/QA-Q3-Q9-EVIDENCE.py \
  --package-root "/path/to/extracted-package" \
  --expected-source-commit "<FINAL_40_HEX_SHA>" \
  --output "/independent-evidence/RC72-Q3-Q9-RAW.zip" \
  --include "runtime-state/field/q3-target-linux.json" \
  --include "runtime-state/field/q4-offline.json" \
  --include "runtime-state/field/q5-bsk.json" \
  --include "runtime-state/field/q6-approval.json" \
  --include "runtime-state/field/q7-releasebatch.json" \
  --include "runtime-state/field/q8-recovery.json"
```

上述 `--include` 路径是现场事前约定的归档命名示例，必须先真实生成这些文件；**不存在会直接 FAIL，不会跳过或合成**。默认 `--r1-relpath` 是强制的 canonical 路径 `runtime-state/r1/event-stream.jsonl`；不得改成普通附件、另一个旧会话的 R1 或伪造事件流。工具强制携带 canonical `runtime-state/r1/event-stream.jsonl`、`SOURCE_COMMIT` / `BUILD_ID` / `RELEASE_FAMILY` / `RELEASE_STATUS`、`RC72_RELEASE_IDENTITY.json`、Manifest/Checksum/Full Inventory，按字节记录 SHA256 和文件大小，输出外部 ZIP 及 `.sha256`。输出只能在包外，不能覆盖旧归档或从 symlink/外部路径搬运；输入 R1/证据不被修改。导出索引所有 Gate 均标 `PENDING_INDEPENDENT_VERIFICATION`，Q9 `NOT_ADMITTED`，**导出成功不表示现场验收成功**。

### 独立复核导出 ZIP（必须在另一验收位置执行）

对导出的 ZIP 和同目录 .sha256，必须执行**第二次独立逐字节校验**，不得只相信导出程序自报成功：

```bash
python packaging/rc7.2/QA-Q3-Q9-EVIDENCE.py \
  --verify-archive "/independent-evidence/RC72-Q3-Q9-RAW.zip" \
  --expected-source-commit "<FINAL_40_HEX_SHA>"
```

校验器要求 ZIP SHA256 与外部回执匹配、目录内没有额外/重复/危险条目、索引声明与每个真实 ZIP 成员的 SHA256 和 size 一致、source/build/release/status/独立 Release Identity 身份匹配。R1 不仅要非空，还须符合本项目原生追加式 JSONL 事件的结构（序列从 1 连续递增、事件 ID / 类型 / 实体身份 / 实体版本 / payload 字段有效）。这些是**结构和字节完整性**检查，不会据此断言事件内容真实、业务 Oracle 正确或签名可信。伪造 q3–q8 已验收或 q9 BANK_FINAL、篡改 R1、补写未登记文件、使用另一源 SHA 均必须报 FAIL；即使返回 EVIDENCE_COPY_INTEGRITY_ONLY，**也只说明证据拷贝完整，不表示 R1 事实可靠、现场 Gate 成立或 Q9 已获授权**。Q3–Q9 的业务真假和审批真实性仍要独立人工/系统复核。

此验收导出工具使用 Python 3.8+ 标准库，QA 的正/负例通过同一独立测试矩阵运行；新工具只有同 HEAD 的 CI 实际成功才能算 QA 工具验收，不把组件测试视为行内 Field 通过。

## 5. QA 终态要求

在 A/B/C/D 最终同源工程验收（各类正/负/恢复、Python 3.8/3.11、Windows、目标 Linux）、完整包真实解压与启动、真实 Q3–Q9 完成前，任何 `FINAL`、`FIELD_VERIFIED`、`BANK_FINAL` 宣称均判 **REJECTED**。C12 是不可压缩交付门禁，不允许只提供源码 ZIP。
