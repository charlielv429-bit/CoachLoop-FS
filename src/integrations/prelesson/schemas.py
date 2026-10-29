"""Teacher-facing contract; all generation and numeric rules stay in the Agent."""
from typing import Literal

from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator

from agents.lesson_plan_agent.generate_draft import LessonPlanDraftInput
from agents.lesson_plan_agent.schemas import LessonPlan,ReviewStatus,EvidenceSource

THEME='冰上双足滑行与身体姿态控制'


class DraftRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    class_label: str=Field(default='匿名班级',min_length=1,max_length=80,description='班级匿名标签；不填学生姓名或健康信息')
    student_count: int=Field(strict=True,gt=0,le=500)
    theme: Literal['冰上双足滑行与身体姿态控制']
    skill_level: Literal['零基础']
    total_minutes: int=Field(strict=True,ge=45,le=45,description='当前模板仅45分钟')
    coach_count: int | None=Field(default=None,strict=True,ge=0,le=50,description='未知留空，不虚构人数')
    teacher_count: int | None=Field(default=None,strict=True,ge=0,le=50)
    venue_conditions: str=Field(min_length=1,max_length=500)
    equipment_conditions: str=Field(min_length=1,max_length=500)
    estimated_group_active_min: float=Field(default=36,strict=True,ge=0,le=45,description='预计设计值，非实测；缺省36分钟')
    estimated_individual_active_min: float=Field(default=25,strict=True,ge=0,le=45,description='预计设计值，非实测；缺省25分钟')
    estimated_avg_hr: float=Field(default=145,strict=True,ge=20,le=250,description='预计输入，非医学目标；缺省145次/分')

    @field_validator('class_label','venue_conditions','equipment_conditions')
    @classmethod
    def plain_text(cls,value):
        if not value.strip() or any(ord(c)<32 or ord(c)==127 for c in value):
            raise ValueError('须为非空且无控制字符的单行文本')
        return value.strip()

    def agent_input(self):
        staff=[]
        if self.coach_count is not None:staff.append(f'教练{self.coach_count}名')
        if self.teacher_count is not None:staff.append(f'教师{self.teacher_count}名')
        return LessonPlanDraftInput(audience=self.class_label,student_count=self.student_count,
            theme=self.theme,skill_level='初学者',total_minutes=self.total_minutes,
            conditions='；'.join([*staff,'场地：'+self.venue_conditions,'器材：'+self.equipment_conditions]),
            group_active_min=self.estimated_group_active_min,
            individual_active_min=self.estimated_individual_active_min,avg_hr=self.estimated_avg_hr,
            class_data_available=False)

    @model_validator(mode='after')
    def reusable_validation(self):
        self.agent_input()  # Also reject contradictory staffing embedded in text.
        return self


class DraftPlan(LessonPlan):
    review_status: Literal[ReviewStatus.DRAFT]=ReviewStatus.DRAFT


class DraftResponse(BaseModel):
    model_config=ConfigDict(extra='forbid')
    schema_version: Literal['prelesson-draft-v1']='prelesson-draft-v1'
    status: Literal['draft_ready']='draft_ready'
    requires_teacher_review: Literal[True]=True
    knowledge_status: Literal['unverified']='unverified'
    load_basis: Literal['estimated_design_assumptions']='estimated_design_assumptions'
    lesson_plan: DraftPlan

    @model_validator(mode='after')
    def no_claimed_approval_or_evidence(self):
        plan=self.lesson_plan
        plan.check_event_output()
        plan._standard_time_consistency()
        if plan.review_status!=ReviewStatus.DRAFT:
            raise ValueError('教案须保持draft，等待教师审核')
        if not any(e.source==EvidenceSource.UNVERIFIED for e in plan.evidence_log):
            raise ValueError('须保留知识依据未核实标记')
        if any(e.source in (EvidenceSource.KB_EVIDENCE,EvidenceSource.REAL_ANALYSIS) for e in plan.evidence_log):
            raise ValueError('此入口不认证知识依据或导入视频结论')
        return self
