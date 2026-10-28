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

### 关键约定
- `skill_code`：仅校验为**非空字符串**，不做候选白名单硬拦截（候选编码占位仅供参考，待专业确认）
- `duration_min` / `stability_score`：接受**整数**或**可无歧义转整数的纯数字字符串**（如 "30"、"3"），在工作流入口标准化为 `int`；拒绝小数/`abc`/空串/布尔
- `stability_score` 为空时允许通过；不将候选评分范围或训练时长范围作为正式拦截条件
- 非法输入不生成模拟反馈，仅返回 `errors` 与 `validation_result`
- `errors` 为结构化列表，`code` 区分 `missing_field` / `invalid_type` / `empty`
- 无知识库依据：`evidence_overall = "insufficient"`，`mock = true`