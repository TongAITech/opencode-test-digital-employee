# F 独立验收 E01 Evidence 读取后的授权复核

接受 PR #274 的精确提交 `05b6b9c90e9a2baa7fc8424dca25bf7480100690`，范围是现有 E01 quality 只读接口的授权时序。

独立探针在隔离工作树，以真实 PostgreSQL 17.6、HTTP 和冷 R1 fixture 运行。探针先调用原始文件校验、确认哈希匹配，随后在返回校验结果前以数据库连接提交 Alice 的 ACL 删除。旧提交 `b05f7f3e` 返回 HTTP 200 并包含 Evidence。新提交返回 HTTP 403，响应没有 Evidence。两次执行中，R1 字节保持一致。无 Evidence 时，两个版本均返回 200 与 EVIDENCE_MISSING，且均未进入文件校验。独立探针复授权限后取得新的 HTTP 200 和原 Evidence 哈希状态。

在旧提交执行候选回归，写权限降级场景返回 200，预期 409，实际红灯。新提交 E01 文件整套真实 PostgreSQL 测试 36 通过、0 跳过（18.291 秒），包括降级时 409、刷新 200、完整撤权 403 以及 R1 字节一致。PR [组件 CI](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/43066557699) 与 W0 检查成功。精确提交证据来自本地隔离工作树。

本次范围是 E01 已授权快照读和读取过程中的项目权限变更。正式运行批次映射、生产 Evidence 存储、真实 DSH 和行内 Windows 待各自验收。
