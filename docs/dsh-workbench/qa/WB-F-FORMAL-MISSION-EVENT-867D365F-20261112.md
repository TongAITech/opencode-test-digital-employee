# F 独立验收正式 Mission 源事件单行解析

接受 #306 精确提交 `867d365f1017f5af2be598a1d690dbb0818f4551` 的独立单行解析。实际本地以警告视为错误执行 5 项，全部通过。精确 [CI 43071117778](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/43071117778) checkout 日志确认 Python 3.8 和 3.11 各通过 38 项。

独立 Ruby 规范化与哈希生成新的 1532 字节事件体，包含中文、非 BMP、组合字符及内部控制字符。重算请求摘要为 `aed664d05d312ff7e25b87a999065b6109433087ec0a9d00e37981b0565ed118`，原体 SHA-256 为 `790ec5be593411ee0b65aed8f06d71c658df4e798ed1a96b9a23ff73135c0d81`。候选接受规范原行并保留精确事件与回执引用。附加 U+0085 的运行 release 在同步修改全部镜像并重新计算摘要后仍被拒绝。转义同名键、CRLF 和多余 JSON 空白同样被拒绝。

临时文件中的同一合法原行交给现有原生 TruthRuntime 冷回放，得到 UNSUPPORTED_EVENT_TYPE，原字节保持一致。本次范围仅为独立源事件结构、请求摘要与原始行哈希。账本唯一性、来源权威、回执重建、正式读写部署和现场仍待分别验收。
