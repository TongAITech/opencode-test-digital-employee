# W0 缺口账本
按真实结果更新，不得把未做的任务写已完成。

| GAP | 级别 | 现状 | 下一动作 | 负责人 |
|---|---|---|---|---|
| WB-G01 | BLOCKER | naodeng/dsh-qa 为 PolyForm Noncommercial；未见银行商业授权 | 获取权利人书面授权，或保持完全独立实现 | A |
| WB-G02 | P0 | 行内 DSH 宿主与开源版兼容性未现场验证 | Windows Git Bash 宿主探测 | D |
| WB-G03 | P0 | 当前 RC7.2 SST 合同未显式建模 system_version 关联 | 增量关联结构、迁移和反例契约 | B/E |
| WB-G04 | P0 | RC7 admin 查询 API 不等于正式 Mission 控制 API | 设计权限/幂等/状态门禁接口 | E |
| WB-G05 | P0 | 六页面十个分区尚未形成实际产品验收矩阵证据 | 原型/独立实现逐项对账 | C/F |
| WB-G06 | P1 | ZSeven QA Node>=24.11，驱动需另装；银行离线兼容性未知 | 先可选化和能力探测，再决定上线 | E/D |
| WB-G07 | P0 | 同批次多需求/多版本/多 SST 真实数据未导入验证 | 通过真实样本完成 Scope 和追踪回归 | B/F |
| WB-G08 | P0 | DSH Teams 目标 32 的宿主并发/租约证明待查 | 同时核验可配置、实际并发、模型配额三层 | D/E/F |
| WB-G09 | P1 | RC8 中央数据接口与工作台语义尚未锁定 | 引入稳定 ID 与事件合同，避免未来重复开发 | A/E |

## 2026-11-09 新增施工缺口
| ID | 级别 | 当前可核查事实 | 关闭门槛 | Owner |
|---|---|---|---|---|
| WB-G10 | P0 | 原版功能对账新增 27 项，但新工作台 UI/实测未完成 | C 实现六页/十区，F 功能录像/接口/反例审查 | C/F |
| WB-G11 | P0 | 旧 rc7_admin API 不等于新 /api/workbench/v1；目前只有设计 oracle | B/E 正式 ACL/关联/命令/事件与 R1 同源验收 | B/E/F |
| WB-G12 | BLOCKER | PolyForm Noncommercial 商业授权缺失，W0 许可 Gate 尚未联入正式打包 | 权利人书面授权或可审计原创实现，F/法务检查文件清单及许可证 | A/F |
| WB-G13 | P0 | W0 首轮 CI 32 项 30 PASS/1 FAIL/1 ERROR；修复待新 HEAD 验收 | 新 HEAD 同 SHA 轻量 CI 全绿 + F 独立签收 | A/F |
| WB-G14 | P1 | SSE replay/命令幂等/关联数据库仅纯函数验证，非真正产品 API | E/B 提交事件持久化/事务/ACL/断线恢复负向测试 | B/E/F |
