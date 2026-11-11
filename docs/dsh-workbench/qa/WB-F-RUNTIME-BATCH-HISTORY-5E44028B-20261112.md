# F 独立复验运行批次历史 5e44028b

裁决 `ACCEPTED_EXACT_DETACHED_BATCH_HISTORY`。对象为 [PR #281](https://github.com/TongAITech/opencode-test-digital-employee/pull/281) 精确提交 `5e44028bf569e8dccced26189f1cf56838365e52`。旧 [F #282](https://github.com/TongAITech/opencode-test-digital-employee/pull/282) P1 拒绝仅针对旧提交，保留作为对照。

独立探针通过真实状态机写入批次及十节点，使用 canonical repository 写入更新或另一批次，对临时 R1 严格 JSON 数据施加独立变体，再通过真实 TruthRuntime 冷回放，核验 raw history 结果与磁盘字节。五项结果如下。

| 变体 | 冷回放 | 历史核验 |
| --- | --- | --- |
| 原 P1，批次 ID 两端空格，v2 release 与 Mission 漂移 | 目标批次落到外部 v2 | HISTORY_CONFLICT |
| 另一批次中 Mission 带 U+2003 与 U+00A0 | 另一批次归到同一 Mission | HISTORY_CONFLICT |
| 同批次 v2 release ID 两端空格 | canonical 投影仍与预期三元组一致 | HISTORY_CONFLICT |
| 同三元组正常更新 v2 | 目标 v2 | 接受 v2 |
| 前缀相同的其他批次带空格 | 仍属于另一批次和另一 Mission | 目标继续接受 v1 |

五项均保持读取前后账本字节相同。候选历史七项与映射四项本地通过，零跳过。[精确 CI 43068981745](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/43068981745) 的 Python 3.8.18 与 3.11.18 均核对实际 checkout 为上述 SHA，各通过紧凑绑定九项、映射四项、历史七项。

本裁决覆盖已解码、固定账本快照的 ReleaseBatch 历史检查。正式来源事件、账本权威、调用方严格 JSON 解码与权限、正式控制及现场验收继续由对应工单证明。
