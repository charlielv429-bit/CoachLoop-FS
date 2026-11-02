"""Lesson-ID planning, without mapping lesson IDs to legacy candidate themes.

Only organization is deterministic. Registry registration is never trusted review.
Plans are bounded process-local snapshots; edits are append-only and unapproved.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
import hashlib
import hmac
import re
import secrets
from threading import RLock
from typing import Literal
from uuid import uuid4

from pydantic import Field, field_validator, model_validator
from agents.lesson_plan_agent.adaptive import AdaptiveRequest, AdaptiveLoad, organization_inputs, validate_classroom_conditions, _metric
from agents.lesson_plan_agent.schemas import TeachingFlow
from .registry import Strict, Knowledge, RegistryError


PLAN_COOKIE = 'coachloop_lesson_plans'


class PlanSessions:
    """Process-signed browser cookie, not a teacher identity or authorization role."""
    def __init__(self):
        self._key = secrets.token_bytes(32)

    def owner(self, cookie):
        if not isinstance(cookie, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}\.[a-f0-9]{64}', cookie):
            return None
        token, signature = cookie.split('.')
        expected = hmac.new(self._key, token.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        return hashlib.sha256(token.encode()).hexdigest()

    def issue(self, cookie):
        if self.owner(cookie):
            return cookie
        token = secrets.token_urlsafe(32)
        return token + '.' + hmac.new(self._key, token.encode(), hashlib.sha256).hexdigest()


class Conditions(Strict):
    class_label: str = Field(default='匿名班级', min_length=1, max_length=80)
    student_count: int = Field(ge=1, le=500)
    skill_level: Literal['零基础', '初级', '初中级', '中级']
    age_band: Literal['儿童', '青少年', '成人', '混合年龄'] = '青少年'
    coach_count: int = Field(ge=0, le=50)
    teacher_count: int = Field(ge=0, le=50)
    usable_area_m2: float = Field(gt=0, le=100000, allow_inf_nan=False)
    declared_practice_capacity: int = Field(ge=1, le=500)
    equipment_sets: int = Field(ge=0, le=500)
    safe_waiting_area: bool
    ice_available: bool = True
    venue_conditions: str = Field(min_length=1, max_length=500)
    equipment_conditions: str = Field(min_length=1, max_length=500)

    @field_validator('class_label', 'venue_conditions', 'equipment_conditions')
    @classmethod
    def plain(cls, value):
        return AdaptiveRequest.plain(Knowledge.safe_text(value))

    @model_validator(mode='after')
    def existing_condition_rules(self):
        return validate_classroom_conditions(self)


class TeacherEdits(Strict):
    goal_draft: str = Field(default='', max_length=500)
    organization_note: str = Field(default='', max_length=1000)
    resource_note: str = Field(default='', max_length=1000)

    @field_validator('goal_draft', 'organization_note', 'resource_note')
    @classmethod
    def plain(cls, value):
        return Knowledge.safe_text(value)


class LessonRequest(Strict):
    lesson_id: str = Field(pattern=r'^L0[1-8]$')
    conditions: Conditions
    prerequisites_confirmed: bool = False
    edits: TeacherEdits = Field(default_factory=TeacherEdits)


class EditRequest(TeacherEdits):
    plan_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    expected_version: int = Field(ge=1, le=100)


def build_framework(request, registry):
    request = LessonRequest.model_validate(request.model_dump())
    lesson = registry.lessons(request.lesson_id)[0]
    missing = list(lesson['missing_materials']) + ['专项先修要求、适用学生水平与审核记录待补充']
    reasons = [] if request.prerequisites_confirmed else ['先修条件未确认，暂缓冰上组织安排；不以旧主题先修ID替代课次先修要求']
    (blocked, reasons, slots, lanes, groups, waves, active_window, core,
     group_active, individual_active, wave_sizes) = organization_inputs(request.conditions, reasons)
    org = dict(status='withheld' if blocked else 'pending_confirmation', reasons=reasons,
               groups=groups, wave_sizes=wave_sizes, rotation_count=waves,
               concurrent_students=0 if blocked else slots, declared_capacity= request.conditions.declared_practice_capacity,
               capacity_source='teacher_declared_unverified', usable_area_m2=request.conditions.usable_area_m2,
               core_active_min_per_student=core,
               note='仅为组织设计假设，不证明安全容量或师生比；教师先修确认未经认证。')
    duties = [{'role':'coach', 'number':i+1, 'task':'负责拟定组的组织与异常报告；专项示范和保护要求待审核，不提供动作要领'} for i in range(request.conditions.coach_count)]
    duties += [{'role':'teacher', 'number':i+1, 'task':'核对人员、装备及冰外等待区，确认轮换交接；不替代专项教练'} for i in range(request.conditions.teacher_count)]
    if blocked:
        duties = [{'role':'staff', 'number':0, 'task':'仅核对暂缓原因，不组织冰上实施'}]
    snapshot_versions={(entry['knowledge_id'],entry['version']) for entry in lesson['linked_knowledge']}
    approved = [item for item in registry.teaching_evidence(request.lesson_id) if (item['knowledge_id'],item['version']) in snapshot_versions]
    notice = ('待审核教案框架；受控审阅建议仅用于本课草稿，专项实操仍须现场教师与安全复核。' if approved else '待审核教案框架；缺少正式专项依据，暂缓专项实操、示范与技术评价。')
    contents = ['点名、装备和场地核查；核对先修资料与人员职责。',
                ('暂缓全部冰上组织；29分钟用于核对资源和先修缺项、资料讨论。' if blocked else '预留示范核查5分钟、轮换组织24分钟（每轮转换1分钟设计假设）；专项内容为空，审核前改为资料核对与口头讨论。'),
                '整理记录、学生自评问题收集、教师复核交接；不作技术评分。']
    flow = TeachingFlow(total_minutes=45, phases=[dict(phase=p, minutes=m, content=contents[i],
            teacher_activity='核查条件与分工，专项审核前不组织实操', student_activity='参与条件核对、口头讨论与自评记录',
            organization='暂缓冰上安排' if blocked else '拟定分组待现场确认；不是实施许可', safety_tip=notice,
            evaluation='仅记录组织与资料问题，不评价动作合格与等级')
            for i, (p,m) in enumerate([('prep',9),('main',29),('closing',7)])]).model_dump(mode='json')
    load = AdaptiveLoad(total_minutes=45, group_density=_metric('预计群体活动窗口密度',group_active),
        individual_density=_metric('预计人均活动密度',individual_active),
        note='复用原活动窗口算法：准备4+结束3，基本29=示范5+轮换24，每轮转换1；均为条件满足后的设计假设，非当前实施量；专项暂缓期间实际负荷不推定，心率不估计。').model_dump(mode='json')
    materials = []
    reviewed_ids={item['knowledge_id'] for item in approved}
    reports=registry.evidence_reports()
    for entry in lesson['linked_knowledge']:
        source_complete = all(entry[k] for k in ('source_id','source_title','source_locator'))
        materials.append({k: deepcopy(entry[k]) for k in ('knowledge_id','category','title','version','source_id','source_title','source_locator','source_verification_status','specialist_review_status','chapter','candidate_version','applicability_limitations','content_kind')})
        materials[-1].update(source_registered=source_complete, source_content_verified=entry['knowledge_id'] in reviewed_ids,
                             specialist_verified=entry['knowledge_id'] in reviewed_ids,
                             reported_inspection_note=entry.get('evidence_inspection_note',''),
                             specialist_confirmation_reported=any(r['knowledge_id']==entry['knowledge_id'] and r['knowledge_version']==entry['version'] and r['kind']=='specialist_report' for r in reports),
                             system_review_status='operator_authenticated' if entry['knowledge_id'] in reviewed_ids else 'pending', usage='metadata_only_not_teaching_guidance',
                             exclusion_reason='已绑定受控草稿建议，仍须现场复核。' if entry['knowledge_id'] in reviewed_ids else '来源登记不等于正文核实；尚无可信专项审核。不得用作确定性动作指导。')
    return dict(schema_version='lesson-framework-v3.1', mode='lesson', lesson={k:lesson[k] for k in ('lesson_id','title','duration_min','teaching_objective_draft')},
        title=lesson['title']+'｜待审核教案框架', review_status='pending_review', requires_teacher_review=True,
        execution_status='withheld_pending_teacher_and_safety_review' if approved else 'withheld_pending_specialist_evidence', technical_guidance=[{**item,'status':'reviewed_suggestion_pending_teacher_confirmation'} for item in approved if item['category']=='KB-S' and item['content_kind']=='source_summary'], formal_teaching_evidence=approved,
        objective_draft=lesson['teaching_objective_draft'], conditions=request.conditions.model_dump(),
        prerequisites={'teacher_confirmed':request.prerequisites_confirmed,'verification_status':'unverified','requirements_status':'missing'},
        preparation_checklist=['核对冰面及场地区域','逐人核查装备齐备和适配','核定容量、等待区及人员交接','补齐专项来源、先修要求与审核记录'],
        teaching_flow=flow, organization=org, staff_tasks=duties, load_accounting=load,
        differentiation=['支持层：待核实学生先修与支持需求','巩固层：专项任务待审核后填写','进阶层：无专项许可不提高难度'],
        knowledge_inventory=materials, missing_materials=missing,
        teacher_review_checklist=['核实知识条目与来源原文支持关系','取得可追溯专项审核意见','确认学生先修与适用水平','复核现场容量、人员、装备与等待区','复核分组及预计负荷假设','逐项复核教师修改，确认前不实施'],
        teaching_suggestions=approved,
        evidence_reports=[report for report in registry.evidence_reports() if report['knowledge_id'] in {entry['knowledge_id'] for entry in lesson['linked_knowledge']}],
        evidence_status='reviewed_suggestions_available' if approved else 'insufficient',
        warning=notice, teacher_edits=[], current_teacher_edits=TeacherEdits().model_dump())


class PlanStore:
    """100 revisions total / 2 MiB JSON, browser-owned until shutdown (global capacity)."""
    def __init__(self):
        self._plans = {}
        self._owners = {}
        self._lock = RLock()

    def clear(self):
        with self._lock:
            self._plans.clear()
            self._owners.clear()

    def _commit(self, plan_id, snapshots):
        proposed = {**self._plans, plan_id:snapshots}
        if sum(map(len,proposed.values())) > 100 or len(json.dumps(proposed,ensure_ascii=False).encode()) > 2*1024*1024:
            raise RegistryError('Plan capacity reached; export before restart')
        self._plans = proposed
        return deepcopy(snapshots[-1])

    def create(self, request, registry, *, owner="internal"):
        plan = build_framework(request,registry)
        plan_id = uuid4().hex
        plan.update(plan_id=plan_id, version=1)
        self._apply_edit(plan,request.edits)
        with self._lock:
            result = self._commit(plan_id,[plan])
            self._owners[plan_id] = owner
            return result

    def _apply_edit(self, plan, edits):
        values = edits.model_dump()
        plan['current_teacher_edits'] = values
        plan['effective_goal_draft'] = {'text':values['goal_draft'] or plan['objective_draft'],
                                        'status':'teacher_pending_review' if values['goal_draft'] else 'generated_pending_review'}
        plan['teacher_edits'].append(dict(version=plan['version'], changed_at=datetime.now(timezone.utc).isoformat(),
            actor='local_unverified_operator', review_status='pending_review', values=values))
        # Teacher text remains separate, explicitly unapproved; never overwrite
        # generated safety, resource holds, evidence status, flow or technical fields.

    def edit(self, request, *, owner="internal"):
        with self._lock:
            versions = self._plans.get(request.plan_id)
            if not versions or self._owners.get(request.plan_id) != owner:
                raise RegistryError('Plan not found in this process')
            if versions[-1]['version'] != request.expected_version:
                raise RegistryError('Version conflict; reload latest plan')
            plan = deepcopy(versions[-1]); plan['version'] += 1
            edits = TeacherEdits(**{k:getattr(request,k) for k in TeacherEdits.model_fields})
            self._apply_edit(plan,edits)
            return self._commit(request.plan_id,[*versions,plan])

    def read(self, plan_id, history=False, *, owner="internal"):
        with self._lock:
            versions = self._plans.get(plan_id)
            if not versions or self._owners.get(plan_id) != owner:
                raise RegistryError('Plan not found in this process')
            return deepcopy(versions if history else versions[-1])


def guard_current_evidence(plan, registry):
    """Preserve historical records internally, never re-export withdrawn guidance."""
    if not plan.get('formal_teaching_evidence'):
        return plan
    active={(item['knowledge_id'],item['version'],item['review_id']) for item in registry.teaching_evidence(plan['lesson']['lesson_id'])}
    def permitted(item):return (item['knowledge_id'],item['version'],item['review_id']) in active
    withdrawn=[item for item in plan['formal_teaching_evidence'] if not permitted(item)]
    if not withdrawn:return plan
    plan=deepcopy(plan)
    for key in ('formal_teaching_evidence','technical_guidance','teaching_suggestions'):
        plan[key]=[item for item in plan.get(key,[]) if permitted(item)]
    plan['withdrawn_evidence']=[{k:item[k] for k in ('knowledge_id','version','source_id','review_id')} for item in withdrawn]
    withdrawn_ids={(item['knowledge_id'],item['version']) for item in withdrawn}
    for item in plan['knowledge_inventory']:
        if (item['knowledge_id'],item['version']) in withdrawn_ids:
            item.update(source_content_verified=False,specialist_verified=False,system_review_status='withdrawn_or_stale',exclusion_reason='审核或版本已变化，须重新复核。')
    plan['evidence_status']='requires_regeneration_after_review_change'
    plan['execution_status']='withheld_pending_specialist_evidence'
    plan['warning']='审核或知识版本已变化；已撤下失效建议，请重新生成并人工复核。'
    return plan
