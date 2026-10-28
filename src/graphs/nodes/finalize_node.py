from langgraph.runtime import Runtime
from langchain_core.runnables import RunnableConfig
from coze_coding_utils.runtime_ctx.context import Context
from graphs.state import FinalizeInput, FinalizeOutput


def finalize_node(state: FinalizeInput, config: RunnableConfig, runtime: Runtime[Context]) -> FinalizeOutput:
    """
    title: 结果汇总
    desc: 汇总运行状态、逐字段校验结果、模拟反馈与错误信息，作为工作流的最终输出。
    """
    ctx = runtime.context
    return FinalizeOutput(
        run_status=state.run_status,
        validation_result=state.validation_result,
        feedback=state.feedback,
        mock=state.mock,
        errors=state.errors,
    )