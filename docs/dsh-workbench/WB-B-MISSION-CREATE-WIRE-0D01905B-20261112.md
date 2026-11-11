# B 审查 Mission 创建请求与回执编码

审查对象为 A #288 精确 `0d01905b3c38eae3e7360949da9f73ab7129380f`，SQL 对照为 #278 精确 `e6eccf1d9a137ae4c9844efbad67f7e57ec155e4`。接受有界的纯编码和测试向量施工。正式 008 PREPARE 及创建仍待下面的增量闭合。

## 选择与事务

- goal 是创建输入，放入正式 selection 的规范 `command`。应冻结精确字段、版本及哈希域，核新旧存量隔离。隔离夹具的无 command selection 不能解释为正式记录；首次正式安装可使用独立迁移边界，若需要共存则用显式版本分离并定义旧行处置。
- 当前夹具按原 K 在同一个事务 advisory lock 下查 selection 字节、摘要和原 context，再决定复用或插入。正式入口也要在锁内比较这三者，再调用预留。改 goal 在分配前拒绝。相同请求复用原 PREPARE 保存的完整身份、原快照及 request bytes；新读取的实时 Scope 不替换已有 intent，正式提交仍复验当前权限及 Scope。原主体 lookup 的权限与新 PREPARE 分开验。
- 真库目录显示 `request_bytes` 为 1..65536 的 bytea，`request_digest` 只验证十六进制形状；现有夹具用无前缀 SHA-256 持久保存 215 字节的夹具正文，已真实提交且冷重试成功，该摘要与正式领域分隔的 SHA-256 不同。正式 SQL 应校验 `SHA256(UTF8('dsh.mission-create.v1' || LF) || request_bytes)`，端口须严格解析并重新编码，检查全部身份、摘要和存储列。库端哈希只校验字节完整性。
- 真库复制原表实际 CHECK 到临时表测试，65536 字节通过，65537 返回 SQLSTATE 23514。组合输入达到 78407 编码字节，使用长度 4096 的合法 goal（非空边缘，内部 U+0001）和 384 字节的非空标识。各字段原始 UTF-8 上限与编码后总上限必须同时成立。selection 还含筛选数组，亦须独立验编码后的总上限。正式入口在持久预留前必须按已审标识分配上限证明能容纳，或在同一事务中无残留地拒绝。摘要覆盖上限内预映像，领域前缀长度不计入 bytea。
- PostgreSQL text 拒绝 NUL。持久列使用的 ID、context、event/receipt ref 还须符合 008 的 1..384 UTF-8 字节约束；不能仅依 JSON/Scope codec 判定可入库。goal 内换行、控制字符及非 BMP 按规则编码；黄金向量固定控制字符转义及首尾空白的精确规则。

## 回执与恢复

- 现有表可存 authority 内唯一的 event_ref、receipt_ref 及 receipt_hash。重复 K 要重取唯一原事件和固定原回执，核 request digest、映射、绑定、operation、各引用及字节哈希与已有记录。相同才复用。冲突不得覆盖、另配身份或自动重发。PG 已写入 intent 而回执未回时，原权威不可查保持 UNKNOWN。
- 以权威保存的原事件字节计算 event_sha256，不能用投影或重编码。需在签审中明确 CRLF 和已迁移账本的行为，保持先后同一字节规则。回执哈希由经审适配器核原回执字节后写入。因为 PG 不保存回执正文，数据库无法单独重验原字节，fixture 中回执引用插入不得当作权威验收。
- 在 PostgreSQL 17.6、UTF8、8192 字节块的隔离库完成上述目录、持久重放及长度探针。未修改 #278 实现、正式迁移、R1 或共享台账。
