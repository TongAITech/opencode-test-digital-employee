# WB-F｜项目元数据 009 独立复验｜3b74d5e0

结论为 `ACCEPTED_EXACT_OPTIONAL_PG_COMPONENT`，适用于 PR #244 的 `3b74d5e00edb6c2c0304074bdc2699481309c52c`，2026-11-11。旧提交 `785790de` 的 F246 拒绝保持有效。[候选 PR #244](https://github.com/TongAITech/opencode-test-digital-employee/pull/244) · [旧报告 PR #246](https://github.com/TongAITech/opencode-test-digital-employee/pull/246)

## 独立复演 F246

使用 PostgreSQL 17.6 ICU、Psycopg 3.2.13 和隔离 fixture。事务 A 以 F246 的 HOLD→ACTIVE SQL 原样创建命名域，绑定与分类初始 P1、P2。事务 B 插入 P3。两边在提交前显式执行 `SET CONSTRAINTS ALL IMMEDIATE`。每个组合使用新数据库，从 `pg_blocking_pids` 观察后手真实等待，再提交或回滚先手。RR 组合的后手在先手事务写入前已固定项目快照。

| 先手 | 先手结局 | 后手隔离 | 后手结局 | 最终域／项目数／分类数 |
| --- | --- | --- | --- | --- |
| 激活 | 提交 | RC | 新增成功并停用命名域 | HOLD／3／2 |
| 激活 | 回滚 | RC | 新增成功 | 无域／3／0 |
| 激活 | 提交 | RR 旧快照 | 40001，回滚 | ACTIVE／2／2 |
| 新增 | 提交 | RC | 23514 GOVERNANCE_POPULATION_INCOMPLETE，回滚 | 无域／3／0 |
| 新增 | 回滚 | RC | 激活成功 | ACTIVE／2／2 |
| 新增 | 提交 | RR 旧快照 | 40001，回滚 | 无域／3／0 |

激活先提交后，GET 返回 `GOVERNANCE_HOLD` 和 `can_rename=false`。与当前名相同的 fresh 请求返回 `GOVERNANCE_HOLD`，结果表保持零行。其余组合结果表同为零。旧复现的 ACTIVE／3／2 与持久化 NO_CHANGE 均未再出现。

源审确认公共 fence 写入形成实际事务版本，行政语句级触发器在改动项目集合、命名域、绑定治理字段和人口分类前取得它，再按 UTF-8 顺序锁域。RR 旧快照无法跳过版本检查。常规 rename 只改名称、版本和 name_key，ACL 只触发访问版本更新。仓内 fixture 持有 fence 时两者仍完成，fence epoch 未变化。真实已有 batch/asset 同 key 测试验证锁等待、两个提交方向、回滚与重试，包含不同 key 进展及历史回执。权限范围通过只读源码与已有 fixture 检查。

## ICU 与同快照读取

独立建非确定性 ICU `und-u-ks-level2` collation，应用于当前项目名称和 history 的两列。确认数据库语言等价下 `first = FIRST` 与预组 `é = e + U+0301`。正常 store 依次写 `FIRST`、`é`、组合形式，均为 APPLIED，绑定 key 等于每次输入的 UTF-8。history 前后字节分别为 `6669727374→4649525354`、`4649525354→c3a9`、`c3a9→65cc81`，最后重复组合形式返回 NO_CHANGE。仓内 ICU 用例同时验证显式 collation 参数。源码确认名称校验、NO_CHANGE、history CHECK 和延迟 proof 都用 UTF-8 bytea，修复 F246 的源码差异。

GET 独立交错在授权读取固定快照后、正式元数据 SELECT 前，由另一条连接提交 P1 的写权限降级。降级前、交错中的 GET 和 fresh GET 分别返回 access revision/can_rename 为 `1/true`、`1/true`、`2/false`，新 GET 保持活跃治理状态。该字段是同快照显示值，正式 mutation 仍须按当前 ACL、治理状态和 CAS 独立重验。

## 独立回归与精确 CI

```sh
WB_PG_TEST_DSN='host=/tmp/dsh-pgicu.DL7Eav/socket port=55439 dbname=postgres' \
  ../pg-environment-venv/bin/python -m unittest discover -s tests -p 'test_dsh_workbench_b*postgres.py' -v
```

F 实际执行 304 项通过，含 optional 009 的 37 项，零跳过。涵盖固定 manifest、001–007 兼容、009 下迁与回滚、复合引用和单一名称事实、并发治理、同 key 跨动作、NUL reason 无损、CAS、历史回执、审计和 outbox 事务，以及 profile v2 对 009 显式不资格化。报告额外复演独立于以上用例。

GitHub Actions 42964582972 checkout 日志和测试步均输出完整候选 SHA，`WB_PG_REQUIRE_ICU=1`，ICU 用例实际通过，37+27+2，零跳过。PR #244 的 W0、Python 3.8/3.11 codec、B PostgreSQL 及 optional 009 检查均为成功。[精确 optional 009 CI](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42964582972)

验收范围为内部可选 009 PostgreSQL 组件。生产 009 profile、Host/API、银行现场、Windows、离线交付及正式 R1 与发布门禁仍须各自取证。报告 PR 只添加此文件。
