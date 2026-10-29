"""Independent Coze-style StateGraph; graphs.graph.main_graph stays unchanged."""
from pydantic import BaseModel
from langgraph.graph import StateGraph,END

from agents.lesson_plan_agent.generate_draft import build_draft,draft_to_json
from integrations.prelesson.schemas import DraftRequest,DraftPlan,DraftResponse


class GenerationOutput(BaseModel):
    lesson_plan: DraftPlan


class PrelessonState(DraftRequest):
    lesson_plan: DraftPlan | None=None
    schema_version: str='prelesson-draft-v1'
    status: str='draft_ready'
    requires_teacher_review: bool=True
    knowledge_status: str='unverified'
    load_basis: str='estimated_design_assumptions'


def generate_lesson(state: DraftRequest) -> GenerationOutput:
    """title: 生成七要素草稿; desc: 复用45分钟模板，不检索、不批准、不写数据库。"""
    plan=build_draft(state.agent_input(),kb_evidence=None)
    # Existing serializer enforces event, citation, arithmetic and time guards.
    return GenerationOutput(lesson_plan=DraftPlan.model_validate_json(draft_to_json(plan)))


def teacher_review_gate(state: GenerationOutput) -> DraftResponse:
    """title: 教师审核交接; desc: 仅返回draft，审核须由后续真实教师流程完成。"""
    plan=DraftPlan.model_validate_json(draft_to_json(state.lesson_plan))
    return DraftResponse(lesson_plan=plan)


builder=StateGraph(PrelessonState,input_schema=DraftRequest,output_schema=DraftResponse)
builder.add_node('generate_prelesson_draft',generate_lesson)
builder.add_node('await_teacher_review',teacher_review_gate)
builder.set_entry_point('generate_prelesson_draft')
builder.add_edge('generate_prelesson_draft','await_teacher_review')
builder.add_edge('await_teacher_review',END)
prelesson_graph=builder.compile()


def run_prelesson(payload: dict) -> DraftResponse:
    """Public Python/CLI/HTTP boundary; reject extra and forged control fields."""
    request=DraftRequest.model_validate(payload)
    result=prelesson_graph.invoke(request.model_dump())
    response=DraftResponse.model_validate(result)
    # Revalidate the exact guarded output, rather than trusting graph channels.
    return DraftResponse.model_validate_json(response.model_dump_json())
