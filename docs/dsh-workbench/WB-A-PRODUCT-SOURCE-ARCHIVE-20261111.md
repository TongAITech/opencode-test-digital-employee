# A 隔离源码归档启动修复

精确原源码d15a9b27实际复现。复制RC7 `SOURCE_DIRS` 到临时目录并以隔离Python启动正常 `create_server(ProductAdminApplication(...))`，旧默认handler尝试导入归档缺失的 `tools`，出现ModuleNotFoundError。新增独立进程与真实HTTP回归在修复前失败（1.724秒）。

默认未配置服务现使用管理包自身handler，旧管理入口启动。安全Workbench仍以明确503拒绝无Host业务调用，对不支持的方法返回405，并禁止访问旧私有API。显式配置的真实业务handler继续处理同源请求。缺工具的源码归档启动测试实际通过（2.706秒），核旧/meta、静态Workbench、GET/PATCH/POST/PUT状态和R1字节。没有构建最终ZIP。

实际本地回归包括隔离归档、Host/断线与真实PG metadata HTTP 15/15（11.460秒），旧管理测试4/4（1.03秒）。合入已独立接受的C源后在隔离候选执行真实PG17.6+ICU的同源与metadata浏览器2/2（7.762秒）。本候选待F独立复验。源码归档启动验证与行内正式离线安装分别记录。

F在候选840629b3发现错误路径状态差异。实际旧默认PATCH `metadata;extra` 返回405，候选使用urlparse剥离尾随参数后误返回503，两者均未触业务。A将独立反例加入归档测试，在840代码上实际失败（2.801秒），改用与原业务路由相同的urlsplit后通过（2.598秒）。旧错误路径差异与旧缺包启动红灯均保留。
