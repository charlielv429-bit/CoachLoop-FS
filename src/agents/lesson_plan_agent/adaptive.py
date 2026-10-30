"""Offline candidate curriculum engine. No verified pedagogy, approval or IO.

V1 API is deliberately unchanged. Reuses the existing seven-element models,
45-minute TeachingFlow, evidence guard and raw-precision LoadMetric calculator.
Capacity is a teacher declaration, NEVER an official safety threshold.
"""
import json
from pathlib import Path
from typing import Literal
from typing_extensions import TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator

from .generate_draft import _parse_staffing
from .schemas import (TeacherInput, GuidingIdeology, TeachingMaterialAnalysis, LearnerAnalysis,
                      VenueEquipment, SafetyPrecautions, TeachingFlow, EvidenceEntry, LoadMetric)

LEVELS = ('零基础', '初级', '初中级', '中级')
CATALOG = json.loads(Path(__file__).with_name('themes.v11.json').read_text(encoding='utf-8'))
THEMES = {t['theme_id']: t for t in CATALOG}
NOTICE = '候选教学设计，知识与安全依据未核实；待专项教练和教师现场复核，确认前不实施。'
FALL = '摔倒、起身及制动处置由专项教练结合现场与学校应急预案确定，本稿不提供统一处置指令。'
LEVEL_RULES = {
    '零基础': ('安全与基础控制', '扶助或短段体验后停顿', '观察指令响应与基础控制'),
    '初级': ('左右侧动作稳定性', '分侧重复后比较质量', '分别记录左右侧连续性'),
    '初中级': ('方向变化与技术衔接', '分段方向衔接后观察质量', '记录方向转换前后动作衔接'),
    '中级': ('专项精度与节奏组合', '单项质量复核后组合练习', '记录节奏与组合顺序保持情况'),
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class AdaptiveRequest(StrictModel):
    class_label: str = Field(default='匿名班级', min_length=1, max_length=80)
    theme_id: str = Field(default='two_foot_glide', min_length=1, max_length=40, json_schema_extra={'enum': list(THEMES)})
    student_count: int = Field(strict=True, ge=1, le=500)
    skill_level: Literal['零基础', '初级', '初中级', '中级']
    age_band: Literal['儿童', '青少年', '成人', '混合年龄'] = '青少年'
    mastered_skills: list[str] = Field(default_factory=list, max_length=24, json_schema_extra={'items': {'type': 'string', 'enum': list(THEMES)}, 'uniqueItems': True})
    coach_count: int = Field(strict=True, ge=0, le=50)
    teacher_count: int = Field(strict=True, ge=0, le=50)
    total_minutes: int = Field(default=45, strict=True, ge=45, le=45)
    usable_area_m2: float = Field(strict=True, gt=0, le=100000)
    # Physical capacity MUST be supplied, no invented m²/student or staff ratio.
    declared_practice_capacity: int = Field(strict=True, ge=1, le=500)
    equipment_sets: int = Field(strict=True, ge=0, le=500, description='齐备且可用的个人冰鞋护具套数')
    safe_waiting_area: bool = Field(strict=True)
    ice_available: bool = Field(strict=True, default=True)
    venue_conditions: str = Field(min_length=1, max_length=500)
    equipment_conditions: str = Field(min_length=1, max_length=500)
    goal_preference: Literal['基础控制', '动作质量', '左右均衡', '衔接节奏'] = '基础控制'
    teacher_goal_edit: str = Field(default='', max_length=500)
    teacher_notes: str = Field(default='', max_length=2000)
    teacher_exercise_edits: list[str] = Field(default_factory=list, max_length=3, json_schema_extra={'anyOf': [{'maxItems': 0}, {'minItems': 3, 'maxItems': 3}], 'items': {'type': 'string', 'maxLength': 500, 'pattern': r'^[^\x00-\x1f\x7f]*$'}})

    @field_validator('class_label', 'venue_conditions', 'equipment_conditions', 'teacher_goal_edit', 'teacher_notes')
    @classmethod
    def plain(cls, value):
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError('Only single-line text is accepted')
        if not value.strip() and value != '':
            raise ValueError('Blank text refused')
        return value.strip()

    @field_validator('teacher_exercise_edits')
    @classmethod
    def practice_edits(cls, values):
        if len(values) not in (0, 3) or any(not isinstance(v, str) or len(v)>500 or any(ord(c)<32 or ord(c)==127 for c in v) for v in values):
            raise ValueError('Provide zero or three single-line exercise edits')
        return [v.strip() for v in values]

    @model_validator(mode='after')
    def known_curriculum(self):
        if self.theme_id not in THEMES or any(s not in THEMES for s in self.mastered_skills):
            raise ValueError('Unknown theme/skill identifier')
        if len(set(self.mastered_skills)) != len(self.mastered_skills):
            raise ValueError('Duplicate prerequisite declaration')
        if not self.class_label or not self.venue_conditions or not self.equipment_conditions:
            raise ValueError('Required text must be nonempty')
        staff = _parse_staffing(self.venue_conditions + '；' + self.equipment_conditions)
        for role, count in [('教练', self.coach_count), ('教师', self.teacher_count)]:
            if staff[role] is not None and staff[role] != count:
                raise ValueError('Staffing text contradicts structured staffing')
        return self


class AdaptiveLoad(StrictModel):
    total_minutes: Literal[45] = 45
    kind: Literal['estimated'] = 'estimated'
    avg_hr: None = None
    group_density: LoadMetric
    individual_density: LoadMetric
    note: str

    @model_validator(mode='after')
    def check(self):
        for m in (self.group_density, self.individual_density):
            m.check_calculation()
            if m.kind != 'estimated' or m.unit != '%' or m.denominator != 45 or not 0 <= m.numerator <= 45:
                raise ValueError('Only estimated 45-minute activity accounting is allowed')
        return self


class AdaptivePlan(StrictModel):
    title: str
    teacher_input: TeacherInput
    guiding_ideology: GuidingIdeology
    teaching_material_analysis: TeachingMaterialAnalysis
    learner_analysis: LearnerAnalysis
    teaching_flow: TeachingFlow
    venue_equipment: VenueEquipment
    safety_precautions: SafetyPrecautions
    load_accounting: AdaptiveLoad
    evidence_log: list[EvidenceEntry]
    review_status: Literal['draft'] = 'draft'
    plan_version: Literal['1.1.0'] = '1.1.0'
    complete_plan: str


def _metric(name, active):
    return LoadMetric(name=name, kind='estimated', numerator=active, denominator=45,
                      unit='%', result=active / 45 * 100,
                      formula='预计活动分钟 / 45分钟 × 100；轮换均匀分配假设，非实测',
                      target=None).model_dump()


def _payload(req):
    t = THEMES[req.theme_id]
    missing = [s for s in t['prerequisites'] if s not in req.mastered_skills]
    reasons = []
    if req.skill_level not in t['supported_levels']: reasons.append('主题与学生水平不匹配')
    if missing: reasons.append('缺少先修技能：' + '、'.join(THEMES[s]['name_zh'] for s in missing))
    if not req.coach_count: reasons.append('无专项教练，暂缓冰上练习；体育教师不自动替代教练')
    if req.equipment_sets < req.student_count: reasons.append('齐备个人装备不足，不通过共用冰鞋护具降低核验要求')
    if not req.safe_waiting_area: reasons.append('等待区安全条件未确认')
    if not req.ice_available: reasons.append('冰面不可使用')
    if req.teacher_count == 0 and req.student_count > req.declared_practice_capacity:
        reasons.append('存在轮换等待学生但无明确等待区负责人员，暂缓冰上实施')
    blocked = bool(reasons)
    slots = min(req.student_count, req.declared_practice_capacity)
    lanes = min(req.coach_count, slots)
    # One supervised wave at a time; each lane gets one actual coach.
    wave_sizes = [min(slots, req.student_count - i) for i in range(0, req.student_count, slots)] if not blocked else []
    groups = []
    for wave, count in enumerate(wave_sizes, 1):
        wave_lanes = min(lanes, count)
        q, r = divmod(count, wave_lanes)
        groups.extend({'wave': wave, 'coach': j + 1, 'students': q + (j < r)} for j in range(wave_lanes))
    waves = len(wave_sizes)
    # 29 main minutes: 5 demonstration, 24 rotation. Each wave 1 minute
    # transition assumption; remaining time is shared evenly. No repetitions quota.
    active_window = max(0, 24 - waves) if not blocked else 0
    if waves and active_window == 0:
        reasons.append('轮换过多，45分钟内无有效核心练习窗口；缩小班级或增加可用区域后重拟')
        blocked = True; groups = []; wave_sizes = []; waves = 0
    core_per_student = active_window / waves if waves else 0.0
    # 4 prep + 3 closing gentle activity minutes are design assumptions.
    group_active = 7 + active_window if not blocked else 0
    individual_active = 7 + core_per_student if not blocked else 0
    rule = LEVEL_RULES[req.skill_level]
    goal = t['goals'] + [rule[0], '目标偏好：' + req.goal_preference]
    if req.teacher_goal_edit: goal += ['教师修改候选目标（未审核）：' + req.teacher_goal_edit]
    exercises = ([{'order': i + 1, 'task': ('教师修改候选练习（未审核）：' + req.teacher_exercise_edits[i]) if req.teacher_exercise_edits and req.teacher_exercise_edits[i] else p,
                   'catalogue_task': p, 'active_min_per_student': core_per_student / 3,
                   'mode': rule[1] + '；侧重' + req.goal_preference, 'status': 'candidate_unverified'}
                  for i, p in enumerate(t['practice_progression'])] if not blocked else [])
    evaluations = (t['evaluation_indicators'] + [rule[2], '按偏好形成性观察：' + req.goal_preference]
                   if not blocked else ['仅核对先修条件与资源，不评价冰上技术完成情况'])
    duties = []
    if not blocked:
        for i in range(lanes):
            duties.append({'role': 'coach', 'number': i + 1, 'task': rule[0] + '；指导本组、观察' + t['key_points'] + '并记录形成性反馈；保护方式待专业核定'})
        for i in range(lanes, req.coach_count):
            duties.append({'role': 'coach', 'number': i + 1, 'task': '机动观察与反馈；现场分工待确认'})
        for i in range(req.teacher_count):
            duties.append({'role': 'teacher', 'number': i + 1, 'task': '等待区秩序、轮换交接及异常报告；不替代专项教练'})
    limits = reasons + t['safety_requirements'] + [NOTICE, FALL]
    if req.teacher_count == 0:
        limits.append('无体育教师：未轮到练习者由现场方案安排在冰外等待，教练不得同时承担冲突岗位；等待区负责人未核定前不实施')
    if not blocked and waves > 1:
        limits.append(f'需{waves}轮且每位学生核心活动仅预计{core_per_student:.2f}分钟；缩小班级/增加区域须先现场确认，不以增加次数补偿')
    if req.age_band in ('儿童', '混合年龄'):
        limits.append('儿童或混龄：装备适配、沟通能力与监护交接待现场确认；不采用成人标准推定适用')
    organization = {'status': 'withheld' if blocked else 'pending_confirmation',
        'capacity_source': 'teacher_declared_unverified', 'declared_capacity': req.declared_practice_capacity,
        'usable_area_m2': req.usable_area_m2, 'concurrent_students': 0 if blocked else slots,
        'wave_sizes': wave_sizes, 'groups': groups, 'rotation_count': waves,
        'main_demo_min': 5, 'main_rotation_min': 24, 'transition_min_per_wave': 1,
        'core_active_min_per_student': core_per_student,
        'group_diagram': ' → '.join(f'轮{w}：' + ' / '.join(f'教练{g["coach"]}组{g["students"]}人' for g in groups if g['wave']==w) for w in range(1,waves+1)),
        'waiting_students_max': 0 if blocked else max(0, req.student_count - slots),
        'note': '面积仅记录，不推算安全容量。容量由教师填报待现场确认；人数拆分不证明安全师生比。冰外等候非练习。'}
    orgtext = ('暂缓实施；' + '；'.join(reasons)) if blocked else (
        f'拟定{waves}轮，现场填报同时练习容量{slots}人；' + organization['group_diagram'] +
        f'。人均核心活动约{core_per_student:.2f}分钟；等待者在冰外等待区。容量、人员分工与路线须现场确认。')
    dutytext = '；'.join(('教练' if d['role']=='coach' else '体育教师') + str(d['number']) + '：' + d['task'] for d in duties) or '暂缓安排，核对人员及先修条件'
    practice_text = '；'.join(x['task'] + '（' + x['mode'] + '）' for x in exercises) if exercises else '暂缓所有冰上实施：仅进行条件核对与陆地口头讨论，不提供实操动作'
    stage_contents = ['点名、装备与场地条件核查；口头确认先修能力；陆地准备活动待现场许可',
                      ('示范5分钟；轮换24分钟（包含每轮转换1分钟的设计假设）；' + practice_text) if not blocked else practice_text, '整理与自评；记录观察；教师审核交接，不自动批准']
    phases = [dict(phase=phase, minutes=minutes, content=stage_contents[i],
                   teacher_activity='按真实人员分工：' + dutytext if not blocked else '核对暂缓原因，不组织冰上实施',
                   student_activity=stage_contents[i], organization=orgtext,
                   safety_tip='；'.join(limits), evaluation='；'.join(evaluations))
              for i, (phase, minutes) in enumerate([('prep', 9), ('main', 29), ('closing', 7)])]
    plan = dict(title=f'花样滑冰·{t["name_zh"]}（45分钟·教师审核稿）',
        teacher_input=dict(audience=f'{req.class_label}·{req.student_count}人·{req.skill_level}·{req.age_band}',theme=t['name_zh'],
                           conditions=f'教练{req.coach_count}名；体育教师{req.teacher_count}名；{req.venue_conditions}；{req.equipment_conditions}',class_data_available=False),
        guiding_ideology=dict(content=NOTICE, motor_competence='；'.join(goal), healthy_behavior='装备检查与异常报告；' + FALL, sports_ethics='尊重同伴、遵守轮换与等待区约定'),
        teaching_material_analysis=dict(technical_composition='；'.join(t['practice_progression'])+'（候选内容，待专业核实）',key_points=t['key_points'],difficulties=t['difficulties'],progression='先修：'+'、'.join(THEMES[s]['name_zh'] for s in t['prerequisites'])+'；'+rule[0]),
        learner_analysis=dict(student_profile=f'{req.student_count}人，{req.skill_level}，{req.age_band}',common_difficulties='；'.join(t['candidate_errors']),tiered_plan='降阶：先修核对；本级：'+rule[1]+'；进阶：仅在专业教练许可后衔接，未经许可不提高难度',note='先修掌握情况来自教师自报，未认证；' + NOTICE),
        teaching_flow=dict(total_minutes=45,phases=phases),
        venue_equipment=dict(zones=f'可用{req.usable_area_m2}平方米；练习区、冰外等待区与缓冲区均待现场核定',route=t['name_zh']+'候选练习路线待现场核定',observation_position=dutytext,grouping=orgtext,proposed_group_sizes=[g['students'] for g in groups],equipment_list=f'齐备个人装备{req.equipment_sets}套；'+req.equipment_conditions,camera_position='不要求录像，不引入真实视频或身份'),
        safety_precautions=dict(risk_screening='现场人员按学校制度核查，AI不进行医疗判断',ice_check=req.venue_conditions+'；现场检查待确认',equipment_check=req.equipment_conditions+'；装备适配待确认',staffing=f'实际教练{req.coach_count}名，体育教师{req.teacher_count}名；'+dutytext,zone_management='；'.join(limits),emergency_flow=FALL,medical_note='身体不适按学校应急预案处理；'+FALL),
        load_accounting=dict(total_minutes=45,kind='estimated',avg_hr=None,
                             group_density=_metric('预计群体活动窗口密度（至少有一组活动，非全体同时活动）',group_active),
                             individual_density=_metric('预计人均活动密度',individual_active),
                             note=f'非实测：准备4分钟+结束3分钟活动假设；基本29分钟=示范5分钟+轮换24分钟，每轮转换1分钟；核心有效窗口{active_window}分钟，平均分配{waves}轮。暂缓时活动量计0。心率未估计，不能据此判断实际生理负荷。'),
        evidence_log=[dict(statement=NOTICE,source='unverified',citation=None),dict(statement='轮换时间与分组是工程设计假设，不是法定师生比或专业安全阈值',source='design_assumption'),dict(statement='班级、资源和先修情况为教师输入，尚未经独立认证',source='teacher_input')],
        review_status='draft',plan_version='1.1.0',complete_plan='；'.join(goal)+'。准备9分钟—基本29分钟—结束7分钟。'+practice_text+'。'+NOTICE)
    plan['complete_plan'] = '\n'.join([
        plan['title'], '草稿 draft；教师与专项教练审核前不实施；知识依据 unverified。',
        '指导思想：' + NOTICE + '；' + '；'.join(goal),
        '教材分析：' + t['key_points'] + '；难点：' + t['difficulties'],
        '学情分析：' + plan['teacher_input']['audience'] + '；先修缺项：' + '、'.join(missing),
        *[f'{p["phase"]} {p["minutes"]}分钟：{p["content"]}' for p in phases],
        '场地器材：' + plan['venue_equipment']['zones'] + '；' + orgtext + '；' + plan['venue_equipment']['equipment_list'],
        '人员分工：' + dutytext, '安全限制：' + '；'.join(limits),
        f'预计群体活动窗口：{group_active}分钟/45分钟；预计人均活动：{individual_active}分钟/45分钟；心率未估计、非实测。',
        plan['load_accounting']['note'], '形成性评价：' + '；'.join(evaluations),
        '教师修改备注（未审核）：' + req.teacher_notes,
    ])
    # Shared model validation (including event/evidence guards) remains mandatory.
    validated = AdaptivePlan.model_validate(plan).model_dump()
    return dict(schema_version='adaptive-prelesson-v1.1',status='needs_confirmation' if blocked else 'draft_ready',
        requires_teacher_review=True,knowledge_status='unverified',review_status='draft',
        request=req.model_dump(),lesson_plan=validated,
        adaptation=dict(theme_id=t['theme_id'],theme_version=t['version'],source=t['source'],verification_status='unverified',
            prerequisites_missing=missing,goals=goal,core_exercises=exercises,organization=organization,
            staff_tasks=duties,evaluation_indicators=evaluations,safety_limits=limits,
            differentiation=['支持：'+rule[1], '巩固：按观察反馈重复当前任务', '进阶：经专项教练许可后衔接'],
            teacher_goal_edit=req.teacher_goal_edit,teacher_notes=req.teacher_notes,
            teacher_review_checklist=['核实先修技能与水平','核定现场容量、等待区和实际人员职责','复核本主题动作与安全要求','确认分组时间与预计负荷假设','核实知识来源；本稿仍为unverified','人工审核在本应用外完成，本应用不批准']))


class SourceData(TypedDict):
    kind: Literal['editorial_candidate']
    reference: None
    note: str


class PracticeData(TypedDict):
    order: int
    task: str
    catalogue_task: str
    active_min_per_student: float
    mode: str
    status: Literal['candidate_unverified']


class GroupData(TypedDict):
    wave: int
    coach: int
    students: int


class DutyData(TypedDict):
    role: Literal['coach', 'teacher']
    number: int
    task: str


class OrganizationData(TypedDict):
    status: Literal['withheld', 'pending_confirmation']
    capacity_source: Literal['teacher_declared_unverified']
    declared_capacity: int
    usable_area_m2: float
    concurrent_students: int
    wave_sizes: list[int]
    groups: list[GroupData]
    rotation_count: int
    main_demo_min: int
    main_rotation_min: int
    transition_min_per_wave: int
    core_active_min_per_student: float
    group_diagram: str
    waiting_students_max: int
    note: str


class AdaptationData(TypedDict):
    theme_id: str
    theme_version: str
    source: SourceData
    verification_status: Literal['unverified']
    prerequisites_missing: list[str]
    goals: list[str]
    core_exercises: list[PracticeData]
    organization: OrganizationData
    staff_tasks: list[DutyData]
    evaluation_indicators: list[str]
    safety_limits: list[str]
    differentiation: list[str]
    teacher_goal_edit: str
    teacher_notes: str
    teacher_review_checklist: list[str]


class AdaptiveResponse(StrictModel):
    schema_version: Literal['adaptive-prelesson-v1.1']
    status: Literal['draft_ready', 'needs_confirmation']
    requires_teacher_review: Literal[True]
    knowledge_status: Literal['unverified']
    review_status: Literal['draft']
    request: AdaptiveRequest
    lesson_plan: AdaptivePlan
    adaptation: AdaptationData

    @model_serializer(mode='wrap')
    def guard_export(self, handler):
        # Inspect raw fields BEFORE Pydantic's serializer can normalize bools
        # into numeric fields. Validate teacher edits and recompute the plan.
        request = AdaptiveRequest.model_validate(_raw(self.request))
        expected = AdaptiveResponse.model_validate(_payload(request))
        if (self.requires_teacher_review is not True
                or json.dumps(_raw(self), sort_keys=True, allow_nan=False)
                != json.dumps(_raw(expected), sort_keys=True, allow_nan=False)):
            raise ValueError('Adaptive draft was changed outside validated teacher inputs')
        return handler(self)


def _raw(value):
    if isinstance(value, BaseModel):
        return {k: _raw(getattr(value, k)) for k in type(value).model_fields}
    if isinstance(value, dict):
        return {k: _raw(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_raw(v) for v in value]
    return value


def generate_adaptive(payload: dict) -> AdaptiveResponse:
    req = AdaptiveRequest.model_validate(payload)
    return AdaptiveResponse.model_validate(_payload(req))


def catalogue():
    # Caller receives an isolated copy; it cannot mutate the engine registry.
    return json.loads(json.dumps(CATALOG, ensure_ascii=False))
