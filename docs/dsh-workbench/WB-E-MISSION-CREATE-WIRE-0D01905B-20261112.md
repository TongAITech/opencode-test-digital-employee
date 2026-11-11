# E 审查正式 Mission 创建请求与回执候选

审查对象 A #288 精确提交 `0d01905b3c38eae3e7360949da9f73ab7129380f`。接受创建输入限 goal、紧凑绑定与九字段描述共同进入摘要的方向。以下边界需要写入下一版，方可冻结正式事件与回执。

- 实际 `Mission` 构造和 `validate_rc7_mission` 都修剪 goal，中文、内部换行和非 BMP 字符保留。首尾空白应显式冻结一张码点表，并用现有 Python 构造与验证路径逐项对照。Python 的 trim 集合包括 U+001C、U+0085、U+00A0，保留 U+FEFF。禁止假定跨语言 trim 一致。服务端应先拒绝需要修剪的输入。冷查询须比较原事件的 goal 和身份再核规范摘要，避免先经过投影规范化掩盖原事件与规范字节不符。
- 实际普通 Mission 初始状态 REGISTERED、sufficiency UNKNOWN、revision 1、四个引用列表为空、latest_evaluation_id 为 null。实际 R1 首行另有 artifact_version 1，和 Mission revision 属于两个不同字段。正式版本均固定整数 1，布尔值拒绝。现有两次默认时间采样可以跨秒。正式端若选择一个登记时刻，应显式使用一个整数 Unix 秒填两个字段，从原事件读取时原值不变。
- 实际 JSONL append 先写入并 fsync，然后才应用投影并返回 `PersistenceReceipt`。在临时 R1 中向投影注入异常，调用没有返回回执，冷进程仍读到新 Mission。现有回执字段仅包含 status、event_id、seq、entity_type、entity_id、entity_version 及计数。采用固定权威下的原 event_id 作为 event_ref 的候选，另把 receipt_ref 在正式追加前分配并与原事件同写，或先冻结可重现的派生规则。无论选择哪种，重启后都需从唯一原事件确定回执。R1 的 event_id 和同 K 唯一性仍须由正式来源检查证明。PG 回执存在和当前投影均不能弥补原事件缺失。
- 原事件哈希必须读取固定快照中的确切事件字节。已接受的严格 JSONL 解析器返回解码对象，重编码对象会丢失原行表示。实际写入器使用文本模式，Windows 默认可把 LF 写成 CRLF。用标准库 newline 转换模拟验证，两个 JSON 内容相同的 LF/CRLF 原行在仅移除尾部 LF 后哈希不同。建议正式专用写入显式产生 LF，reader 明确拒绝正式事件中的 CRLF，或明确写入与读取都保留 CR 进入哈希。原字节不能在搬运或对账时发生换行转写。真实 Windows 仍待验。
- 请求与回执验证均须查当前正式源权限与原权威身份。回执只证明唯一创建已持久化，初始化与放行仍走各自门禁。查不到、歧义、连接中断或缺原字节按原 K UNKNOWN/HOLD，零自动重新分配。

探针执行基于此精确源及一次性 R1。复现了实际初始字段、同一构造两时间可不同、持久后投影异常、原行换行表示影响哈希。正式事件类型、持久回执方案、严格原字节读端、跨库写入以及真实 Windows/Host 均未验证。本报告为设计评审。
