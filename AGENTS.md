## 项目概述
- **名称**: coachloop_feedback
- **功能**: 花样滑冰 AI 教学辅助的最小可运行通用技术框架。接收学员与技能输入，以确定性代码完成字段校验；合法输入生成仅保留原始事实的结构化模拟反馈（无专业判断、无训练建议），非法输入返回字段级错误。不调用大模型，不接入知识库/数据库/插件/外部 API/摄像头。

> 说明：目标群体、动作标准、候选技能编码、评价指标与正式报告均待专业同学确认（P0/P0.1 文档另行维护）。

### 节点清单
| 节点名 | 文件位置 | 类型 | 功能描述 | 分支逻辑 | 配置文件 |
|-------|---------|------|---------|---------|---------|
| validate_node | `src/graphs/nodes/validate_node.py` | task | 确定性校验字段存在性/类型/非空/候选范围 | - | - |
| should_generate_feedback | `src/graphs/graph.py` | condition | 根据校验状态决定后续走向 | valid→gen_feedback_node, invalid→finalize_node | - |
| gen_feedback_node | `src/graphs/nodes/gen_feedback_node.py` | task | 合法输入生成结构化模拟反馈，evidence_overall 固定 insufficient | - | - |
| finalize_node | `src/graphs/nodes/finalize_node.py` | task | 汇总 run_status/validation_result/feedback/mock/errors 作为最终输出 | - | - |

**类型说明**: task(task节点) / agent(大模型) / condition(条件分支) / looparray(列表循环) / loopcond(条件循环)

### 子图清单
- （无子图，主图为无环 DAG）

### 技能使用
- 无（纯确定性代码，不加载任何集成技能）

### 工具模块（非工作流节点）
- **视频分析 / 姿态特征计算**（`src/tools/video_analysis/`）：纯 MOCK 关键点几何计算，不做真实视频识别、不设评价阈值、不推断重心/冰刀压力/内外刃。
  - `schemas.py`：数据模型（Landmark/KeypointFrame/KeypointDataset/FeatureResult/AnalysisOutput）
  - `keypoint_io.py`：JSON 读取与校验（强制 `is_mock=true` + `mock://` 来源，拒绝冒充真实识别）
  - `geometry.py`：纯几何（膝角/躯干角/髋踝相对偏移），退化抛 `DegenerateGeometryError`
  - `features.py`：逐帧特征提取（缺失/NaN→按缺失处理；退化→标记 `degenerate`）
  - `run.py`：CLI 入口（`python -m tools.video_analysis.run <json> --side left`）
  - 坐标约定：归一化图像坐标，x 右、y 下；特征为 2D 可观测几何量，非三维测量
  - 涉及视角：膝角/躯干角/髋踝偏移均适用于侧（侧向 90°）视角
  - 运行：`PYTHONPATH=src pytest -q tests/test_video_analysis.py`
  - MOCK 数据：`assets/mock/pose_keypoints_mock.json`
- **V2 真实视频识别**（`src/tools/video_analysis/`，需隔离环境 `.venv-video`）：
  - `mp_mapping.py`：MediaPipe 33 点 → KeypointFrame 纯映射（无 mediapipe 依赖，主 venv 可测）
  - `pose_extractor.py`：MediaPipe 1.2 新版 tasks API，MP4→33 点→复用 extract_features；`is_mock=false`；缺失即标记 `detected=false`，不做插值冒充
  - `extract_video.py`：CLI（`.venv-video/bin/python -m tools.video_analysis.extract_video <mp4> --side left`）
  - **前置阻碍（real 识别暂不可运行）**：① 需获授权测试视频；② 需 `pose_landmarker.task` 模型文件（应放 `assets/models/`，MediaPipe 不自带）；③ 系统库 `libEGL.so.1` 缺失（需批准安装系统包）。缺任一即抛 `MissingPrerequisiteError`。
  - 隔离环境：`.venv-video`（mediapipe 1.2.0 + opencv-contrib + pydantic），**不污染主 `.venv`**
- **真实视频识别待完成项**（本轮未执行端到端）：
  - ① 提供获授权测试视频；② 放置 `assets/models/pose_landmarker_lite.task` 模型；③ 批准安装 `libEGL/libGL` 系统库（headless 环境缺失）
  - 满足后：`.venv-video/bin/python -m tools.video_analysis.extract_video <mp4> --side left` 即可复用 extract_features 产出 `is_mock=false` 的逐帧特征与有效帧比例
- **V4-MVP 姿态变化事件检测**（`src/tools/video_analysis/`，纯逻辑，仅需主 `.venv`）：
  - `event_detection.py`：复用 V2 pose_result 的 knee/torso/hip_ankle 特征，轻量平滑（居中移动平均）+ 相对稳健基线变化检测 + 连续异常帧合并为事件（起止时间/时长/变化幅度/次数）；按可见度/缺失/孤立突跳标记 `review_required`。探索性阈值，**非评分/非诊断**，仅 2D 可观测几何量
  - `events_cli.py`：CLI（`PYTHONPATH=src .venv/bin/python -m tools.video_analysis.events_cli --input /tmp/pose_result.json -o /tmp/event_detection_result.json --print-summary`）
  - 测试：`tests/test_event_detection.py`（无事件/连续事件合并/低质量帧/缺失特征/自定义阈值）
  - 界定：不重跑视频推理，不推断双腿遮挡/真实重心/冰刀用刃（需教练结合 3D/冰面复核）
- **V5-MVP 教练事件审核**（`src/tools/video_analysis/`，纯逻辑，仅需主 `.venv`）：
  - `event_review.py`：复用 V4 事件结果，生成稳定可复现 `event_id`（sha1(video|frame_start|frame_end|feature)）；审核状态机 pending/confirmed/normal_movement/tracking_error/uncertain；记录审核人/审核时间/备注；`original_event` 与 `source` 不可变，审核写回仅追加 `review_history`（审计可追溯）
  - `events_review_cli.py`：CLI（`PYTHONPATH=src .venv/bin/python -m tools.video_analysis.events_review_cli --input /tmp/event_detection_result.json -o /tmp/event_review_result.json`；`--apply <event_id> --status <s> --by <name> --note <txt>` 写回单条审核）
  - 测试：`tests/test_event_review.py`（状态合法性/稳定 id/原始数据不被覆盖/审计轨迹可追溯）
  - 界定：不做自动动作诊断、不接前端/大模型/数据库；审核结果以 JSON 持久化供后续 Agent 消费
- **V5.2 最小教练审核界面**（`src/tools/video_analysis/`，标准库 HTTP 服务）：
  - `review_ui.py`：本地 HTTP 服务（`PYTHONPATH=src .venv/bin/python -m tools.video_analysis.review_ui --port 8766`）；路由 `/`(页面)、`/video`(同源视频 Range 位流，支持点击跳转播放)、`/api/events`、`/api/review`、`/api/demo`、`/api/demo/reset`、`/api/demo/review`
  - `review_ui_static.html`：纯净中文前端（事件表/点击跳转/四种审核+备注/演示 DEMO 面板）
  - 持久化：真实审核→`/tmp/coach_review.json`，演示→`/tmp/coach_review.demo.json`（演示强制 `[demo]` 署名，与真实结果隔离）
  - 界定：不接大模型/数据库；视频不可访问时仅提示、不伪造播放

### 关键约定
- `skill_code`：仅校验为**非空字符串**，不做候选白名单硬拦截（候选编码占位仅供参考，待专业确认）
- `duration_min` / `stability_score`：接受**整数**或**可无歧义转整数的纯数字字符串**（如 "30"、"3"），在工作流入口标准化为 `int`；拒绝小数/`abc`/空串/布尔
- `stability_score` 为空时允许通过；不将候选评分范围或训练时长范围作为正式拦截条件
- 非法输入不生成模拟反馈，仅返回 `errors` 与 `validation_result`

### 教案生成 Agent（独立确定性模块）
- 目录 `src/agents/lesson_plan_agent/`，使用主 `.venv`；草稿生成和测试不调用大模型、视频识别或付费 API。
  - `schemas.py`：七要素结构；当前 `TeachingFlow` 严格45分钟，准备8–10、基本28–30、结束5–7；`GeneralTeachingFlow` 保留其他课时扩展边界。
  - `load_calc.py`：原始精度计算群体/个体密度和平均心率；仅 `display_result` 舍入。共享模型及导出边界复核分母、总课时、单位和计算结果；非法心率/非有限数值拒绝。
  - `guard.py`：基于结构化审核状态保护未确认事件；事件ID仅允许最多64位ASCII字母、数字、下划线和连字符。构造后修改也须在插入观察句、条目及教案导出前重新检查。
  - `generate_draft.py`：仅支持初学者《冰上双足滑行与身体姿态控制》；师资与分组依据显式输入，组织安排仍待确认，安全要求仍待专项审核。`build_draft()` 生成草稿，`draft_to_json()` 执行输出检查；CLI `python -m agents.lesson_plan_agent.generate_draft`。
  - `kb_adapter.py`：检索客户端/配置可注入；分数和来源可定位不等于证据支持。目录、纯标题、图片和来源不一致片段为C；未确认支持关系的正文为B；只有来源、原文与当前陈述完全绑定的可信人工核验记录才可形成A级教学依据。无A级证据维持 `unverified`，构造后添加 citation 也禁止导出。检索不会自动制造人工核验记录；不运行OCR、不修改在线知识库。
- 教案测试：`tests/test_lesson_plan_agent.py`、`test_generate_draft.py`、`test_generate_draft_consistency.py`、`test_kb_adapter.py`、`test_lesson_reliability_round2.py`、`test_lesson_final_reliability.py`；全部使用合成数据或注入客户端，不依赖真实Coze凭据或网络。
- 与数据库及训练归档模块联合测试：隔离PostgreSQL 16，显式设置专用 `TEACHING_DATABASE_URL` 与 `TEACHING_ALLOW_MIGRATION=mock-only`，运行 `.venv/bin/python -B -m pytest -q -p no:cacheprovider`；不得连接生产库。参考 `docs/teaching-db-v01.md` 与 `docs/reviewed-training-import-v01.md`。
- 边界：人工核验记录真实性依赖可信上游，尚未实现真实Coze来源认证；本模块不自动部署、不推断专项技术合格线，也不替代教师/教练审核。
- `errors` 为结构化列表，`code` 区分 `missing_field` / `invalid_type` / `empty`
- 无知识库依据：`evidence_overall = "insufficient"`，`mock = true`
### INTEGRATION-02 独立课前工作流
- `src/graphs/prelesson_graph.py`：`generate_prelesson_draft → await_teacher_review`，复用教案Agent，不修改原 `graphs.graph.main_graph` 的三个节点或分支。
- 输入 `integrations.prelesson.schemas.DraftRequest`：零基础、固定双足滑行主题、45分钟；结构化人数/师资与场地器材条件。输出 `DraftResponse` 含七要素、预计负荷、`draft`、`requires_teacher_review=true`、`knowledge_status=unverified`。
- Python入口 `run_prelesson(payload)`；CLI `PYTHONPATH=src .venv/bin/python -m integrations.prelesson --input docs/prelesson-workflow-v01.example-request.json`；独立HTTP工厂 `integrations.prelesson.api:create_app`，POST `/api/v1/lesson-plans/draft`，服务凭据配置缺失时关闭。
- 不调用知识库/大模型/视频识别，不写数据库或批准教案；凭据仅授权草稿生成，不认证教师审核。Schema、OpenAPI、合成示例与Coze节点配置说明见 `docs/prelesson-workflow-v01.md`，平台未实际接通或部署。
- 新测试 `tests/test_prelesson_workflow.py`，保留旧文本反馈流程回归，并与已有隔离PostgreSQL测试联合运行。

### INTEGRATION-03 主服务课前路由
- `src/main.py` 通过 `integrations.prelesson.api.create_router(include_alias=True)` 挂载 POST `/api/v1/lesson-plans/draft` 和 `/prelesson/draft`，复用 `run_prelesson`，不删除旧工作流节点。
- 两个路径均强制应用Bearer验证；配置缺失默认关闭，不信任未经验证的平台网关身份头。服务凭据不证明教师审核身份，draft/unverified/45分钟保护不变。
- JSON限制与错误脱敏通过 `PrelessonRoute` 局部生效，不替换主服务旧接口的全局处理。旧主服务接口并未自动获得新鉴权，公网发布必须单独验证路由访问策略。
- 新测试 `tests/test_prelesson_route.py`（lifespan替换的单元测试）和 `tests/teaching/test_main_prelesson_http.py`（真实uvicorn/main lifespan＋隔离PostgreSQL），后者必须在专用数据库中实际执行。
- 安全方案、181项跳过说明、主服务OpenAPI切片和下一阶段最小边界见 `docs/coze-integration-v01.md`；不覆盖Coze本地未提交文件，不部署。

### INTEGRATION-04 部署准备（未部署）

- 课前交互控制台：`integrations.prelesson.console.create_console_app(port)`为独立loopback应用，不挂main；本地HttpOnly/SameSite会话与Origin/Host/CSRF校验通过后注入临时内部Bearer复用原API。禁止生产Token、公开代理/公网绑定，不能当教师身份认证。`scripts/run_prelesson_console.py`或Mac的 `scripts/start_prelesson_console.command` 启动；界面和安全边界/实际截图见 `docs/prelesson-interactive-console-v01.md`。测试 `tests/test_prelesson_console.py`、`tests/test_prelesson_console_http.py`，无需数据库或外部模型。

- 三阶段本地演示：`src/integrations/three_stage_demo.py`只适配既有七要素/几何/V4/V5结构；`agents/postlesson_agent.py`以服务端注入身份只读查询数据库，输出mock、draft、unverified且不做技术错误或等级判定。入口未挂main；不执行教师批准或报告写回。`tests/teaching/test_three_stage_demo.py`仅在隔离数据库使用显式MOCK角色模拟教师/教练状态机，绝非真实人工审核。证据及线上阻塞见 `docs/coze-delivery-status-v01.md`；`scripts/prepare_three_stage_delivery.py`生成离线文件，不是Coze安装器或ZIP打包器。

- DEPLOY-FIX-01：`main.PRELESSON_ONLY` 在导入时固定，同时用于lifespan与访问白名单；profile=1跳过数据库、memory检查点、旧工作流与异步运行时初始化。启动器预检不再要求/解析数据库变量，普通模式初始化不变。真实启动器无DB、出站连接及初始化禁止探针、18项HTTP烟测和普通模式行为测试见 `tests/test_prelesson_db_free_startup.py`；当前部署要求见 `docs/coze-deploy-readiness-v01.md`。下述原启动链路描述以该更新为准。
- 显式 `COACHLOOP_PRELESSON_ONLY=1` 在main安装课前公开面白名单：仅GET健康检查和两个POST课前入口；其他路径/方法在处理器前404，旧流程仍在默认/0模式保留。配置值非法则启动失败。
- `src/integrations/prelesson/exposure.py` 不替代Bearer或教师身份认证；公网部署不能依赖未验证的Coze网关。平台控制面与系统依赖兼容性待Coze实测。
- `scripts/coze_prelesson_run.sh` 是可选受控启动器，先执行 `scripts/check_coze_deployment.py --preflight`，不满足条件退出；PR #6审查后 `.coze [deploy].run` 已强制使用该启动器；`[dev]` 保留原入口。配置变更不等于执行部署，平台实际命令仍待实测。
- 检查脚本使用标准库、只输出脱敏状态；HTTP检查拒绝重定向、验证认证与草稿保护，并用GET探测旧POST路径，不能启动旧工作流/异步任务或调用模型。待批准HTTPS地址确定后才可进行远程检查；本轮只做回环测试。
- 说明/GUI最少步骤见 `docs/coze-deploy-readiness-v01.md`；测试 `tests/test_deploy_readiness.py` 与现有隔离PG真实main测试联合运行。

- PR #6安全修复：生产入口不得绕过预检；检查器按已发布响应Schema核对必填结构与版本，契约文件必须打包。开发入口不对公网安全作保证，不允许为平台联调绕过认证或回退旧生产启动命令。
