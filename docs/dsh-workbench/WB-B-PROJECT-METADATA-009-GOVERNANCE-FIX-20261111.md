# B：PR244 009治理并发与UTF8精确比较修复证据

状态：**B_LOCAL_REAL_PG_PASS / NEW_EXACT_HEAD_D_E_F_REVIEW_REQUIRED / ISOLATED_CANDIDATE_ONLY**。旧冻结源`785790deb6d277f3be0e363f4901835d1fa625be`与原catalog保留，不沿用旧PASS。旧源真实并发和ICU缺陷如下；本增量无HTTP/UI、008、R1、原profile或08/09/10变化。

## 旧源真实反例

PG17.6实际两个独立owner连接：A新建NAMING_ACTIVE域、绑定并记录P1/P2，B插入P3。对方尚未提交时两边`SET CONSTRAINTS ALL IMMEDIATE`均成功，然后各提交。原结果`NAMING_ACTIVE / 3 projects / 2 population`，GET错报GOVERNED_ROOT_ACTIVE，旧名称NO_CHANGE仍产生原回执。把两顺序和REPEATABLE READ旧快照写入做成3项回归，先在精确旧SQL运行：**3失败 / 0.971s**；激活后新增没有停用，新增后激活没有拒绝，旧快照没有报错。

另用`git archive 785790de`取旧真实代码，复制同一新ICU测试至临时目录，在真实PG17.6+ICU比较`first`/`FIRST`：等价排序但字节不同，旧历史CHECK拒绝23514，经store返回422 ILLEGAL_IDENTITY。**1错误 / 0.607s**。旧默认排序环境的通过没有覆盖此场景。

## 修复与实际Oracle

行政分母写操作在BEFORE STATEMENT先更新受控单行fence的epoch，再按UTF8字节序锁命名域行，然后才写project identity/namespace/population/binding成员。成员定义的INSERT/DELETE/指定字段UPDATE均纳入；治理TRUNCATE拒绝。共用的实际row version使REPEATABLE READ旧快照在更新fence时明确失败40001，不是只等advisory锁后继续验证旧快照。正常rename只写名称/key/revision及原结果，不取全局fence，仍按namespace SHARE→project NO KEY UPDATE→binding→claim；ACL epoch更新也不取fence。没有把任意owner手工预锁/DDL操作或生产角色漂移当已封闭。

真实两连接用pg_blocking_pids观察等待：激活先提交则后来的新增在锁后看见该域并置HOLD；新增先提交则旧两成员的激活不完整、全回滚；两种先操作回滚都释放围栏并让后操作得到正确结果；RR旧快照等待后40001，无namespace残留。已活动域的普通rename先提交，再允许等待的新增项目停用该域；原rename回执仍可读。独占fence行时普通rename和独立ACL变更不被其串行化；现有asset/batch同K、不同K、超时与失败回滚全回归。

NO_CHANGE、名称规范边界、历史CHECK及变更proof用UTF8 bytea比较，不缩Unicode；009要求UTF8数据库。真实非确定性ICU下同时改项目/历史名称列排序规则及显式函数参数排序规则：不同字节均APPLIED，精确同字节才NO_CHANGE。SQL request/revision ASCII校验也不借名称排序规则。新增GET `can_rename` 是同一受权PG快照中的布尔提示：现绑定根项目+活动允许改名域+当前can_write才true；reader、未治理、HOLD及撤成reader为false。PATCH仍独立验证Host mutation、CSRF/Origin、原context、锁内ACL和治理，不使用该提示作授权。

## 运行结果与未准入边界

- 旧3个治理红转为**3通过 / 1.039s**。原本地PG无ICU：目标37项中36通过、1明确跳过；不把它算ICU PASS。使用已有官方PG源码`7885b94dd81b98bbab9ed878680d156df7bf857f`隔离编译PG17.6+ICU78.2，原服务未改。单独ICU **1通过 / 0.378s**。
- 最终完整B suite同真实PG17.6+ICU、psycopg3.2.13、`WB_PG_REQUIRE_ICU=1`：**304 tests / 110.935s / OK / 0 skipped**（目标37项含2个manifest测试）。专门CI要求实际ICU，不容许静默跳过。CI结果另登记PR body，源不反复变更。
- 新[实际catalog证据](evidence/WB-B-M1-009-GOVERNANCE-FIX-PG17-CATALOG-20261111.json)显示runtime无fence UPDATE/name UPDATE/namespace SELECT或SET executor；空009 down拆除fence和额外权限。已装009仍让旧v2明确UNQUALIFIED；空down回到MATCHED_AS_OF，两者都不授admission。没有动态学习或给009新生产profile。固定manifest/SQL哈希更新，旧785试验数据库不伪改checksum；仅空旧fixture清理后重装，非空历史另需受审保留数据路径。

D/E/F仍须核新精确源，A HTTP/C UI须重新对新版本验证。真实Host、生产命名治理来源、新固定profile、Windows与正式发布均未获资格。
