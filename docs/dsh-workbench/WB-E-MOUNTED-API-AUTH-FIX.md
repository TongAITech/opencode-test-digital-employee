# 工作台挂载模式遗留API访问隔离

修复基线ebce951e中工作台新API鉴权失败后，旁路旧/api/missions/*/overview仍可读正式R1的问题。显式注入workbench_handler或workbench_mode=True均启用安全挂载模式；自定义handler不能用False关闭保护。CLI --workbench可在Host尚未接入时先关闭旧私有API。

安全模式下，新/api/workbench/v1仍交原handler鉴权；所有旧/api/* GET（仅精确/api/meta例外）/POST在dispatch和POST body读取前固定403，错误不暴露路径、inventory、对象或内部异常。/api/health含敏感R1路径/计数因而不开放。旧独立无挂载/无flag模式保留现有行为。

本地持久synthetic R1+真实HTTP测试覆盖旧Mission/health/cases/hierarchy/路径变体拒绝、零dispatch、非法JSON body未解析、R1 bytes不变、公开meta、workbench鉴权拒绝、显式安全模式缺Host503、CLI flag与独立legacy200兼容。测试provider不是现场认证；真实DSH/Windows为FIELD_NEEDS_BANK_TRANSFER。

首次CLI测试Mock缺server_address导致测试错误，已补完整server接口后重跑；不是产品错误证据。F独立验收需绑定最终SHA，08/09/10由A维护。

安全CLI使用WorkbenchPublicApplication静态/meta facade，不初始化TruthRuntime、不读写R1，缺源及父目录均不创建，启动信息不打印R1路径。真实本地PG+HTTP额外验证挂载后可信provider的scope/quality仍200、legacy同时403、原R1不变。浏览器回归因本venv缺playwright未运行，未记浏览器PASS。
