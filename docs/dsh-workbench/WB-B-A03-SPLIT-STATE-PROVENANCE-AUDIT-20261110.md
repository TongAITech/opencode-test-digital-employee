# WB-B W0 追加设计见证：SST 拆分状态与来源审计不可篡改

日期：2026-11-10
Owner：B（领域模型）
来源基线：A work/dsh-wb-w0@a3555b187eb35d27a2d712313dd8ea7daa28915f
类型：W0 DESIGN_WITNESS / F_REVIEW_REQUIRED；不是 W1 PostgreSQL 实现或 QA_PASS。

## 核心发现与影响

1. 原 `brv.split_state` 是可写字符串。即使 `brvs` 中已有 6 条真实 SST 链，测试 fixture 仍全部保存 `UNSPLIT`，B06 如果直接把此列返回给 UI，将把已拆分的需求—版本误标为“待拆分”，形成错误业务 Oracle。
2. 原 `sst_source_trace`、`authoritative_req_version` 和 `authoritative_link` 的来源修订/引用可以静默 UPDATE；其中无消费者的来源链甚至可直接 DELETE。即使有真实 FK 约束也挡不住“非空但伪造的新来源 ref”。这破坏来源证据可追溯和历史审计。

## 本轮 W0 设计修订

- 新增 `scope_rows_with_states` 的投影视图式见证：先以真实 `BRV LEFT JOIN BRVS`、项目及批次 ACL 取出合法链接，再从每一行 `sst_id IS NULL` 推导 `UNSPLIT`，否则为 `SPLIT`；完全不信任可变 `brv.split_state`。合法 BRV 未拆分返回 1 个 NULL SST 行，不虚构 SST；拆分后零伪 UNSPLIT 行。正式 B06 必须用单次数据库一致性快照同时读取结果与版本水位，不能以此 Python helper 充作 HTTP 实现。
- 在原 SQLite W0 DDL 中为 `sst_source_trace`、`authoritative_req_version`、`authoritative_link` 分别添加 BEFORE UPDATE/DELETE fail-closed trigger。产品 PostgreSQL 方案须采用来源修订不可改写、正式来源 supersession/退役另留审计，不允许通过 SQL UPDATE 改写已证明的历史链接。
- 原 FG18 同一上游 raw SST ID 在不同系统版本合法复用仍允许；项目/系统版本/SST 三元 trace FK 和 source_ref 完整性逻辑保持。F 独立原测试不改写。

## 新增 W0 负向用例

- 被人为写错的 `brv.split_state` 不得影响根据真实 verified SST link 推导的状态；
- 未拆分的合法 BRV 挂上已验证来源的 SST 后，Scope 必须从 UNSPLIT 变 SPLIT，不能同时含假 NULL 行，关系版本 CAS 生效；
- 来源 revision/ref 即使不是空白也不得静默改写；无 BRVS 消费的 verified link 也不可静默删除；失败后原值与关系计数不变；
- 未授权 Project 403 优先于资源存在性、授权后 404、B2 不能自动继承 B1 的已拆 SST。

## 验收与依赖

- 这只是设计见证；生产环境的撤销/更正必须设计显式业务变更审批和来源审计，不代表永不允许合法修正。项目 BUSINESS_TZ 未批准仍 HOLD。
- 未启动 WB-B01/B02 正式 PostgreSQL/迁移/服务/API；不签 IMPLEMENTATION_QA_PASS。B06 正式分页/游标/来源/拆分状态仍要实库实测。
- F PR #106 已完成 C 原型/FG23 的独立审查，不等于全 W0 设计接受；最新 A@a3555b187eb35d27a2d712313dd8ea7daa28915f 的 W0 仍 NOT_FROZEN，A02 商业授权另阻断。
- B 独立 PR 本次只修改 B-owned test 与本设计见证文件；A/F 复核后由 A 将证据追加 08/09/10，原红灯不擦除。
