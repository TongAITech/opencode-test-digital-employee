# B 对正式 Mission 第一阶段设计的复审

B 对 E245 精确源 `5be49d089cdf8e320c29276418e3069fe9c0e796` 给出 `B_DESIGN_ACCEPTED_FOR_STAGE1_PRESERVATION_ONLY`。审查范围为 typed 表示保真、独立 DTO、旧 wire 兼容及现有写入口的局部拒绝。参考 D248 `d3b7e2c4`、F249 `cb8d8672`、V3 `04ca9716` 和紧凑 wire `3266cb2d`。未发现本阶段 B 职责范围内的 P1。

- 第一阶段沿用既有 15/4/7 wire 和 PG `business_id` 语义。隔离解码核对原始身份和镜像，保留规范字节。结构校验、摘要、operation ref 和 `ScopeIdentity` 均无法签发权威或代替真实 PG 快照核验。实现范围排除 001–009、来源 profile、PG 数据及权限变更。核对 `27fb6cc7..5be49d08`，差异仅为 E 候选文档。
- 仅当 raw 三个保留键均缺省时可进入旧 ABSENT 路径。显式 null、partial、flat-only、镜像冲突或未知内部状态均须拒绝可写转换。历史日志按原语义回放，保留既有字节和诊断字段。隔离 clone/deepcopy 须保持规范内容，生产 bound 入口保持 HOLD。
- `to_payload` 在 `asdict`、拷贝或属性访问造成字段丢失前检查状态。`append_entity` 还须按本次实际归一化的全局 canonical `mission_id` 查当前目标，覆盖不同 release、ID trim、原行保留键为 null 的情形。按新 release 过滤会漏掉当前目标。拒绝须先于 durable acceptance 与 append，并验证原始日志、投影和旧行保真。跨进程陈旧投影和 raw writer 的闭包继续单独审查。
- PG `(project_id,batch_id)`、正式 `runtime_release_id` 和正式 `runtime_release_batch_id` 仍是三个独立身份。正式映射描述、复合快照 FK、008 PREPARE/回执、来源 catalog profile/锁协议和 HostFence 按后续增量分别验收。009 metadata_revision 不进入 Scope 身份，008 与 009 的依赖及部署 profile 按实际组合另审。旧数据缺正式来源仍 HOLD。

已核读当前 codec、来源 profile 和实际 `to_payload`、`_r1_payload`、`append_entity`。既有 codec 单测 9/9 通过。此结果验证当前结构工具，第一阶段新模型及 guard 行为等待精确实现源回归。现场状态为 `FIELD_NEEDS_BANK_TRANSFER`。
