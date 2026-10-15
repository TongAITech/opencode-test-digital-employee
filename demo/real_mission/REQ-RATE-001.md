# REQ-RATE-001 利率调整边界规则

## 业务目标

信贷利率调整服务接收当前年利率与调整值，按业务规则计算调整后的年利率。

## 业务规则

1. 调整值 `delta` 的合法范围为 **[-0.50, +0.50]，包含两个边界**。
2. 当 `delta = +0.50` 时必须受理，返回 `accepted=true`、`code=ACCEPTED`。
3. 当 `delta > +0.50` 或 `delta < -0.50` 时必须拒绝，返回 `accepted=false`、`code=DELTA_OUT_OF_RANGE`。
4. 调整后的年利率不得小于 0；若小于 0，返回 `accepted=false`、`code=NEGATIVE_RATE_FORBIDDEN`。
5. 成功时返回的 `rate` 保留两位小数。例如当前年利率 `3.25`、调整值 `+0.50`，结果必须为 `3.75`。

## 验收样例

| 当前利率 | 调整值 | 预期 |
| --- | ---: | --- |
| 3.25 | +0.50 | ACCEPTED，rate=3.75 |
| 3.25 | +0.51 | DELTA_OUT_OF_RANGE |
| 0.20 | -0.50 | NEGATIVE_RATE_FORBIDDEN |

## 风险

边界判断若把 `+0.50` 错写成排除边界，会导致合法调息请求被错误拒绝。该规则按高风险边界场景纳入测试。