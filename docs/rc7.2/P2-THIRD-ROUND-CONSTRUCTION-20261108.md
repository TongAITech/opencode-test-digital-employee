# RC7.2 第三轮 P2 工程施工与真实验收边界（2026-11-08）

## 基线

- 继承主线 `work/rc7.2`：`67f92d735c8e6e5ac5ad6e7403c63678bfc65455`。
- 第二轮 PR #78 已合入，13/13 同 SHA 工程源资格、合并后 3/3 主线运行 PASS。第二轮 Windows P1 实体 ZIP、C12 真实主程序、银行 Q3–Q9 不在通过范围。
- 本轮施工分支：`work/rc7.2-p2-stage-20261108`；中途不构建 GB 级 ZIP。

## P2 本次可工程落实的事项

| 范围 | 施工变更 | 否定验收 |
| --- | --- | --- |
| C04 N9 产品 Gate | 从签名专业任务、差异、N9 DSH 分析、复现授权、真实复现、独立处置任一可信 R1 历史触发专业门禁，不能仅等到复现成功以后才切换 Gate | 提前差异、无专业 provider、N9 仅专业 provider、全空清洁路径；不追加 R1、不自动重复业务 |
| C12 DSH 批准来源 | HTTPS 下载禁绝任何跨 URL 重定向；Authorization 不随跳转泄露；响应/异常脱敏；包内上级目录符号链接和大文件在复制前拒绝 | HTTP 302、泄漏错误文本、注入 Header、包外目录逃逸、本地超大源 |

P2 仍未核销：C03 所有 N8 语义回边的银行实体行为，C04 真正专业 RCA/人工复现后修复回归（已有生产组件但银行 Field 未验证），C07 全角色 AgentTeams 实体调用，C12 获准分发 DSH 主程序来源+独立 SHA256、真实 Windows ZIP 和独立 C12 物理检查，行内 Q3–Q9。代码 PASS ≠ BANK_FINAL。

## 工程验收

- 第三轮同一 SHA Linux/Windows Python 3.8/3.11 P2 NO-ZIP 回归；PR 同 SHA 继承 CI 复核通过才合并。
- 全部代码变更批量提交、验证，最后在批准真实 DSH 主程序到位时才构建完整 ZIP 一次。
- `FIELD_VERIFIED=false`, `BANK_FINAL=false`，没有银行真实 R1 时不能上报 Mission 完成。
