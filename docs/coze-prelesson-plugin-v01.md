# CoachLoop-FS 智能备课助手：Coze 插件导入候选 V0.1

本包复用 `POST /api/v1/lesson-plans/draft`，没有部署、发布插件或执行 Coze 平台调用。仅支持零基础《冰上双足滑行与身体姿态控制》45分钟模板。教案始终为 draft，知识依据始终 unverified，必须由教师审核；服务 Bearer 不证明教师身份或审核结果。

## 规范核实与兼容性边界

2026-10-29 尝试访问 Coze 官方文档入口 <https://www.coze.cn/open/docs/guides/plugin>，当前云环境代理返回 CONNECT 403，未取得官方页面。此地址仅为文档查询入口，不保证当前页面路由有效。当前官方的 OpenAPI 版本限制、导入大小、嵌套层级、nullable/anyOf/$ref/布尔 enum 支持、认证配置方式和响应截断策略均**待 Coze 平台验证**。不能据此声称官方规范已经核实或已经接通。

提供标准 OpenAPI 3.0.3 JSON 导入候选，避免直接要求导入器支持服务原生的 OpenAPI 3.1。转换把 const 改为单值 enum、数值 exclusiveMinimum 改为 3.0 形式、可空引用展开为 nullable 对象；保留嵌套结构、约束及响应字段，不更改真实 API。生成器遇到未知可空联合则失败，不能静默丢失语义。平台若不支持这些结构，先记录导入报错，评估适配，禁止删除安全字段或放宽服务校验以求导入成功。

`coze-prelesson-plugin-v01.openapi.json` 中 `.invalid` 是不能访问的明确占位地址，**不可直接用于平台调用**。配置实际获准的 HTTPS 服务 origin 后才可尝试导入；本工具只检查地址格式，不验证域名归属、DNS、TLS、服务可用性或公网认证。

## 文件与本地准备

- 导入候选：`docs/coze-prelesson-plugin-v01.openapi.json`。
- 地址生成器：`scripts/build_coze_prelesson_plugin.py`（标准库，无网络访问）。
- 输入及完整预期输出：`docs/prelesson-workflow-v01.example-request.json`、`docs/prelesson-workflow-v01.example-response.json`；也已嵌入候选 OpenAPI 的 example。
- 既有部署预检及18项 HTTP 烟测：`scripts/check_coze_deployment.py`；部署要求见 `docs/coze-deploy-readiness-v01.md`。

在本地终端把 `COACHLOOP_SERVICE_ORIGIN` 设为你已核实且获准使用的 HTTPS 根地址（不含 API 路径、查询参数或凭据），生成最终导入文件：

```bash
.venv/bin/python scripts/build_coze_prelesson_plugin.py \
  --origin "$COACHLOOP_SERVICE_ORIGIN" --output /tmp/coachloop-plugin.openapi.json
```

此命令不需要 Token，也不发送请求。生成文件仍含安全的匿名合成示例；不要把真实学生信息替换进示例。禁止把 Token 放入 origin、OpenAPI、提示词、工具输入、日志或 Git。公网地址与平台兼容性未实测，不提供虚构的“可用服务域名”。

## 最少图形界面操作（具体菜单名待平台验证）

1. 在 Coze 的插件管理中新建自有插件，名称“CoachLoop-FS 智能备课助手”；选择通过 OpenAPI/Schema 导入，粘贴或上传生成文件。若当前版本只允许其他导入形式，停止并记录要求。
2. 核对服务器为实际获准的 HTTPS 地址，工具只包含 `generatePrelessonDraft`，方法 POST，路径 `/api/v1/lesson-plans/draft`。
3. 在**平台安全认证配置**中设置 Bearer/Authorization 请求头注入，关联服务端 `COACHLOOP_PRELESSON_TOKEN` 对应凭据。若界面要求完整头值，使用 `Bearer <密钥>`；若已自动加 Bearer，仅填密钥，避免重复前缀。字段名和密钥保存/共享权限待平台实测。不能安全注入时不得发布或把密钥改为普通输入参数。
4. 用文档合成请求调试，检查完整嵌套输出及所有保护标记。再分别测试缺失凭据、错误凭据、课时44、不支持主题及自动批准字段，确认失败不返回教案。本轮没有执行此平台操作。
5. 在现有课前工作流新增插件节点，绑定下表输入；结束节点输出完整 `lesson_plan` 与审核标记。保留旧文本工作流节点。完成教师确认前不得写成“批准”，不得自动归档为已审核。

插件私有调试、插件发布及公开部署是不同操作；本轮均未发布或部署。未来发布需单独授权并验证平台访问范围、凭据隔离和服务暴露面。

## 输入映射

请求为 JSON 对象，额外字段被拒绝；整数必须以 JSON 整数发送，不能传字符串或布尔值。Schema 不表达全部业务语义，服务仍执行师资/文本/负荷联合校验。

| 字段 | 类型与约束 | 节点来源 |
| --- | --- | --- |
| student_count | 必填 integer，1–500 | 教师输入，合成测试20 |
| theme | 必填，固定“冰上双足滑行与身体姿态控制” | 固定值或教师确认 |
| skill_level | 必填，固定“零基础” | 固定值 |
| total_minutes | 必填 integer，45 | 固定45 |
| coach_count / teacher_count | 可选 integer 0–50 或 null | 实际师资；未知省略/null，不能虚构 |
| venue_conditions / equipment_conditions | 必填 string，1–500字符 | 场地与器材条件；禁止学生隐私 |
| class_label | 可选 string，1–80字符 | 匿名班级标签，默认“匿名班级” |
| estimated_group_active_min | 可选 number，0–45，默认36 | 预计设计活动分钟，非实测 |
| estimated_individual_active_min | 可选 number，0–45，默认25 | 预计个体活动分钟，非实测 |
| estimated_avg_hr | 可选 number，20–250，默认145 | 预计值，非医学目标或学生健康数据 |

## 输出映射

必须保留完整 JSON；不要让模型重写成“已核实”或“已批准”。不要求平台把嵌套字段自动展开。

| 输出 | 真实响应路径 |
| --- | --- |
| 七要素 | lesson_plan.guiding_ideology、teaching_material_analysis、learner_analysis、venue_equipment、safety_precautions、teaching_flow、load_accounting |
| 三阶段时间 | lesson_plan.teaching_flow.phases；total_minutes=45 |
| 分层练习 | lesson_plan.learner_analysis.tiered_plan |
| 预计运动负荷 | lesson_plan.load_accounting；load_basis=estimated_design_assumptions |
| 安全提示 | lesson_plan.safety_precautions；safety_review_status=unreviewed |
| 知识状态 | knowledge_status=unverified；lesson_plan.evidence_log 不得伪造引用 |
| 教师审核要求 | requires_teacher_review=true |
| 审核状态 | **lesson_plan.review_status=draft**（没有顶层 review_status） |
| 组织确认 | lesson_plan.venue_equipment.organization_status=pending_confirmation |

匿名请求示例（完整请求/响应见上述 JSON 文件）：

```json
{"class_label":"MOCK-CLASS-01","student_count":20,"theme":"冰上双足滑行与身体姿态控制","skill_level":"零基础","total_minutes":45,"coach_count":1,"teacher_count":1,"venue_conditions":"合成室内冰场一片，容量待现场确认","equipment_conditions":"合成冰鞋与护具各20套，标志桶若干"}
```

成功为 HTTP200，`status=draft_ready`、`requires_teacher_review=true`、`knowledge_status=unverified`，`lesson_plan.review_status=draft`，三阶段合计45分钟；完整预期响应可直接对照 example-response 文件，本地测试逐字段比对。七要素中的文本为草稿建议，不代表专项教练已确认安全。

## 错误与故障排查

| 状态/现象 | 检查方法 |
| --- | --- |
| 401 | 缺失/无法识别 Bearer；检查安全头注入，不能靠请求体字段替代 |
| 403 | 凭据不匹配；在密钥配置中修正，禁止把密钥贴进反馈或日志 |
| 413 | 超出既有1MiB请求限制；减少输入，不扩大公开API限制 |
| 422 | 字段类型、45分钟、主题/水平、师资矛盾、负荷值或额外批准字段不合法 |
| 503 | 服务端未配置课前凭据，安全关闭；由部署人员核对配置 |
| 404/405 | 检查 origin和POST路径；受限模式仅允许GET健康检查及两个POST；不要改调用旧/run |
| 重定向/TLS/超时 | 停止联调并修复实际HTTPS服务；不得跟随跨域重定向传Token或关闭TLS验证 |
| Schema导入失败 | 记录脱敏错误，核对官方版本与嵌套/nullable/anyOf/引用支持；兼容性尚未实测 |
| 输出缺字段/被截断 | 对照完整响应example，确认平台工具输出上限及结束节点映射；未验证完整保护字段则不投入使用 |
| /openapi.json 不可访问 | 受限部署模式刻意封闭该路径；导入本地静态候选，不为导入开放旧接口 |

错误契约为对象 `{"detail":"..."}` 或 `{"detail":[{"loc":["body","total_minutes"],"type":"...","msg":"..."}]}`；不能将字符串 `"detail"` 或携带 lesson_plan 的错误当成功。平台若只输出HTTP200包装错误，需要实测并显式分支，不能推断生成成功。

服务器部署预检要求显式受限模式、强服务凭据、隔离且获准的 PostgreSQL配置及依赖；本插件文件不解决托管启动、数据库连通性或公网网关限制。原 /run 等在受限模式拒绝，不能通过插件转发调用它们。

## 自动化验证

```bash
.venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_coze_prelesson_plugin.py
# 完整回归必须按既有数据库文档配置隔离 PostgreSQL16，不能使用生产数据库：
.venv/bin/python -B -m pytest -q -p no:cacheprovider
git diff --check
```

专项验证候选文件可重复生成、与实时 FastAPI组件一致、错误/成功响应、45分钟与nullable师资、匿名示例、审核/知识保护和地址边界。测试使用合成凭据和本地 TestClient，不证明 Coze 导入成功。没有安装额外Schema验证器，3.0.3转换使用仓库现有结构校验与针对性测试；平台官方验证器验收仍未完成。

2026-10-29 实际结果：新增插件测试33项；插件与原有视频41项联合运行74 passed；最终全量692 passed、0 failed、0 skipped（27.44秒），含 PostgreSQL16.15 迁移升级/回退/重新升级、受限角色RLS、训练归档及真实本地uvicorn/main HTTP回归。仅有既有Coze SDK的Pydantic弃用警告1项。`git diff --check`通过。中间一次误用旧隔离容器因测试密码不匹配产生506 passed、186 setup errors，未改数据库凭据或业务代码；最终重新创建空白隔离容器完成全量验收，结束后恢复旧容器。未访问生产库。
