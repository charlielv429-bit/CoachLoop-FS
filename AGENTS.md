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
- **后续接入 MediaPipe 最小步骤**（待批准后执行，现未安装）：
  1. 安装 `mediapipe`（需解决与现有 `opencv-python` 的共存/版本策略）
  2. 用 `cv2.VideoCapture`/ffmpeg 抽帧
  3. 每帧运行 `mp_pose.Pose()` 得到 33 点，序列化为本模块 `Landmark`/`KeypointFrame` 结构
  4. 复用本模块 `extract_features` 计算特征；此时 `model` 标注为 `mediapipe_pose`、`is_mock=false`

### 关键约定
- `skill_code`：仅校验为**非空字符串**，不做候选白名单硬拦截（候选编码占位仅供参考，待专业确认）
- `duration_min` / `stability_score`：接受**整数**或**可无歧义转整数的纯数字字符串**（如 "30"、"3"），在工作流入口标准化为 `int`；拒绝小数/`abc`/空串/布尔
- `stability_score` 为空时允许通过；不将候选评分范围或训练时长范围作为正式拦截条件
- 非法输入不生成模拟反馈，仅返回 `errors` 与 `validation_result`
- `errors` 为结构化列表，`code` 区分 `missing_field` / `invalid_type` / `empty`
- 无知识库依据：`evidence_overall = "insufficient"`，`mock = true`