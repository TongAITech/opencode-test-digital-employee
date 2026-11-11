# F 独立验收运行批次九字段描述

接受 PR #273 精确提交 `7444f997109d9bdb7d1c571b8a63a7ab93c92fa3`，范围为已解码描述和紧凑绑定之间的纯结构验证。

隔离工作树运行映射 4 项、紧凑绑定 9 项，全部通过。独立探针另验证 7 个拒绝场景，包括 NFC 与 NFD 字符串差异、authority 不同、runtime release 与 runtime batch 对调、孤立 UTF-16 surrogate、绑定 JSON 重复键、Scope 的 release 被替换、绑定字节缺失。另验证精确匹配的 Unicode operation ref 与独立中文 runtime batch ID 两个成功样例。原紧凑外层保留 15 个键。GitHub [CI 43066423677](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/43066423677) 日志确认两项任务实际 checkout 上述精确提交，Python 3.8 与 3.11 各通过 13 项。

运行批次身份由后续真实来源校验。完整请求摘要预映像与正式事件、回执格式待定。本次验收未启用 008、正式读取接口、R1 写入或 Host。
