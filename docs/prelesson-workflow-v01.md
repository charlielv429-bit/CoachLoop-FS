# INTEGRATION-02：课前七要素教案工作流

基线 main `b6e1b0bfec5381b8c18f690ffcdb1cc412b4fcae`。本实现只生成草稿，不部署、不写数据库、不调用知识库/大模型/MediaPipe/OCR，不批准教案。

## 已核查的旧入口与新增入口

`.coze` 的入口是 `src/main.py`；其中 `GraphService` 固定加载 `graphs.graph`。旧 `graphs/graph.py` 保留 `validate_node → gen_feedback_node → finalize_node` 及校验失败分支。本次不修改 `.coze`、旧主图、旧节点、`main.py`、视频分析、数据库或训练归档接口。

新增独立 LangGraph：`graphs.prelesson_graph.prelesson_graph`，沿用项目的 StateGraph、Pydantic输入/输出与确定性节点结构：

`DraftRequest → generate_prelesson_draft → await_teacher_review → DraftResponse`

公开 Python 边界：`graphs.prelesson_graph.run_prelesson(payload)`，先校验完整请求再调用图。教师审核交接节点只输出待审核草稿，不代表人工审核已发生。

独立 HTTP 工厂：`integrations.prelesson.api:create_app`；不挂载旧 `/run`，不改变原工作流选择逻辑。复用已有训练接口的有限JSON解析与1 MiB请求上限组件，不调用其数据库服务。

## 输入/输出契约

- POST `/api/v1/lesson-plans/draft`
- [请求 JSON Schema](prelesson-workflow-v01.request.schema.json)
- [响应 JSON Schema](prelesson-workflow-v01.response.schema.json)，按 serialization 模式包含 `display_result` 等实际输出字段。
- [OpenAPI](prelesson-workflow-v01.openapi.json)；本地应用也提供 `/openapi.json`。
- [合成请求](prelesson-workflow-v01.example-request.json)、[实际本地生成响应](prelesson-workflow-v01.example-response.json)。示例不代表Coze平台运行。

| 输入字段 | 契约 |
|---|---|
| class_label | 可选匿名班级标签，缺省“匿名班级”；不填学生姓名、身份或健康记录 |
| student_count | 必填整数1–500；500是接口资源边界，不表示安全班额 |
| theme | 必填，固定“冰上双足滑行与身体姿态控制” |
| skill_level | 必填，固定“零基础”；明确映射到已有Agent的“初学者”模板参数 |
| total_minutes | 必填整数45；字符串或45.0均拒绝 |
| coach_count / teacher_count | 可选非负整数，接口资源上限50；未知省略或null，不能当作0或编造默认人数 |
| venue_conditions / equipment_conditions | 必填非空单行文本，各最多500字符；与师资字段冲突会拒绝 |
| estimated_group_active_min | 可选预计活动时间，缺省36，范围0–45分钟 |
| estimated_individual_active_min | 可选预计个体练习时间，缺省25，范围0–45分钟 |
| estimated_avg_hr | 可选预计心率，缺省145次/分；20–250仅为既有录入有效域，不是医学安全目标 |

数值为JSON number，人数和课时必须为integer，禁止布尔值和数字字符串。NaN/Infinity/巨大指数、重复JSON键、未知字段和超大请求拒绝。不能提交 `review_status`、citation、KB核验记录、姿态事件或课堂实测声明。

响应顶层：

```json
{
  "schema_version": "prelesson-draft-v1",
  "status": "draft_ready",
  "requires_teacher_review": true,
  "knowledge_status": "unverified",
  "load_basis": "estimated_design_assumptions",
  "lesson_plan": {"review_status": "draft"}
}
```

上面是节选；完整响应见示例及Schema。`lesson_plan`包含七要素、9/29/7分钟三阶段流程、分层练习、组织建议、安全提示、负荷公式/分子/分母/原始结果与展示值、证据清单。缺省负荷是已有Agent的预计设计假设，不是实测或由学生人数推断的生理数据；不会承诺达标。

所有组织方案保持 `pending_confirmation`，安全审核保持 `unreviewed`。课标和安全资料始终未核实，引用为空；此入口不接收或认证人工核验声明。师资不足、未知或场地风险未确认时仍只能提供待确认草稿，不能当作可直接实施的教学许可。教师确认需要真实教师工作流，本接口没有批准/数据库归档能力。

## 本地可运行方式

CLI（无需凭据、数据库或网络）：

```bash
PYTHONPATH=src .venv/bin/python -B -m integrations.prelesson \
  --input docs/prelesson-workflow-v01.example-request.json
# 也可 --input - 从stdin读取JSON。无效输入退出码2，stdout不输出教案。
```

HTTP（仅本地回环测试；不部署）：

```bash
# 通过安全环境配置提供 COACHLOOP_PRELESSON_TOKEN，勿提交或打印其值。
PYTHONPATH=src .venv/bin/python -B -m uvicorn integrations.prelesson.api:create_app \
  --factory --host 127.0.0.1 --port 5011
curl --fail-with-body http://127.0.0.1:5011/api/v1/lesson-plans/draft \
  -H "Authorization: Bearer ${COACHLOOP_PRELESSON_TOKEN}" \
  -H 'Content-Type: application/json' \
  --data-binary @docs/prelesson-workflow-v01.example-request.json
```

未配置服务凭据返回503；缺失/错误凭据401/403；无效需求422；请求超过1 MiB返回413；成功200并 `Cache-Control: no-store`。凭据只授权生成草稿，不能证明具体教师身份或人工审核真实性。不要在Coze提示词、表单、日志或截图中保存服务凭据。Coze平台不能直接访问本机127.0.0.1，本轮不创建公网地址。

## Coze平台需要配置的节点（配置说明，非已发布流程）

1. **开始/表单节点**：按请求Schema建立人数、主题、水平、课时、教练/教师人数、场地和器材变量；匿名班级标签可选。主题/水平固定为当前支持值，课时为integer 45。未知师资传null或省略。预计负荷可隐藏并保留明确的设计假设说明，或由教师显式输入。
2. **插件工具或HTTP节点**：在平台支持的方式导入OpenAPI并配置 POST 路径，将上述变量映射到JSON body。服务地址须由后续获批准的运行环境提供；服务凭据放平台安全认证配置。禁止用LLM直接生成/拼接审批和引用字段。
3. **结果判断节点**：仅在HTTP 200且 `status=draft_ready`、`requires_teacher_review=true`、`lesson_plan.review_status=draft` 时展示草稿。401/403/413/422/503进入错误分支，提示检查配置或教学条件，不使用旧结果冒充成功，不补写不支持主题的教案。
4. **教师审核交接节点**：展示七要素、三阶段、负荷、待核实依据及安全/组织状态；要求教师在真实审核流程中复核。本轮没有批准API，因此不得将点击“继续”改写为approved。
5. **结束节点**：输出完整结构化 `lesson_plan` 与审核/证据标记；审核未完成时流程停留在草稿交接。保留原文本模拟反馈工作流，使用独立课前入口，不替换旧开始/校验/模拟反馈节点。

需要平台侧提供：已有工作流节点截图或导出（去除秘密）、插件/HTTP节点能力与Schema限制、可用的获批准服务地址、认证配置方式及教师审核节点机制。当前没有Coze平台配置访问权限，未导入插件、未修改在线工作流，也未完成平台真实调用；不能将本地TestClient或CLI测试称为“Coze已接通”。

## 验证

```bash
.venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_prelesson_workflow.py
# 全量需显式启用本项目隔离PostgreSQL 16测试库，禁止生产数据库。
.venv/bin/python -B -m pytest -q -p no:cacheprovider
```

测试覆盖完整教案、45分钟/七要素/负荷、非法输入、伪造引用和审批、人员边界、离线依赖、CLI/HTTP、公开Schema与实际响应，以及旧文本工作流原节点和合法/非法分支。视频、数据库与训练接口沿用已有测试联合验证。本地测试数量与具体提交以开发交付报告为准；这些结果不替代Coze平台联调或教师审核。

本轮实际本地验收：全新隔离PostgreSQL 16.15，全量 **481通过、0失败、0跳过**；新增课前工作流单独 **46通过**，数据库及训练归档单独 **206通过**，原V2—V5.2视频及审核单独 **41通过**。原435项包含在全量结果中，专项结果不重复累计。有一项既有第三方SDK的Pydantic弃用警告。`git diff --check`通过；未连接生产数据库，未部署或调用Coze平台。
