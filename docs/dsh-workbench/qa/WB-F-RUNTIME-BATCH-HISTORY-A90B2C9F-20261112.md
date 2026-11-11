# F 独立复验运行批次历史 a90b2c9f

裁决 `REJECTED_P1_CANONICAL_IDENTITY_MISMATCH`。复验对象为 [PR #281](https://github.com/TongAITech/opencode-test-digital-employee/pull/281) 精确提交 `a90b2c9fbef7d60b4184668f944eddef8d25e472`，参考 D #263 和 F #264 的批次完整历史与身份不漂移要求。

本地候选的六项批次历史与四项映射用例全部通过，包含正常更新、同名前缀批次、漂移后改回、重复原始初始化、同 Mission 冲突批次、原始 metadata 矛盾和缺必填字段。[CI](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/43067432159) 的 Python 3.8.18、3.11.18 两个 job 均确认 checkout 同一完整 SHA，各通过紧凑绑定九项、映射四项、历史六项。

## 独立反例

1. 使用真实 `RC72StateMachine` 在临时 R1 建立 `RUN-BATCH / RUN-RELEASE / MISSION` v1 与十节点。
2. 使用真实 `CanonicalRC72Repository` 写入同批次 v2，release 与 Mission 分别为 `OTHER-RELEASE`、`OTHER-MISSION`。只在临时日志中将该 v2 的 envelope `entity_id` 和 payload `release_batch_id` 改为 `" RUN-BATCH "`。结果仍是严格可解码的 JSONL。
3. 重新构造 `TruthRuntime`。既有 canonical validator 会剥除身份两端空白，故以 `RUN-BATCH` 查询当前记录得到 v2 外部 release 与 Mission。对同一冷快照执行候选核验返回历史 v1，接受了错误结果。复验前后临时日志字节相等。

`runtime_batch_history.py` 以原始字符串判定无关事件，在调用会规范化身份的 `validate_release_batch` 前跳过 v2。历史准入必须先证明任何 ReleaseBatch 的原始身份与 canonical replay 身份一致，再按精确批次或 Mission 判定相关性。至少应阻断因批次或 Mission 规范化而隐藏的相关事件，并在修复候选重跑独立冷回放。正式创建来源、授权、Host 与现场验收均不在本次覆盖范围内。
