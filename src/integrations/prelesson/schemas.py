"""Teacher-facing contract; all generation and numeric rules stay in the Agent."""
from typing import Literal
from decimal import Decimal
import math

from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator,model_serializer

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
    estimated_group_active_min: float=Field(default=36,strict=True,ge=0,le=45,description='预计设计值，非实测；缺省36分钟',json_schema_extra={'x-check-bounds-before-float-conversion':True,'x-reject-nonzero-float-underflow':True})
    estimated_individual_active_min: float=Field(default=25,strict=True,ge=0,le=45,description='预计设计值，非实测；缺省25分钟',json_schema_extra={'x-check-bounds-before-float-conversion':True,'x-reject-nonzero-float-underflow':True})
    estimated_avg_hr: float=Field(default=145,strict=True,ge=20,le=250,description='预计输入，非医学目标；缺省145次/分',json_schema_extra={'x-check-bounds-before-float-conversion':True,'x-reject-nonzero-float-underflow':True})

    @field_validator('class_label','venue_conditions','equipment_conditions')
    @classmethod
    def plain_text(cls,value):
        if not value.strip() or any(ord(c)<32 or ord(c)==127 for c in value):
            raise ValueError('须为非空且无控制字符的单行文本')
        return value.strip()

    @field_validator('estimated_group_active_min','estimated_individual_active_min','estimated_avg_hr',mode='before')
    @classmethod
    def exact_numeric_bounds(cls,value,info):
        # ExactJSONRoute preserves JSON decimal tokens. Check their domain
        # BEFORE the existing float-based load calculator can round/clamp them.
        if isinstance(value,bool) or not isinstance(value,(int,float,Decimal)):
            raise ValueError('预计负荷须为JSON数值')
        exact=value if isinstance(value,Decimal) else Decimal(str(value))
        lo,hi=(20,250) if info.field_name=='estimated_avg_hr' else (0,45)
        if not exact.is_finite() or not Decimal(lo)<=exact<=Decimal(hi):
            raise ValueError('预计负荷超出原始数值有效域')
        converted=float(exact)
        if not math.isfinite(converted) or (exact!=0 and converted==0):
            raise ValueError('预计负荷不能在浮点转换中下溢为零')
        return converted

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
        controls={'schema_version':'prelesson-draft-v1','status':'draft_ready',
                  'knowledge_status':'unverified','load_basis':'estimated_design_assumptions'}
        if self.requires_teacher_review is not True or any(getattr(self,k)!=v for k,v in controls.items()):
            raise ValueError('课前输出须保持草稿、待教师审核、未核实知识与预计负荷状态')
        plan=self.lesson_plan
        plan.check_event_output()
        plan._standard_time_consistency()
        if plan.review_status!=ReviewStatus.DRAFT:
            raise ValueError('教案须保持draft，等待教师审核')
        if not any(e.source==EvidenceSource.UNVERIFIED for e in plan.evidence_log):
            raise ValueError('须保留知识依据未核实标记')
        if any(e.source in (EvidenceSource.KB_EVIDENCE,EvidenceSource.REAL_ANALYSIS) for e in plan.evidence_log):
            raise ValueError('此入口不认证知识依据或导入视频结论')
        if (plan.safety_precautions.safety_review_status!='unreviewed'
                or plan.venue_equipment.organization_status!='pending_confirmation'):
            raise ValueError('安全和组织方案须保持待确认状态')
        load=plan.load_accounting
        if any(metric.kind!='estimated' for metric in (load.avg_hr,load.group_density,load.individual_density)):
            raise ValueError('此入口负荷只能标为预计值')
        # Revalidate nested field/phase constraints too; validating an existing
        # Pydantic instance alone does not rerun all nested field validators.
        DraftPlan.model_validate(plan.model_dump())
        return self

    @model_serializer(mode='wrap')
    def guarded_output(self,handler):
        # model_copy/assignment do not rerun Literal field validation. Recheck
        # the handoff contract before every export, even of an existing instance.
        self.no_claimed_approval_or_evidence()
        return handler(self)


class ErrorDetail(BaseModel):
    loc: list[str | int]
    type: str
    msg: str


class ErrorResponse(BaseModel):
    detail: str | list[ErrorDetail]
