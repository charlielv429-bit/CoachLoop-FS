"""CoachLoop-FS 教案生成 Agent —— 阶段 A 基础数据结构。

独立模块，负责：
- 七要素教案 Pydantic 结构（缺项即校验失败）；
- 三段式课时强校验（准备/基本/结束，合计严格 == 45 分钟，且各段在允许范围）；
- 证据来源/数据状态标记（教师输入/知识库证据/真实分析数据/设计假设/未核实）；
- 未经教练审核的 V4 事件不得描述为"已确认技术错误"的保护。

本模块不依赖大模型、数据库、网页或插件；仅使用已有依赖。
"""
from enum import Enum
from typing import List, Optional, Literal

from pydantic import BaseModel, Field, ConfigDict, computed_field, model_serializer, model_validator


class EvidenceSource(str, Enum):
    """证据来源/数据状态标记。"""
    TEACHER_INPUT = "teacher_input"        # 教师输入
    KB_EVIDENCE = "kb_evidence"            # 已验证知识库证据
    REAL_ANALYSIS = "real_analysis"        # 真实分析数据（CoachLoop-FS 视频特征/事件）
    DESIGN_ASSUMPTION = "design_assumption"  # 设计假设
    UNVERIFIED = "unverified"              # 未核实（知识库未接入等）


class ReviewStatus(str, Enum):
    """教案审核状态（沿用事件审核语义，供人工复核）。"""
    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    NEEDS_REVISION = "needs_revision"


# V4 事件审核状态（仅教练显式写入 confirmed 才可视为已确认）
CONFIRMED_STATUS = "confirmed"
NON_CONFIRMED_EVENT_STATUSES = ("pending", "normal_movement", "tracking_error", "uncertain")


# ---------- 七要素：第 1 要素 指导思想 ----------
class GuidingIdeology(BaseModel):
    content: str = Field(..., min_length=1, description="指导思想内容")
    motor_competence: str = Field(..., min_length=1, description="运动能力维度可观察目标")
    healthy_behavior: str = Field(..., min_length=1, description="健康行为维度可观察目标")
    sports_ethics: str = Field(..., min_length=1, description="体育品德维度可观察目标")


# ---------- 七要素：第 2 要素 教材分析 ----------
class TeachingMaterialAnalysis(BaseModel):
    technical_composition: str = Field(..., min_length=1, description="技术构成")
    key_points: str = Field(..., min_length=1, description="教学重点")
    difficulties: str = Field(..., min_length=1, description="教学难点")
    progression: str = Field(..., min_length=1, description="与前后课程的联系")
    note_2d_limitation: str = Field(
        default="膝角/躯干倾角/髋踝偏移为二维视频可观测几何量，不等同于真实重心、冰刀用刃或经证实的专项技术错误。",
        description="二维测量的局限性说明（不得将探索性阈值当作合格标准）",
    )


# ---------- 七要素：第 3 要素 学情分析 ----------
class LearnerAnalysis(BaseModel):
    student_profile: str = Field(..., min_length=1, description="学生基础（学段/人数/水平）")
    common_difficulties: str = Field(default="", description="常见学习困难")
    tiered_plan: Optional[str] = Field(default=None, description="分层教学需求")
    note: str = Field(
        default="已确认事实/未经审核姿态事件/待核实推测需在教案中以证据来源明确区分。",
        description="数据区分说明",
    )


# ---------- 七要素：第 4 要素 场地器材布置 ----------
class VenueEquipment(BaseModel):
    organization_status: Literal["pending_confirmation"] = "pending_confirmation"
    proposed_group_sizes: List[int] = Field(default_factory=list)
    zones: str = Field(..., min_length=1, description="冰场区域划分")
    route: str = Field(default="", description="练习路线")
    observation_position: str = Field(default="", description="教师观察位置")
    grouping: str = Field(default="", description="分组安排")
    equipment_list: str = Field(default="", description="器材数量")
    camera_position: str = Field(default="", description="视频拍摄机位")


# ---------- 七要素：第 5 要素 安全防范与禁忌 ----------
class SafetyPrecautions(BaseModel):
    safety_review_status: Literal["unreviewed"] = "unreviewed"
    risk_screening: str = Field(..., min_length=1, description="课前风险筛查")
    ice_check: str = Field(..., min_length=1, description="冰面检查")
    equipment_check: str = Field(..., min_length=1, description="装备检查")
    staffing: str = Field(default="", description="教学人员职责")
    zone_management: str = Field(default="", description="练习区管理")
    emergency_flow: str = Field(..., min_length=1, description="紧急处置流程")
    medical_note: str = Field(
        default="涉及伤病/呼吸系统疾病/身体不适，仅提醒教师按学校既有制度核查，AI 不擅自诊断或处理医疗问题。",
        description="医疗边界声明",
    )


# ---------- 七要素：第 6 要素 教学流程（三段式） ----------
class TeachingPhase(str, Enum):
    PREP = "prep"        # 准备
    MAIN = "main"        # 基本
    CLOSING = "closing"  # 结束


# 各阶段允许的时间范围（分钟）
PHASE_RANGE_MINUTES = {
    TeachingPhase.PREP: (8, 10),
    TeachingPhase.MAIN: (28, 30),
    TeachingPhase.CLOSING: (5, 7),
}

PHASE_CN = {TeachingPhase.PREP: "准备", TeachingPhase.MAIN: "基本", TeachingPhase.CLOSING: "结束"}


class Phase(BaseModel):
    phase: TeachingPhase = Field(..., description="教学阶段")
    minutes: int = Field(..., gt=0, description="该阶段分钟数（正整数）")
    content: str = Field(..., min_length=1, description="教学内容")
    teacher_activity: str = Field(default="", description="教师活动")
    student_activity: str = Field(default="", description="学生活动")
    organization: str = Field(default="", description="组织方法")
    safety_tip: str = Field(default="", description="安全提示")
    evaluation: str = Field(default="", description="评价方式")


class GeneralTeachingFlow(BaseModel):
    """三段式课时结构：准备/基本/结束，合计严格等于 total_minutes。"""
    total_minutes: int = Field(default=45, gt=0, description="总课时（分钟）")
    phases: List[Phase] = Field(default=[], description="教学阶段列表（必须恰含准备/基本/结束三段）")

    @model_validator(mode="after")
    def _check_three_phases_and_time(self) -> "GeneralTeachingFlow":
        seen = set()
        total = 0
        for p in self.phases:
            if p.phase in seen:
                raise ValueError(f"阶段重复：{PHASE_CN[p.phase]}")
            seen.add(p.phase)
            total += p.minutes
        for ph in TeachingPhase:
            if ph not in seen:
                raise ValueError(f"缺少教学阶段：{PHASE_CN[ph]}")
        if len(seen) != 3:
            raise ValueError("教学流程必须恰含准备/基本/结束三个阶段")
        if total != self.total_minutes:
            raise ValueError(
                f"三段式时间合计须严格等于 {self.total_minutes} 分钟，实际合计 {total} 分钟"
            )
        return self


class TeachingFlow(GeneralTeachingFlow):
    """当前标准教案模式：严格45分钟；其他模式须显式使用通用模型另行定义。

    GeneralTeachingFlow 只负责通用三阶段完整性、正时长与合计约束，
    不可代替 LessonPlan 的标准模式校验。
    """
    @model_validator(mode="after")
    def _standard_45(self) -> "TeachingFlow":
        if self.total_minutes != 45:
            raise ValueError("当前45分钟标准教案模式要求总课时为45分钟")
        for p in self.phases:
            lo, hi = PHASE_RANGE_MINUTES[p.phase]
            if not (lo <= p.minutes <= hi):
                raise ValueError(
                    f"阶段 {PHASE_CN[p.phase]} 分钟数须在 [{lo}, {hi}]，实际 {p.minutes}"
                )
        return self


# ---------- 七要素：第 7 要素 负荷核算 结果模型 ----------
class MeasurementKind(str, Enum):
    ESTIMATED = "estimated"  # 预计值（待课堂实测验证）
    MEASURED = "measured"    # 实测值


class LoadMetric(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    name: str = Field(..., description="指标名")
    kind: MeasurementKind = Field(..., description="预计值或实测值")
    formula: str = Field(..., description="计算公式（含分子/分母/单位说明）")
    numerator: float = Field(..., ge=0, description="原始精度分子")
    denominator: float = Field(..., gt=0, description="原始精度分母")
    unit: str = Field(..., description="单位（如 % / 次/分）")
    result: float = Field(..., ge=0, description="原始精度计算结果")
    target: Optional[str] = Field(default=None, description="可选目标/依据说明")

    @computed_field
    @property
    def display_result(self) -> float:
        """仅展示时舍入，不能作为后续计算输入。"""
        return round(self.result, 2)


class LoadAccounting(BaseModel):
    avg_hr: LoadMetric = Field(..., description="预计平均心率（次/分）")
    group_density: LoadMetric = Field(..., description="群体运动密度（%）")
    individual_density: LoadMetric = Field(..., description="个体练习密度（%）")
    total_minutes: int = Field(..., description="总课时（分钟）")
    note: str = Field(
        default="无真实心率/有效练习时间实测时，以上均为预计值，待课堂实测验证。",
        description="口径说明",
    )


    @model_validator(mode="after")
    def _valid_load_inputs(self) -> "LoadAccounting":
        from .load_calc import validate_load_inputs
        validate_load_inputs(self.total_minutes, self.group_density.numerator,
                             self.individual_density.numerator, self.avg_hr.result)
        return self


# ---------- 证据与事件引用（来源/状态标记） ----------
class EventClaim(str, Enum):
    OBSERVATION = "observation"
    CONFIRMED_ERROR = "confirmed_error"


class EventRef(BaseModel):
    """引用某条 V4 事件（不得描述为已确认技术错误，除非教练确认）。"""
    event_id: str = Field(..., min_length=1, description="V4 事件 event_id")
    feature: str = Field(..., min_length=1, description="特征名（knee_angle_deg 等）")
    frame_start: int = Field(..., description="起始帧")
    frame_end: int = Field(..., description="结束帧")
    review_status: Literal["pending", "confirmed", "normal_movement", "tracking_error", "uncertain"] = Field(..., description="事件人工审核状态")
    deviation_max: float = Field(default=0.0, description="偏离幅度（若 V4 提供）")


class EvidenceEntry(BaseModel):
    statement: str = Field(..., min_length=1, description="教案内的陈述/依据")
    source: EvidenceSource = Field(..., description="来源/数据状态标记")
    citation: Optional[str] = Field(default=None, description="引用标注（文件·章节/页码）；未核实则必须为 None")
    event_ref: Optional[EventRef] = Field(default=None, description="若引用 V4 事件，须填写以触发状态保护")
    event_claim: EventClaim = EventClaim.OBSERVATION

    @model_validator(mode="after")
    def _unverified_has_no_citation(self) -> "EvidenceEntry":
        if self.source is EvidenceSource.UNVERIFIED and self.citation is not None:
            raise ValueError("unverified 证据不得携带 citation")
        return self

    @model_serializer(mode="wrap")
    def _guard_entry_output(self, handler):
        from .guard import validate_event_claims
        violations = validate_event_claims([self])
        if violations:
            raise ValueError("；".join(violations))
        return handler(self)


# ---------- 顶层：七要素教案 ----------
class TeacherInput(BaseModel):
    """教师提供的教学条件（非关键项可为空，但不虚构）。"""
    audience: str = Field(..., min_length=1, description="教学对象")
    theme: str = Field(..., min_length=1, description="教学主题/动作")
    conditions: str = Field(default="", description="教学条件（场地/器材/人员）")
    class_data_available: bool = Field(default=False, description="是否有经授权班级训练记录")


class LessonPlan(BaseModel):
    """七要素教案（缺项即校验失败）。"""
    title: str = Field(..., min_length=1, description="教案标题")
    teacher_input: TeacherInput = Field(..., description="教学条件输入")
    guiding_ideology: GuidingIdeology = Field(..., description="要素1：指导思想")
    teaching_material_analysis: TeachingMaterialAnalysis = Field(..., description="要素2：教材分析")
    learner_analysis: LearnerAnalysis = Field(..., description="要素3：学情分析")
    venue_equipment: VenueEquipment = Field(..., description="要素4：场地器材布置")
    safety_precautions: SafetyPrecautions = Field(..., description="要素5：安全防范与禁忌")
    teaching_flow: TeachingFlow = Field(..., description="要素6：教学流程")
    load_accounting: LoadAccounting = Field(..., description="要素7：运动负荷与密度核算")
    evidence_log: List[EvidenceEntry] = Field(default=[], description="证据来源/状态记录")
    review_status: ReviewStatus = Field(default=ReviewStatus.DRAFT, description="教案审核状态（人员审核）")
    plan_version: str = Field(default="1.0", description="教案版本")

    @model_validator(mode="after")
    def _standard_time_consistency(self) -> "LessonPlan":
        # 在顶层重复核对，防止嵌套模型被 model_copy/model_construct 绕过。
        if (self.teaching_flow.total_minutes != 45
                or sum(p.minutes for p in self.teaching_flow.phases) != 45):
            raise ValueError("当前45分钟标准教案模式要求三阶段合计为45分钟")
        if self.load_accounting.total_minutes != self.teaching_flow.total_minutes:
            raise ValueError("教学流程与负荷核算总课时必须一致")
        return self

    def check_event_output(self) -> None:
        from .guard import validate_event_claims
        violations = validate_event_claims(self.evidence_log)
        if violations:
            raise ValueError("；".join(violations))

    @model_validator(mode="after")
    def _event_claims_are_reviewed(self) -> "LessonPlan":
        self.check_event_output()
        return self

    @model_serializer(mode="wrap")
    def _guard_output(self, handler):
        # 覆盖 model_dump/model_dump_json，防止构造后追加违规事件绕过校验。
        self.check_event_output()
        return handler(self)
