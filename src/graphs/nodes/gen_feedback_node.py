from typing import Any, Dict
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from coze_coding_utils.runtime_ctx.context import Context
from graphs.state import FeedbackInput, FeedbackOutput


def gen_feedback_node(state: FeedbackInput, config: RunnableConfig, runtime: Runtime[Context]) -> FeedbackOutput:
    """
    title: 模拟反馈生成
    desc: 仅保留原始观察事实生成结构化模拟反馈，不推测动作原因、不生成具体训练建议；无知识库依据时 evidence_overall 固定为 insufficient。
    """
    ctx = runtime.context
    # 仅转录原始输入事实，不做任何专业推断
    feedback: Dict[str, Any] = {
        "student_id": str(state.student_id),
        "skill_code": str(state.skill_code),
        "duration_min": state.duration_min,
        "observation": str(state.observation),
        "stability_score": state.stability_score,
        "evidence_overall": "insufficient",
    }
    return FeedbackOutput(feedback=feedback, mock=True)