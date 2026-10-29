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

### 教案生成 Agent（阶段A 基础模块 + 任务1 草稿生成器）
- 目录 `src/agents/lesson_plan_agent/`，纯确定性逻辑，仅需主 `.venv`，不接大模型/知识库/数据库
  - `schemas.py`：七要素 Pydantic 结构；`TeachingFlow` 校验三段式（PREP 8-10 / MAIN 28-30 / CLOSING 5-7）合计严格 == 45
  - `load_calc.py`：`calc_load(total, group_min, indiv_min, avg_hr, kind)` → 群体/个体密度 + 平均心率，含公式/分子分母/单位/结果；区分预计(ESTIMATED)与实测(MEASURED)
  - `guard.py`：`canvas` 未接知识库→`unverified_kb()`；确认前缀保护 `validate_event_claims()`（禁止把未审核事件写成已确认技术错误）
  - `generate_draft.py`（任务1，新增）：`build_draft()` 由输入生成七要素 45 分钟教案草稿，`draft_to_json()` 可序列化 JSON；CLI：`PYTHONPATH=src .venv/bin/python -m agents.lesson_plan_agent.generate_draft --theme "..." --student-count 20 ... --output /tmp/lesson_draft.json`
    - 任务1.1 跨字段一致性：`_parse_staffing()/_build_staffing()` 从输入解析教练/教师人数（不自行增设）；`_build_grouping_and_tiers()` 明确能力分层3级↔轮换组4组对应；负荷词典注明"设计目标、尚未由课堂安排实测验证"；安全措辞去掉绝对化处置、技术要领待专项教练确认；主/结束段评价为可观察三层级过程性目标（非官方合格线）
    - 任务2A 最小知识库接入：`kb_adapter.py` 封装一次真实检索，**仅**接受带【原文出处】标记、非图像块、score≥0.5 的可核验命中（KBHit：query/content/source_file/page/score）；图像块、无标记、SDK异常一律返回空（不虚构引用）。`build_draft(..., kb_evidence=[...])` 仅对可核验命中新增 `EvidenceSource.KB_EVIDENCE`（含 citation 文件|原PDF第N页）；无可核验命中→维持 `unverified`。CLI 加 `--kb`。真实 E2E：`curriculum_2022` 已导入已核验前言 p1-6（doc 7701926456758370330）；Q1 命中 原PDF第6页(核心素养内涵章节目录)，Q2/Q3 仅图像块/无标记文本→无核验命中、降级 unverified
- 测试：`tests/test_lesson_plan_agent.py` + `tests/test_generate_draft.py` + `tests/test_generate_draft_consistency.py` + `tests/test_kb_adapter.py`（合计 88 项通过；V2—V5.2 等原有测试无回归）
- 界定：来源严格区分 teacher_input / unverified(不虚构引用) / design_assumption；技术建议待专业教练确认、不设角度阈值；未审核事件不得描述为已确认错误
- `errors` 为结构化列表，`code` 区分 `missing_field` / `invalid_type` / `empty`
- 无知识库依据：`evidence_overall = "insufficient"`，`mock = true`