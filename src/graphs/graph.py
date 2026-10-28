from langgraph.graph import StateGraph, END
from graphs.state import (
    GlobalState,
    GraphInput,
    GraphOutput,
    ValidateStatusInput,
)
from graphs.nodes.validate_node import validate_node
from graphs.nodes.gen_feedback_node import gen_feedback_node
from graphs.nodes.finalize_node import finalize_node


def should_generate_feedback(state: ValidateStatusInput) -> str:
    """
    title: 是否生成模拟反馈
    desc: 根据校验状态决定分支走向：合法输入生成模拟反馈，非法输入直接收尾返回字段错误。
    """
    if state.run_status == "valid":
        return "生成模拟反馈"
    return "直接收尾"


# 主图：输入校验 -> 条件分支（合法生成模拟反馈 / 非法直接收尾） -> 结果汇总
builder = StateGraph(GlobalState, input_schema=GraphInput, output_schema=GraphOutput)

builder.add_node("validate_node", validate_node)
builder.add_node("gen_feedback_node", gen_feedback_node)
builder.add_node("finalize_node", finalize_node)

builder.set_entry_point("validate_node")

builder.add_conditional_edges(
    source="validate_node",
    path=should_generate_feedback,
    path_map={
        "生成模拟反馈": "gen_feedback_node",
        "直接收尾": "finalize_node",
    },
)

builder.add_edge("gen_feedback_node", "finalize_node")
builder.add_edge("finalize_node", END)

main_graph = builder.compile()