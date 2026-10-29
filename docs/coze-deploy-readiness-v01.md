# INTEGRATION-04：Coze最小部署准备（未部署）

基线 main `8fc0f3dfe111aaa892a1d7d92973a5ab5b330633`。本轮只准备代码、脱敏检查工具和操作说明；没有公网地址、没有上传凭据、没有真实学员数据、没有调用Coze AI Coding/模型。

## 审查结论与部署边界

仓库生产链路已修正为 `.coze [deploy] → scripts/setup.sh → scripts/coze_prelesson_run.sh → 预检 → src/main.py`；开发 `[dev]` 仍使用原 `scripts/http_run.sh`。这只是分支内配置变更，不是平台部署。`.coze`声明Python 3.12。main原lifespan连接 `PGDATABASE_URL`，设置UTC并初始化memory检查点；不能把不运行lifespan的TestClient测试当作部署验收。main的 `PGDATABASE_URL` 也有既有SDK读取路径，但本轮专用启动器明确要求安全注入进程环境，避免未经验证的平台变量机制。

- 两个课前POST复用既有Bearer、输入/响应Schema和 `run_prelesson`，仍只有零基础固定主题、45分钟、七要素、预计负荷、draft、教师审核必需和unverified。
- 原 `/run`、`/async_run`、`/stream_run` 等没有统一应用认证，旧入口会产生工作流或异步任务；不可直接公开整个main。
- 新增**显式选择**的 `COACHLOOP_PRELESSON_ONLY=1`：仅允许 GET `/health` 与 POST `/api/v1/lesson-plans/draft`、`/prelesson/draft`；其他路径和方法先返回404，WebSocket关闭，不执行旧处理器。两个POST仍必须Bearer，白名单不代替教师身份认证。
- 缺省/`0`保留旧服务行为；其他flag值使应用导入失败。为保留旧文本流程，开发入口不改、不删旧节点；生产 `[deploy].run` 已强制使用专用启动器，不接受缺失/0/非法profile绕过预检。手工使用旧启动脚本仍只适合受控开发环境，不得替代生产命令。若开发预览也能公网访问，必须同样限制访问面。
- profile=1时 `/run`、`/graph_parameter`、`/openapi.json`、`/docs` 均不公开。**Coze是否依赖这些控制面路径：待 Coze 实测**。若平台需要它们，不要为通过检查直接放开公网旧入口；先确认控制面与公开业务面的隔离能力，或保持未发布状态。

## setup.sh / pyproject.toml检查

`uv.lock`已跟踪；本地离线 `uv lock --check --offline` 成功（139包），冻结runtime requirements导出成功，未安装依赖、未改锁文件。生产 `PIP_TARGET` 分支使用frozen导出，开发分支仍有既有 `uv sync --frozen || uv sync` 回退；生产应确认走预期模式，不能把开发回退当作冻结构建证据。

项目已有PyGObject、pycairo、dbus-python及OpenCV等依赖，可能需要系统库/编译工具。**托管镜像构建这些依赖：待 Coze 实测**。本轮不新增依赖、不删除视频依赖、不安装额外系统包。PIP_TARGET是否在构建/运行阶段存在也待实测；专用启动器在该变量存在时加入PYTHONPATH，避免安装目标不可见。实际原生库加载仍需构建与启动日志证明。

## 最小环境配置（不含值）

| 变量 | 类型/要求 | 状态 |
|---|---|---|
| COACHLOOP_PRELESSON_ONLY | 非秘密，必须为 `1` | 本地可验证；平台注入待实测 |
| COACHLOOP_PRELESSON_TOKEN | 秘密，建议安全生成至少32随机字节；预检只检查至少32个可见ASCII字符且无空白，不证明随机性 | 只放秘密配置，启动前注入；平台机制待实测 |
| PGDATABASE_URL | 秘密，明确的 `postgresql://` 连接串，使用获批准托管库/最小权限账号 | 不打印值；托管连接与memory初始化权限待实测 |
| COZE_WORKSPACE_PATH | 平台工作目录；本地缺省`.` | 平台值待实测 |
| DEPLOY_RUN_PORT | 平台运行端口；项目缺省5000 | 平台分配/健康检查策略待实测 |
| PIP_TARGET | 平台可选依赖安装目录 | 构建及运行可见性待实测 |

凭据只授权生成草稿，不能证明教师审核。服务不接受“平台已认证”等自报头替代Bearer。用TLS和平台秘密管理；不要将Token放URL、普通表单、示例JSON、日志或Git。秘密轮换需重建应用/重启，因为认证闭包在路由构建时读取配置。禁止为了联调关闭认证或打印环境变量全集。

## 专用启动器与检查工具

**本轮不运行公网启动命令。**仓库 `[deploy].run` 已指向下列命令；Coze是否实际读取它仍待平台验证：

```bash
bash scripts/coze_prelesson_run.sh
```

它先运行本地预检，不满足profile/凭据/明确数据库URL/依赖/响应契约文件条件就退出；成功后使用原main入口及平台端口。平台若覆盖启动命令，必须核对其仍为受检入口，不能回退旧脚本跳过检查。修改仓库部署配置不等于执行发布，本轮没有触发平台部署。

本地预检（只读环境与包版本存在性；不连接数据库、不输出任何值）：

```bash
python scripts/check_coze_deployment.py --preflight
```

HTTP检查（仅在地址获批准后由操作者执行；凭据从当前安全环境读取，不作为命令行参数）：

```bash
python scripts/check_coze_deployment.py --base-url https://YOUR-APPROVED-ORIGIN
```

`YOUR-APPROVED-ORIGIN`是占位符，不是已发布地址。只允许无用户名/密码、路径、query和fragment的HTTPS origin；本地回环测试可用HTTP。远程HTTPS沿用系统代理与CA验证，没有关闭TLS选项；拒绝重定向，避免Bearer被带到其他地址。本地回环测试直连，不访问外部服务。

一次检查18项：健康、两个入口的缺失/错误认证与伪造网关头拒绝、两个完整合成草稿、非法课时/主题/自报批准拒绝，以及旧三个路径的阻断。检查器先按已发布响应Schema核对必填结构、类型、常量/枚举及基础边界，再核对版本、七要素、三阶段时间、负荷公式、draft、教师审核、unverified及安全待确认状态。其标准库结构检查支持当前生成契约使用的子集，不是通用JSON Schema引擎。报告只含固定检查名、布尔结果和状态码，不含响应正文、URL、原始异常或凭据。退出码0表示这些观察项通过，1表示检查失败，2表示命令参数错误；参数错误也不回显参数值。

旧入口只发送GET探测，不POST旧工作流、不提交异步任务、不调用模型；405会被判为未证实阻断，而不是安全通过。检查成功只是端点观察结果，不等于网关身份认证证明、数据库权限审计或Coze发布完成。profile=1会在所有方法上阻断旧路径，自动化测试验证处理器未执行。

## 脱敏示例、OpenAPI和最小节点

复用既有已测试文件，不重复生成另一套业务模型：

- [匿名合成输入](prelesson-workflow-v01.example-request.json)
- [本地生成输出](prelesson-workflow-v01.example-response.json)
- [输入Schema](prelesson-workflow-v01.request.schema.json)、[输出Schema](prelesson-workflow-v01.response.schema.json)
- [仅两个课前路径的OpenAPI](coze-integration-v01.openapi.json)

profile=1不暴露main完整OpenAPI，请使用上述文件配置插件；Coze是否支持文件导入、如何绑定服务域名与认证：**待 Coze 实测**。不要将旧 `/run` 注册为课前插件，也不要把旧mock文本结果当作七要素教案。

最小工作流：开始表单（人数、固定主题、零基础、45分钟、师资、场地器材）→ 插件HTTP POST规范路径 → 状态判断 → 教师审核交接展示 → 结束。服务Token放平台安全认证配置；错误分支不补写教案。输出保持 `requires_teacher_review=true`、`lesson_plan.review_status=draft`、`knowledge_status=unverified`。当前没有教师批准写回API；按钮继续不能改写为approved。

## 最少GUI操作（全部由你在获批准后进行）

1. 在代码来源界面同步已审查提交；不要启动AI Coding重新生成代码。GitHub同步/分支选择控件名称**待 Coze 实测**。
2. 在安全配置中设置上述必需变量，仅部署环境启用profile；确认托管PostgreSQL与memory启动权限。不要把秘密发到聊天或普通配置文件。变量是否进入进程环境**待 Coze 实测**。
3. 核对平台实际使用仓库声明的专用生产启动器；若被界面配置覆盖，先修正并停止发布。确认构建、预检和启动日志后，由你决定是否发布；构建镜像、端口及控制面兼容性**待 Coze 实测**。本轮没有点击发布。
4. 平台给出实际HTTPS地址后，从受控环境运行18项烟测，保存脱敏通过/失败报告。未通过时不开放旧入口、不关闭认证。
5. 在插件/HTTP节点导入现有OpenAPI并配置安全Bearer，映射匿名示例，接上状态判断和教师审核交接，运行一次合成班级工作流并保存脱敏结果。插件安全头转发及在线端到端行为**待 Coze 实测**。

这些步骤不需要调用AI Coding或付费模型；平台构建、托管资源及发布的计费规则仍需你按实际账户确认。公网地址、在线Coze运行和实际教师审核均不能由本地测试替代。

## 本轮实际自动化结果（非平台发布证据）

全新隔离PostgreSQL 16.15，最终全量 **593 passed、0 skipped、0 failed**；部署准备/安全43通过，真实main（旧/课前profile × 有/无Bearer）及回环18项检查4通过。主服务旧行为/认证32通过，数据库与训练接口目录210通过，原视频及教练审核41通过；专项均包含在全量中，不重复累计。有一项既有第三方SDK的Pydantic弃用警告。锁文件离线一致性、冻结runtime导出、Shell语法及 `git diff --check` 均通过。

没有对Coze平台发出部署、密钥写入或模型请求，没有公开地址、生产库连接或真实学员数据。部署前结论：本地准备可审查；Coze原生依赖构建、进程变量注入、健康/控制面兼容、HTTPS域名和插件认证转发仍全部**待 Coze 实测**，未具备“公网接口已可用”的证据。

## PR #6 独立安全审查修复

- P1：原 `[deploy].run` 仍使用旧脚本，可能在漏配profile时绕过安全预检。现改为专用启动器，开发入口保持不变；测试确认缺失/0/非法profile、短凭据、缺失或错误数据库URL均在主服务启动前退出。平台是否遵从该命令仍待Coze实测。
- P2：旧烟测仅要求七要素为非空对象，可能接受缺字段和错误版本。现复用本地已发布响应Schema做结构检查，并核对固定版本、主题、响应班级/人数与提交的合成输入一致，以及无真实课堂/视频声明。响应Schema文件必须随代码打包；缺失时预检/烟测拒绝通过，文件打包行为待Coze实测。
- 新增处理器调用计数、编码/归一化路径、真实HTTP重定向及错误配置反例。课前白名单启用时旧处理器调用计数必须保持0；重定向目的路径不能收到请求/Bearer。Origin中的控制字符、空白及反斜线拒绝。未更改七要素Agent、视频、数据库或已有Bearer逻辑。

PR #6修复后最终独立验收：全新隔离PostgreSQL 16.15，全量 **614 passed、0 skipped、0 failed**；部署安全对抗64通过，真实main/profile/HTTP检查器4通过。主服务认证与契约32通过，数据库及训练接口目录210通过，原视频41通过（专项包含在全量中）。修复前3项独立反例失败，修复后均拦截。`git diff --check`通过，仅有一项既有SDK弃用警告。代码层面未发现未关闭的P0/P1/P2合并阻断问题；Coze真实启动命令、契约文件打包、秘密注入、系统依赖、控制面/健康探测及HTTPS/插件转发仍须人工验证，本轮没有部署或上传凭据。
