# B 本地 PostgreSQL 环境准备证据

状态：ENVIRONMENT_READY / W1_BUSINESS_IMPLEMENTATION_NOT_STARTED / POSTGRES_BUSINESS_QA_NOT_RUN。
日期：2026-11-10；平台 macOS x86_64，Apple clang 21.0.0。

官方源码 `https://github.com/postgres/postgres.git`，tag REL_17_6，commit `7885b94dd81b98bbab9ed878680d156df7bf857f`；许可证为源码 COPYRIGHT 的 PostgreSQL License。本次仅准备本地工程测试依赖，未纳入产品/Windows离线包。

环境根目录为工程父目录（含 workbench、wb-pg）。源码在 pg-environment-source，隔离安装在 pg-environment-runtime，专用数据目录 pg-environment-data，专用Unix socket `/tmp/dsh-pg-371f43f0`，端口标识55432。TCP listen_addresses为空；未连接/修改已有数据库；未建立工作台业务schema。

从环境根目录运行：

```sh
cd pg-environment-source
./configure --prefix="$PWD/../pg-environment-runtime" --without-icu --without-readline
make -j4
make install
cd ..
# initdb已执行，勿覆盖已有数据目录；新环境需另取专用空目录。
pg-environment-runtime/bin/pg_ctl -D "$PWD/pg-environment-data" -l "$PWD/pg-environment-server.log" -o "-h '' -k /tmp/dsh-pg-371f43f0 -p 55432" start
pg-environment-runtime/bin/psql -h /tmp/dsh-pg-371f43f0 -p 55432 -d postgres -v ON_ERROR_STOP=1
pg-environment-runtime/bin/pg_ctl -D "$PWD/pg-environment-data" -m fast stop
```

本地真实结果：version()=PostgreSQL17.6；BEGIN→CREATE TABLE environment_probe→INSERT→ROLLBACK 后 to_regclass IS NULL=t；fast restart 后 SELECT1=1；SHOW listen_addresses为空。以上只证明数据库引擎和环境可运行，不证明业务迁移/权限/RLS/并发/恢复验收。

保留失败：Docker CLI存在但daemon不可连接；Homebrew bottle manifest下载失败且提议升级四个现有依赖，已停止安装；官方ftp下载15秒超时后改用GitHub官方源码；首次项目长目录Unix socket超过103字节失败，改用700权限短目录后启动成功。编译/安装/initdb/server日志位于环境根的 pg-environment-*.log。

下一工单：仅在A/F正式冻结W0后，B01/B02实施命名迁移及真实PostgreSQL测试；业务事务/API使用非superuser runtime角色，不能使用本环境管理员替代权限验收。独立PG客户端驱动、生产连接配置、RLS与迁移回滚尚未实现。
