# D01 版本声明与失败恢复增量证据

基线14534d611966b1692b682011d636bef3aed3f747；D独立实现，需F独立验收。

新增allowlisted manifest观察后的版本对账：仅接受规范包身份@deepseek-ai/dsh；版本一致只记DECLARED_VERSION_MATCH_RUNTIME_UNVERIFIED，不同/冲突/缺失分别明确；client export仅声明，panel_compatibility始终CAPABILITY_UNKNOWN。不会读新路径或任意配置。

HTTP 401/403归HOST_PERMISSION_DENIED，404归HOST_ROUTE_MISSING，其余网络/服务器失败GET_UNAVAILABLE；失败即停止，不继续会话明细。不做自动认证、安装或POST。探测每次重读，无旧成功缓存。

实测命令：python3 -m unittest discover -s tests -p 'test_dsh_workbench_host*_d.py' -v，33/33 OK，包括五项真正临时loopback socket测试（不是DSH）。新增3个测试覆盖声明版本匹配/不符/冲突、manifest缺失→损坏→修复、401/403/404/500零额外读取。

真实本机命令：python3 tools/dsh_workbench/wb_d_host_probe.py --url http://127.0.0.1:4096，exit2，session_status=GET_UNAVAILABLE，field_verified=false，bank_final=false。没有实际DSH版本/面板接口/Host身份可供现场验证，因此D01为COMPONENT_TESTED / BLOCKED_FIELD，不能登记IMPLEMENTATION_QA_PASS。真实DSH1.18.26和Windows恢复均NOT_RUN。

未写模型密钥、未安装插件、未修改R1或08/09/10。F必须独立审查提交后的精确SHA，不继承旧D设计check结果。
