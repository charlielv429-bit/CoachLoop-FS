# INTEGRATION-04：Coze最小部署准备（未部署）

基线 main `8fc0f3dfe111aaa892a1d7d92973a5ab5b330633`。本轮只准备代码、脱敏检查工具和操作说明；没有公网地址、没有上传凭据、没有真实学员数据、没有调用Coze AI Coding/模型。

## 审查结论与部署边界

仓库生产链路为 `.coze [deploy] → scripts/setup.sh → scripts/coze_prelesson_run.sh → 预检 → src/main.py`；开发 `[dev]` 仍使用原 `scripts/http_run.sh`。配置变更不等于平台部署，`.coze`声明Python 3.12。DEPLOY-FIX-01后，main与路径白名单共用导入时固定的profile：`COACHLOOP_PRELESSON_ONLY=1` 的真实lifespan跳过数据库连接、memory schema/PostgresSaver.setup、旧工作流构建和异步运行时；**无需任何数据库变量，也不使用注入的数据库连接**。普通模式保留原初始化路径。不能把替换lifespan的路由单测当作真实启动证据。

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
| PGDATABASE_URL / DATABASE_URL / PGHOST等 | 课前受限模式不需要，也不用于连接数据库 | 不复制开发连接，不依赖平台自动注入；无需业务迁移或种子数据 |
| COZE_WORKSPACE_PATH | 平台工作目录；本地缺省`.` | 平台值待实测 |
| DEPLOY_RUN_PORT | 平台运行端口；项目缺省5000 | 平台分配/健康检查策略待实测 |
| PIP_TARGET | 平台可选依赖安装目录 | 构建及运行可见性待实测 |

凭据只授权生成草稿，不能证明教师审核。服务不接受“平台已认证”等自报头替代Bearer。用TLS和平台秘密管理；不要将Token放URL、普通表单、示例JSON、日志或Git。秘密轮换需重建应用/重启，因为认证闭包在路由构建时读取配置。禁止为了联调关闭认证或打印环境变量全集。

## DEPLOY-FIX-01：课前无数据库启动

基于main `50f958e`。只有课前受限模式跳过原lifespan，未删除旧路由、未修改数据库模型/迁移/视频/教案Agent。数据库变量即使存在或格式错误，也不会用于课前启动；不进行变量名称适配，不读取SDK数据库配置，不建立数据库连接或执行DDL。普通模式（缺省/0）仍走原数据库、检查点、旧工作流及异步运行时路径，不能将普通模式直接公开公网。

部署所需应用配置只有 `COACHLOOP_PRELESSON_ONLY=1` 与安全注入的 `COACHLOOP_PRELESSON_TOKEN`；另需平台提供或核对工作目录、运行端口和依赖可见性。模式在导入时固定，修改模式或密钥后都需重启。原服务仍导入数据库SDK/驱动模块，因此无数据库运行不等于可以从现有依赖中卸载驱动。

`tests/test_prelesson_db_free_startup.py` 包含真实 `bash scripts/coze_prelesson_run.sh → 预检 → python src/main.py → uvicorn main:app` 测试，不替换lifespan。它清除数据库相关变量，在子进程Python初始化阶段安装拒绝探针，禁止数据库URL解析/引擎创建/连接、PostgresSaver.setup、旧工作流构建和异步运行时初始化，并通过审计钩子拒绝出站socket连接；任何尝试即使被调用方吞掉异常也记录失败。探针就绪标记确认预检与主服务两个Python进程均已安装。验证健康检查、两个POST的Bearer与草稿保护、旧路由阻断和18项真实HTTP烟测；另测注入无效数据库变量仍无连接，以及普通模式原初始化/关闭逻辑不变。运行命令：

```bash
.venv/bin/python -B -m pytest -q -p no:cacheprovider \
  tests/test_prelesson_db_free_startup.py tests/test_deploy_readiness.py tests/test_deploy_error_responses.py
```

旧预检中“缺少/非法数据库URL必须阻止课前启动”的两项断言按新契约移除，替换为无DB/无效DB可启动的正向测试；认证、非法profile和错误响应结构拒绝断言保持。没有放宽401/403/422错误响应检查。

Coze尚需验证实际构建镜像、启动器是否被采用、生产模式/端口与健康探针要求、环境变量与安全凭据注入、HTTPS与插件认证转发。若平台要求被白名单封闭的控制面路径，不能直接放开旧接口；先明确平台隔离机制。本轮没有部署或接触生产数据库。

DEPLOY-FIX-01本地实际验收：新启动模块9 passed；启动/部署/错误响应专项116 passed；全量在全新隔离PostgreSQL16.15上710 passed、0 failed、0 skipped（34.03秒），包含原视频41项、真实普通模式启动、数据库迁移往返/RLS及训练归档。两个无DB真实启动场景各通过18项HTTP烟测，数据库/旧初始化/出站连接拒绝探针零触发。仅有既有Coze SDK的Pydantic弃用警告1项。`git diff --check`及启动器shell语法检查通过。全量数据库仅用于验证普通模式和既有业务模块，课前部署不需要它。

## 专用启动器与检查工具

**本轮不运行公网启动命令。**仓库 `[deploy].run` 已指向下列命令；Coze是否实际读取它仍待平台验证：

```bash
bash scripts/coze_prelesson_run.sh
```

它先运行本地预检，不满足profile/凭据/依赖/成功与错误契约文件条件就退出；成功后使用main入口及平台端口。预检报告明确标记 `database_mode=disabled`，不解析或校验数据库变量。平台若覆盖启动命令，必须核对其仍为受检入口，不能回退旧脚本跳过检查。修改仓库部署配置不等于执行发布，本轮没有触发平台部署。

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
2. 在安全配置中设置profile=1与课前Bearer秘密，并核对工作目录/端口；课前模式不配置数据库，也不需要memory建表权限。不要把秘密发到聊天或普通配置文件。变量是否进入进程环境**待 Coze 实测**。
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

## PR #6 错误响应假通过P2修复

补充独立审查发现，c13c1d4的原614项测试未覆盖三种错误响应：422返回JSON字符串 `"detail"`，401/403响应体仍携带完整教案，均可能被烟测误判通过。本轮把三个反例纳入 `tests/test_deploy_error_responses.py`，并修复检查器，真实API及OpenAPI契约不变。

- 所有预期4xx/5xx统一使用本地 `docs/coze-integration-v01.openapi.json` 的 `ErrorResponse`/`ErrorDetail` Schema检查；与真实Pydantic错误模型做一致性测试。不再仅凭状态码或字符串成员判断。此错误契约文件与成功响应Schema均须随代码打包；缺失时预检/烟测不能通过。
- 错误必须是API实际使用的 `detail` 对象封套。烟测额外拒绝成功字段、`draft_ready` 标记及嵌套/JSON编码的成功载荷；这是部署检查的安全限制，不修改服务端允许的契约。错误位置中引用 `lesson_plan` 字段名仍是合法错误信息。
- 401、403、422及旧路径的403/404都校验错误结构。400、405、413、503等未列入某检查预期集合的状态仍失败；不会为凑通过而扩大状态码集合。18项HTTP检查数量不变。
- 报告仍只输出固定检查名、布尔值和合法整数状态码；非法类型状态码、原始响应、URL、异常和凭据均不回显。原始数据类型错误、成功载荷混入、合法字符串/字段错误数组、实际API错误及其他状态边界均有自动化覆盖。

该P2修复实际结果：全新隔离PostgreSQL 16.15，全量 **659 passed、0 skipped、0 failed**；原3项异常响应反例 **3/3通过**；部署专项109通过；真实本地uvicorn/HTTP烟测4通过；数据库及训练接口210通过，原视频41通过。新增45项正式测试，包括37项对抗（含原3项）及8项正向/错误契约兼容测试。真实API和OpenAPI文件未改动，没有扩大任何预期状态码集合。`git diff --check`通过，仅有既有SDK弃用警告。代码范围内未发现剩余已确认的P0/P1/P2阻断问题；Coze平台命令、文件打包、秘密注入和在线联调仍待人工验证。
