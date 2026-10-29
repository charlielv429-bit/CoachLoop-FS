# INTEGRATION-03：主服务课前入口收尾与安全审查

## 基线与远程事实

开发基于 main `051811bd1bff8b39a8d024362e438cc3e68d264e`。开始时远程没有 `feature/coze-integration-v01`，main 没有主服务课前路由、别名或 `tests/test_prelesson_route.py`。Coze本地未上传文件不在本工作区，未读取或覆盖，不能验证其字节内容、测试日志或网关配置。本实现复用已合并的 `run_prelesson` 和PR #4认证/Schema/保护，提供等价主服务能力。

## 实现与契约

`src/main.py` 使用 `create_router(include_alias=True)` 挂载两个相同处理器：

- POST `/api/v1/lesson-plans/draft`
- POST `/prelesson/draft`（别名，认证、校验与输出完全一致）

调用仍需 `Authorization: Bearer <服务凭据>`，凭据从服务端安全环境变量 `COACHLOOP_PRELESSON_TOKEN` 注入；未配置503、缺失401、错误403。`X-Coze-Authenticated`、`X-Authenticated-User` 等自报网关头不能替代Bearer验证。请求不能设置审核状态、引用、KB核验或视频结论。只支持零基础固定主题、45分钟；输出七要素、预计负荷、draft、教师审核必需和unverified。

输入/成功输出Schema复用 [请求](prelesson-workflow-v01.request.schema.json) 与 [响应](prelesson-workflow-v01.response.schema.json)。主服务完整契约以 `/openapi.json` 为准；[两个课前路径的OpenAPI切片](coze-integration-v01.openapi.json)可供插件配置，未填部署地址。测试逐项比较切片路径、Schema和真实main契约，旧独立工厂的OpenAPI保持不变。

`PrelessonRoute` 在路由内复用精确JSON解析、1 MiB请求限制和脱敏错误处理；不安装影响旧接口的全局中间件/异常处理器。主服务原lifespan、文本主图、视频识别、数据库迁移和训练归档接口不变。旧独立 `create_app` 继续可用。新主服务入口不写 teaching 表，不进行知识检索/视频推理/OCR，不自动批准教案。

## 认证审查与可部署方案（本轮未部署）

已证实的控制是应用内Bearer精确比较和默认关闭，覆盖两个入口。这个共享服务凭据只授权生成草稿，不认证某位教师，不证明Coze平台来源，也不赋予教师批准权限。未拿到网关部署配置、身份验证协议或真实请求证据，因此不得把“平台网关存在”当作已完成认证。

可部署方案：

1. 主服务运行在受限网络，只经获批准的TLS入口访问；主机防火墙/网关限制直接访问。平台在插件安全认证设置中保存服务凭据，服务通过秘密管理注入同一凭据；只放Authorization头，不放URL、表单、代码样例、源码或命令输出。
2. 上游若需要教师级授权，网关必须实际验证所选会话/JWT签名及发行方/受众/有效期，清除客户端伪造的身份头，并限制允许调用的路由与方法。没有该配置与测试证据时，保持应用Bearer校验，不能设置免认证开关。
3. 对外按路径明确允许两个课前POST及必要的受限健康检查。**既有 `/run`、`/stream_run`、`/node_run`、`/async_run`、任务查询等接口没有因本轮获得统一Bearer保护**，不能因此将整个main服务无条件开放公网；需独立鉴权/网关阻断与日志审查。本轮不扩展其权限逻辑。
4. 网关和应用日志不记录Authorization、服务凭据或不必要的班级文本；禁止通过已有 `/run` 的query/body传递凭据（该旧入口会记录输入）。使用匿名合成请求验证允许、拒绝与错误分支，验证轮换、限流和审计策略后再申请发布；本轮没有发布操作。

原main启动会初始化数据库连接及memory检查点，这是已有lifespan行为；生产运行需专用最小权限运行账号及获批准的初始化方案，不能拿测试超级用户替代运行角色。本轮真实启动仅连接全新隔离PostgreSQL，不读取生产连接信息。

## 全部181项跳过原因

独立复现原GitHub基线、去掉 `TEACHING_DATABASE_URL` 与 `TEACHING_ALLOW_MIGRATION` 后：**333 passed、181 skipped、0 failed**。仓库唯一实际跳过点是 `tests/teaching/conftest.py` 的数据库夹具：缺少显式隔离库URL就跳过；配置了错误/非隔离URL会失败而不会偷偷连接。`pytest -q -rs -p no:cacheprovider` 已逐项列出181项相同原因：

| 测试模块 | 跳过数 | 被跳过的验证 |
|---|---:|---|
| test_event_consistency.py | 49 | 六字段/JSON快照、错误类型及旧数据迁移一致性 |
| test_postgres.py | 46 | 迁移升级/回退、真实受限角色、RLS/租户、权限与审核历史 |
| test_training_import.py | 86 | 真实数据库导入、审核信任、幂等/并发、精度及跨租户隔离 |
| 合计 | 181 | 全部为隔离PostgreSQL环境依赖 |

这些跳过不是通过，也不能由SQLite替代。Coze报告的340+181与基线333+181加7项测试在数量上相符，但未上传的测试覆盖和实际网关控制不能由这个算式证明。

覆盖不足另行处理：基线没有主服务路由测试或真实uvicorn启动测试。本轮新增主服务双路径/auth/schema/非法输入/原接口隔离测试，以及一个真实 `uvicorn main:app`＋隔离PostgreSQL HTTP测试。前者明确替换数据库lifespan，不能冒充真实启动；后者使用未替换的真实main lifespan、回环HTTP及专用测试库。无隔离库时这个新增真实启动用例会另行跳过；全环境验收必须使它与原181项一起实际执行。

## 测试与本地运行

```bash
# 单元路由及既有课前流程，不需数据库；TestClient需要本地线程/事件循环通信能力。
.venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_prelesson_route.py tests/test_prelesson_workflow.py tests/test_prelesson_review_adversarial.py
# 专用隔离库安全配置沿用DB-A，只允许127.0.0.1:55432/coachloop_db_a_test。
# 安全注入 TEACHING_DATABASE_URL 和 TEACHING_ALLOW_MIGRATION=mock-only 后：
.venv/bin/python -B -m pytest -q -p no:cacheprovider
.venv/bin/python -B -m pytest -q -p no:cacheprovider tests/teaching/test_main_prelesson_http.py
```

真实HTTP测试临时启动 `uvicorn main:app --host 127.0.0.1 --port <临时端口>`，为子进程注入指向同一隔离库的 `PGDATABASE_URL` 和临时服务凭据；不打印值，不经过外部服务，结束后关闭进程。生产环境启动命令仍是现有 `.coze`/`scripts/http_run.sh`，本轮未修改部署配置。不要为本地测试复用生产URL。

## INTEGRATION-04 最小边界

只做**一个Coze课前插件的受控端到端联调**：确认获批准服务地址和认证配置，映射当前Schema，用一个匿名合成班验证草稿、拒绝分支和教师审核交接，保留脱敏调用证据。不得重做Agent/视频识别，不导入真实学员，不新增数据库审批/归档或课后评价；真实教师身份认证、批准写回及真实数据准入若需要，另行明确范围和授权。

## 本轮实际验收结果

全新隔离PostgreSQL **16.15**：全量 **536 passed、0 skipped、0 failed**；主服务路由21 passed；真实uvicorn main＋PG 1 passed；数据库/训练归档目录207 passed（包含该真实启动测试）；原视频/教练审核41 passed。原181项环境跳过均已实际执行。各专项包含在全量中，不重复累计。存在一项既有第三方SDK的Pydantic弃用警告；`git diff --check`通过。

当前已覆盖代码级合并验收，未验证Coze在线配置、真实平台网关、教师身份授权或公网发布。main原lifespan与旧入口认证策略仍按上文保留边界；不能据本地HTTP成功宣称已上线。

## PR #5 最终独立审查

确认一项P2测试隔离缺陷：旧路由测试复用全局缓存的 `main` 模块；先以空凭据导入main，再运行成功路径测试会出现两个503失败。应用拒绝请求是正确的，问题是测试假定设置环境变量会重建已导入的认证闭包。测试现在用独立模块实例，并恢复环境，避免导入顺序影响；未改生产认证或任何主服务业务代码。

服务凭据在构建路由时读取，必须在进程启动前通过安全环境配置注入；修改平台配置或进程环境不会自动刷新已经构建的路由，轮换需要按受控重启/应用重建方案进行。新增真实uvicorn无凭据启动用例验证两个路径均返回503，即使请求带Bearer或自报平台身份头也不能生成教案。查询参数、Cookie、错误Token后缀及路径重定向的对抗测试均不得绕过认证。原 `/run` 的无Bearer调用仍按原文本工作流运行，明确证明新认证没有覆盖整个服务；这属于公网暴露前必须处理的旧入口访问边界。

本地兼容性核查：Python 3.12、FastAPI 0.135.1、Starlette 0.52.1、Pydantic 2.12.5、LangGraph 1.0.2、coze-coding-utils 0.2.8、coze-coding-dev-sdk 0.5.26、uvicorn 0.41.0。真实main有/无Bearer配置均须使用隔离PostgreSQL启动成功；不据此宣称Coze在线托管网关或凭据注入已经验证。原lifespan仍依赖数据库/检查点，缺少数据库配置的托管环境需先修正运行配置，不能把单独的无DB路由单测当作启动验收。

PR #5复验实际结果：全新隔离PostgreSQL 16.15，全量 **548 passed、0 skipped、0 failed**；main认证/契约/旧接口对抗32通过，真实main有/无Bearer启动2通过，课前与教案输出保护79通过，数据库/训练归档目录208通过，原视频41通过。修复前的导入顺序反例2失败，修复后同样预先导入条件下整个路由模块32通过。只改测试和本说明，生产代码与依赖未改；不存在本轮发现且未关闭的代码合并阻断问题。Coze在线配置、网关控制和公网发布仍未验收。
