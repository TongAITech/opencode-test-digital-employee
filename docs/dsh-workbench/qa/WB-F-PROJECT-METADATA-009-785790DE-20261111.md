# WB-F｜项目元数据 009 独立验收｜785790de

- 结论 `REJECTED_EXACT_SOURCE`，一项可复现 P1。候选为 PR #244 的 `785790deb6d277f3be0e363f4901835d1fa625be`。
- 验收日期 2026-11-11。F 独立工作区运行 PostgreSQL 17.6、Psycopg 3.2.13。各检查使用仓内 fixture 创建并清理的隔离数据库。
- 依据为 B230 命名治理合同、A9a、候选固定 manifest、SQL、runner、store 及相应测试。报告只覆盖该源的内部可选 009 PostgreSQL 候选。

## P1｜并发激活与项目创建绕过完整治理分母

**要求**。项目范围有未知行时，命名域不能激活，已激活域也必须阻断新的命名请求。当前 `metadata_project_insert()` 只停用事务可见的活跃域，`metadata_integrity()` 只校验当前事务可见的项目和域，两个事务没有共享的序列化点。参考候选 SQL 第 84–105 行。

**独立复现**。用 `MetadataPG` fixture 的两条数据库 owner 连接，初始已安装 001–007 与 009，有 P1、P2，尚无命名域。每条连接开始默认 READ COMMITTED 事务。事务 A 建 `NS` HOLD，用 fixture 的 `govern()` 中的同一 SQL 绑定并分类 P1、P2，再在该事务把 NS 改为 ACTIVE。事务 B 在 A 未提交时插入 P3。两个事务都在对方未提交时成功执行 `SET CONSTRAINTS ALL IMMEDIATE`，然后依次提交 A、B。两条连接均沿用 fixture 的正常管理员身份。

```text
A 可见项目数                                2
B 可见 ACTIVE 域数                           0
提交后 NS 状态／项目总数／分类总数           NAMING_ACTIVE / 3 / 2
P1 受控读取                                 GOVERNED_ROOT_ACTIVE
P1 原名 first，fresh key                     NO_CHANGE
数据库计数 result / audit / history / outbox 1 / 1 / 0 / 0
当前名称／metadata_revision／name_key        first / 1 / 6669727374
```

可复验的关键调度如下。A 的三条建域/绑定/分类语句沿用 `MetadataPG.govern()`，保留相同参数和执行顺序。

| 顺序 | A | B |
| --- | --- | --- |
| 1 | `BEGIN` | `BEGIN` |
| 2 | 建 HOLD 域，按可见项目建绑定和分类，设为 ACTIVE | |
| 3 | | `INSERT INTO wb.project(project_id,name) VALUES('P3','third')` |
| 4 | `SET CONSTRAINTS ALL IMMEDIATE` | `SET CONSTRAINTS ALL IMMEDIATE` |
| 5 | `COMMIT` | |
| 6 | | `COMMIT` |

接着用正常 runtime 的 `get_metadata('alice','P1')`，再执行 `rename('alice', request('first'))`。独立 Oracle 检查数据库状态和四张业务记录计数。该结果确实在不完整分母下对新请求落了回执和审计。另一 fresh key 请求改名为 `changed` 时，延迟触发器抛出 `23514 GOVERNANCE_POPULATION_INCOMPLETE`，Python 返回 `ILLEGAL_IDENTITY`。回执、审计、历史、outbox、当前名称和 revision 都保持上表状态。管理员在事务内将域转 HOLD、补齐 P3 绑定与分类、重新激活后，以相同失败请求重试成功一次，得到 revision 2、一条 history、一条 outbox、两条 result、两条 audit。

后续精确复验须证明合法的建域、激活、项目新增在并发提交与回滚时维持完整分母，并覆盖已先行触发约束的调度。GET 和 fresh NO_CHANGE 均需按真实治理状态响应。

## 字节等价源码差异与环境限制

B230 规定 UTF-8 精确字节等价，禁止使用数据库语言排序比较。唯一索引和绑定一致性检查使用 `bytea`，但 `metadata_name_valid`、history CHECK、延迟 proof、NO_CHANGE 分支仍使用文本比较，见候选 SQL 第 42、78、109–112、171 行。仓内当前默认确定性排序的用例通过，包含同域隔离名称、大小写区别和 Unicode 输入。

F 在另一个 fixture 尝试 `CREATE COLLATION wb.f_m1_ci (provider=icu, locale='und-u-ks-level2', deterministic=false)`，PostgreSQL 返回 `0A000 ICU is not supported in this build`。未取得 ICU 上的行为结果，以上仅为源码与合同差异。后续候选需明确使用字节等价或提供能够执行并验证配置限制的证据。

## 通过的回归与范围

```sh
WB_PG_TEST_DSN='host=/tmp/dsh-pg-371f43f0 port=55432 dbname=postgres' \
  ../pg-environment-venv/bin/python -m unittest discover -s tests -p 'test_dsh_workbench_b*postgres.py' -v
```

F 实际运行 296 项通过，含 optional 009 的 29 项。真实并发覆盖已有 batch、asset 与 metadata 同 key 的两方向等待、提交、回滚、超时恢复，以及 `NO KEY UPDATE` 与不同 key 的分离。其它通过项覆盖单一名称事实与 UTF-8 key、CAS、原始回执及重放、审计/outbox 故障原子回滚、NUL reason 的 `bytea` 与审计 hex 可逆、旧 runner/默认 001–007 兼容及 profile v2 明确不资格化 009。权限检查基于源码和已有测试。独立 P1 的调度在这些回归之外。

固定 manifest 的原始哈希和每份迁移脚本哈希在执行前校验，图为 001–007 加 009，009 无 008 依赖。源码审查覆盖既有 request key、受限 executor、CAS 和原子写入分支。保留原目录及 R1 边界。

GitHub Actions 运行 42958453490 为 SUCCESS，checkout 日志执行了 `git log -1 --format=%H` 并输出本报告完整 SHA。三组分母分别 29、27、2，均 OK。此记录与 F 的本地独立执行分别留存。[精确 CI](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42958453490)

生产 009 profile 资格、Host API、银行现场、Windows、离线交付、正式 R1 执行和最终发布均不在本报告验收范围。
