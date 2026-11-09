# 工作台 API / 事件契约草案
状态：W0 设计草案；以下接口为待实现，非现有可用 API

## 查询 API
GET /api/workbench/v1/projects/{project_id}/release-dates
GET /api/workbench/v1/projects/{project_id}/release-dates/{yyyy-mm-dd}/scope
GET /api/workbench/v1/projects/{project_id}/release-dates/{yyyy-mm-dd}/quality
GET /api/workbench/v1/missions/{mission_id}/graph
GET /api/workbench/v1/missions/{mission_id}/workitems
GET /api/workbench/v1/attempts/{attempt_id}/evidence
GET /api/workbench/v1/capabilities
GET /api/workbench/v1/events（SSE）

## 受控命令
POST /api/workbench/v1/missions/{mission_id}/commands
命令需要 command_id/idempotency_key、expected_state_revision、principal/authorization、scope_ref、action、reason；服务端校验合法状态转移、权限、资源及人工门禁，并给出 accepted/rejected/revision_conflict 和正式 command_ref。
禁止绕过 RC7.2 控制面直接变更 R1 事件或 NodeGate。

## Scope 查询契约
每个业务查询必须包含 project_id 和 batch_id 或经 project_id+release_date 解析得到稳定 batch_id；需求/版本/SST 筛选传 ID 数组、按关联表校验，不能做简单字符串联想查询。
结果返回 scope、source_refs、truth_revision、as_of、records、pagination、warnings、gap_indicators；R1 真相缺失时返回缺口/未就绪，不返回空成功。

## 事件
mission.updated、workitem.updated、attempt.created、evidence.verified、nodegate.updated、batch.scope_changed、human_gate.requested、data.source_unavailable。
事件必须带 event_id、revision、project_id、batch_id、mission_id?、timestamp；前端按 revision 去重和恢复，断线后先拉最新快照再订阅。

## 典型错误
400 INVALID_SCOPE / VALIDATION_ERROR；403 FORBIDDEN；404 RESOURCE_NOT_FOUND；409 STATE_REVISION_CONFLICT / GATE_BLOCKED；422 ILLEGAL_ASSOCIATION；503 TRUTH_SOURCE_UNAVAILABLE。中文面向用户提示，保留可检索的英文错误码。
