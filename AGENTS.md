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

### 关键约定
- 候选技能编码：`jump, spin, spiral, footwork, step, camel`（占位，待专业确认）
- 候选评分范围：`[0, 10]`
- 非法输入不生成模拟反馈，仅返回 `errors` 与 `validation_result`
- 无知识库依据：`evidence_overall = "insufficient"`，`mock = true`