# Coze线上401诊断：部署3875f17

2026-10-30（北京时间）只读核对远程main与部署提交均为 `3875f17`，包含课前无数据库启动修复。没有修改生产配置、重新部署或调用付费API。

## 当前证据与不能确认的内容

| 观察 | 能支持的结论 | 不能据此断言 |
| --- | --- | --- |
| 用户提供startup complete、监听0.0.0.0:5000 | 应用进程至少完成了当时的启动 | 外部请求一定能转发到该进程、当前所有副本健康 |
| 部署源码GET /health无Depends，返回status=ok | 该路由自身不要求Bearer | 平台网关必须匿名开放它 |
| 仓库唯一全局应用中间件为路径白名单 | 课前模式允许GET /health，其他不允许路径返回404 | 平台没有额外网关/部署访问控制 |
| 仓库课前认证错误文案为Bearer credential required | 用户看到Missing authorization header与应用认证文案不符 | 单凭文案能精确区分平台网关与托管部署访问鉴权层 |
| 当前云环境访问线上health与官方文档时CONNECT 403 | 出口代理拦截了请求；没有取得源站响应 | 源站返回403或部署失败 |

当前最符合证据的是**应用前方的托管鉴权拒绝**，而非已证实的数据库/应用启动失败；是否同时存在路由问题尚未排除。最终归属需对照同一请求时刻的应用access log：如果401没有到达应用记录，且平台凭据能使health返回应用的JSON，才能进一步证实上游拦截。应用日志未记录本身不能单独证明未到达，因为平台可能关闭、抽样或延迟访问日志。

部署链路 `.coze → scripts/coze_prelesson_run.sh → src/main.py` 使用 `DEPLOY_RUN_PORT`，缺省5000，绑定0.0.0.0。用户日志与缺省一致，但当前没有平台生产端口映射证据。网关可在访问上游端口前返回401，因此401既不证明端口错误，也不证明端口转发成功。平台鉴权通过后的health=200及应用access log才是有效端到端证据。

## 三层凭据不要混同

1. Coze网关/部署访问控制：可能先校验请求是否允许访问部署域名，实际机制待平台验证。
2. API渠道的调用凭据与地址：以该**部署应用**的官方调用示例为准；API渠道开启不等于任意自定义HTTP路径均可匿名访问，也不证明会透传Authorization。
3. FastAPI应用Bearer：`COACHLOOP_PRELESSON_TOKEN`只授权两个课前POST；不是已证实的Coze平台访问Token，不认证教师审核身份。

官方文档入口 `https://www.coze.cn/open/docs` 以及线上域名均被当前出口代理以CONNECT 403拒绝，未取得官方正文。不能确认当前Coze Coding是否提供服务专用Token、正式服务URL、特定header或某种透传方式。通用Coze智能体API、工作流API和个人访问令牌不能据此推断适用于coze.site自定义FastAPI；不要猜测/v3/chat等地址来替代本服务接口。亦不能凭“WebSDK关闭/API开启”推断应用HTTP认证已配置完成。

## Mac最少测试命令

将此诊断分支检出到你自己的本地仓库；无需安装新依赖，脚本只使用Python标准库和仓库现有的静态契约检查文件。不复制整个服务环境或任何数据库地址。

```bash
git fetch origin feature/coze-gateway-diagnostics-v01
# 不覆盖本地未提交工作；用独立worktree获取诊断脚本：
git worktree add ../CoachLoop-FS-gateway-check origin/feature/coze-gateway-diagnostics-v01
cd ../CoachLoop-FS-gateway-check
python3 scripts/diagnose_coze_gateway.py
```

在隐藏提示中输入应用 `COACHLOOP_PRELESSON_TOKEN`，不要写入命令行、聊天或日志。脚本先向终端显示目标origin以便核对；只对指定HTTPS origin发送GET /health、两个课前POST及非法课时反例，不调用旧/run或异步接口。不会自动跟随任何重定向，保留TLS验证与系统代理/CA设置，不保存凭据或原始响应。报告只包含固定字段、状态码及固定响应特征；退出码0表示诊断完成，**不表示部署、认证或插件验收通过**。

如果平台官方调用示例明确提供了该部署的Token，而且使用Authorization: Bearer，可再运行：

```bash
python3 scripts/diagnose_coze_gateway.py --with-platform-token
```

此处Bearer是一个待实际示例确认的探测格式，不是对Coze规范的宣称。脚本分别隐藏询问应用和平台凭据；两者不同时，不会把两个Bearer拼到一个Authorization里，也不会让一个覆盖另一个。如果平台官方示例指定了**不同的X-请求头**，可以用 `--platform-header` 配置那个真实字段，前缀按示例选择 `--platform-prefix Bearer` 或 `--platform-prefix raw`。不要自行创造字段名或根据测试中合成的header猜测平台支持。若平台要求其他认证方式，停止，不把秘密放进URL或Cookie尝试绕过。

默认目标是用户提供的 `https://33vnf9hq7m.coze.site`。仅当平台官方示例明确给出不同的可信HTTPS根地址时，使用 `--base-url` 指定那个origin；不接受URL中的用户名、密码、查询参数、路径或fragment，不猜测服务路径。脚本固定调用应用自定义课前路径：如果官方API渠道仅支持专有调用协议，则脚本不能代替适配，应先确认自定义HTTP路由是否受支持。

## 怎样读结果

| 脱敏观察 | 解释与下一步 |
| --- | --- |
| health_no_credentials=401，health_application_bearer仍401 | 应用Token没有使上游请求通过；结合文案/日志定位，不修改应用Bearer以迎合未知平台认证 |
| health_platform_credential=200，draft_platform_credential_only=403 | 很可能平台凭据已过网关，而应用不认可该Token；应用错误特征和访问日志可加强判断 |
| authorization_header_collision=true | 平台与应用的不同凭据共用Authorization；需要平台明确支持的双层凭据传递或受信转发设计，不能关闭应用认证或随意统一两类Token |
| 正确凭据下两个POST的verified_draft=true | 响应通过完整现有Schema、七要素、45分钟、草稿、教师审核和unverified/预计负荷检查；还需核对无凭据/错误凭据拒绝、44分钟为422且application_error_shape=true |
| 任何错误的error_contains_success_payload=true | 错误携带成功载荷，不能当作安全拒绝或通过 |
| redirect_refused=true | 检查平台正式origin与路由；不要加-L或把密钥转发到跳转地址 |
| transport_or_response_error=true | 检查本地网络、TLS、代理、响应大小等；脚本故意不打印原始异常或URL凭据 |
| 平台凭据后502/503/404 | 可能是端口、上游、正式地址或协议不匹配，结合平台路由和访问日志调查；不再直接归咎于Token |

某个响应特征吻合只说明格式一致，不构成响应来源的密码学证明。脱敏JSON报告可以分享；不得附上Token、Authorization原文、Cookie或完整平台调用示例中的秘密值。

## 最少Coze界面核对与发布决定

1. 打开当前部署的API渠道详情/调用示例（具体菜单待平台验证），只核对：正式URL、HTTP方法、自定义路径支持、认证类型、请求头名和Token用途。密钥留在平台安全配置或Mac隐藏输入中，无需发到聊天。
2. 核对该部署的访问控制、生产端口是否与DEPLOY_RUN_PORT/5000一致，以及认证头是否透传给应用。保留所有认证；不要为health浏览器401开启匿名业务访问或恢复旧/run。
3. 用上述本地矩阵确认健康与教案响应，再决定插件认证配置。没有通过完整调用之前，只能离线准备插件Schema，不能声称在线插件已可用。

当前不建议仅为401重新部署。若只需获取正确的调用地址/凭据，可能完全不需要改代码；是否修改平台配置会触发重启/重新发布以平台说明为准，需用户单独执行或授权。若确认头冲突且平台无法透传两种身份，再单独设计最小适配，不能在证据不足时直接改认证逻辑。本分支只新增诊断工具、测试和本文档，无服务/生产配置修改。

## 本地验证结果

诊断工具新增17项合成测试；与真实无数据库启动、错误响应保护、主服务认证与插件契约联合运行147 passed、0 failed、0 skipped（10.37秒）。只有既有SDK的Pydantic弃用警告1项，`git diff --check`通过。真实本地启动测试包含两个无DB场景及各18项HTTP烟测。没有运行数据库全量集成回归，因为本分支没有变更服务、数据库或业务模型。本地通过不等于线上验证；线上健康、平台凭据及教案请求均未获得源站实测结果。
