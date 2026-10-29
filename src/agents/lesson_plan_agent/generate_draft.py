"""教案生成 Agent —— 花样滑冰教案草稿生成器（任务1）。

确定性、无大模型：依据教师输入与阶段 A 的七要素/三段式/负荷/证据保护，
生成《初学者 45 分钟 冰上双足滑行与身体姿态控制》结构化教案草稿（可序列化 JSON）。

规则（继承阶段 A 保护）：
- 课标知识库未接入 → 涉及课标/规范一律标记 unverified，不虚构文件·章节·页码。
- 未经教练审核的姿态事件不得描述为"已确认技术错误"（本生成器默认不引入任何事件证据，并再次经 guard 校验）。
- 所有花滑技术建议标注"待专业教练确认"，不虚构技术角度合格阈值。
"""
import argparse
import json
import re
from typing import Optional

from .guard import unverified_kb, validate_event_claims
from .load_calc import calc_load, min_activity_for_targets
from .schemas import (
    EvidenceEntry,
    EvidenceSource,
    GuidingIdeology,
    LearnerAnalysis,
    LessonPlan,
    LoadAccounting,
    MeasurementKind,
    Phase,
    ReviewStatus,
    SafetyPrecautions,
    TeacherInput,
    TeachingFlow,
    TeachingMaterialAnalysis,
    TeachingPhase,
    VenueEquipment,
)
from pydantic import BaseModel, Field, field_validator, model_validator

try:  # 知识库适配器为可选依赖；缺失时安全降级（教案仍可生成，转入 unverified）
    from . import kb_adapter
except Exception:  # pragma: no cover
    kb_adapter = None

_TOTAL_MIN = 45  # 默认总课时
_KB_MIN_SCORE = 0.5  # 纳入教案的知识库命中最低相似度

# 师资解析：从教师输入条件中提取人数（未明确时不得自行增设）
_STAFF_RE = {
    "教练": re.compile(r"教练\s*(\d+)\s*(?:名|人)"),
    "教师": re.compile(r"教师\s*(\d+)\s*(?:名|人)"),
}


def _parse_staffing(conditions: str) -> dict:
    """解析教师输入中的教练/教师人数；未明确时返回 None。"""
    out: dict = {}
    for role, pat in _STAFF_RE.items():
        m = pat.search(conditions or "")
        out[role] = int(m.group(1)) if m else None
    return out


def _build_staffing(conditions: str) -> str:
    """依据输入生成师资说明，避免自行增设人员或虚构岗位编制。"""
    st = _parse_staffing(conditions)
    parts = []
    if st["教练"] is not None:
        parts.append(f"教练{st['教练']}名")
    if st["教师"] is not None:
        parts.append(f"教师{st['教师']}名")
    if parts:
        base = "+".join(parts) + "；岗位分工（巡视/随组/观照全局）按现场由教师核定，不虚构新增人员"
    else:
        base = "教学人员配置以输入与现场核定为准，本稿不自行增设人员"
    return base + "；涉学生安全分工须由教师按班级实际统筹。"


def _build_grouping_and_tiers() -> tuple:
    """能力分层(3级)与轮换分组(4组)的对应关系，避免含糊/冲突。"""
    tier_plan = (
        "按站稳程度分 3 个能力层级：层级①仍扶栏者加固站稳；层级②可站稳者练短距滑行；"
        "层级③较稳者可尝试增大滑距（须教师确认后再加入重心转移小练）。"
    )
    grouping = (
        "轮换组 4 组（A/B/C/D）用于场地轮换；能力分层 3 级与之对应——层级①→组A，"
        "层级②→组B、组C，层级③→组D；具体人数与分组由教师按到场名册现场核定。"
    )
    return tier_plan, grouping


class LessonPlanDraftInput(BaseModel):
    """教师输入的教学条件（用于生成教案草稿）。"""

    audience: str = Field(..., min_length=1, description="教学对象（如：小学三年级）")
    student_count: int = Field(..., gt=0, description="学生人数（>0）")
    skill_level: str = Field(..., min_length=1, description="技术水平（如：初学者）")
    theme: str = Field(default="冰上双足滑行与身体姿态控制", min_length=1, description="教学主题/动作")
    conditions: str = Field(default="标准冰场1片；教练2人+教师1人；冰鞋/护具/标志桶若干", description="教学条件（场地/器材/人员）")
    total_minutes: int = Field(default=45, gt=0, description="总课时（分钟）")
    group_active_min: float = Field(default=36.0, ge=0.0, description="群体活动时间（分钟）")
    individual_active_min: float = Field(default=25.0, ge=0.0, description="个体有效练习时间（分钟）")
    avg_hr: float = Field(default=145.0, ge=0.0, description="预计平均心率（次/分）")
    class_data_available: bool = Field(default=False, description="是否有经授权班级训练记录")

    @model_validator(mode="after")
    def _check_total_minutes(self) -> "LessonPlanDraftInput":
        if self.total_minutes != _TOTAL_MIN:
            raise ValueError(f"当前仅支持总课时 = {_TOTAL_MIN} 分钟，实际 {self.total_minutes}")
        return self

    @model_validator(mode="after")
    def _check_load_times_within(self) -> "LessonPlanDraftInput":
        if self.group_active_min > self.total_minutes:
            raise ValueError("群体活动时间不能超过总课时")
        if self.individual_active_min > self.total_minutes:
            raise ValueError("个体练习时间不能超过总课时")
        return self


def _build_phases() -> list:
    """三段式（准备9 / 基本29 / 结束7 = 45 分钟）：冰上双足滑行与身体姿态控制。"""
    return [
        Phase(
            phase=TeachingPhase.PREP,
            minutes=9,
            content="课堂常规、健康与装备检查；陆地关节激活（踝/膝/髋）；冰上适应性热身（扶栏站立、原地踏步、小步随行）。",
            teacher_activity="整队点名、讲解本课目标；示范扶栏站立与热身动作；巡回检查装备与健康状态（由教师按学校制度执行）。",
            student_activity="着装与护具检查；跟随完成陆地踝膝髋活动；冰上扶栏站立、原地踏步与小步热身。",
            organization="冰场边沿分 4 组，护栏辅助；教师位于入口中区观察全局。",
            safety_tip="全程佩戴护具；冰面防滑、禁止奔跑；感到不适立即示意教师。",
            evaluation="口头评定装备检查与热身完成度。",
        ),
        Phase(
            phase=TeachingPhase.MAIN,
            minutes=29,
            content="讲解示范双足滑行与身体姿态控制（基本站姿）；扶栏→放手短距滑行；重心小步转移与制动小练习；分段巩固，录像留存。",
            teacher_activity="示范「稳定基本站姿」：膝微屈、躯干适度前倾、头平视前方、双脚平刃着冰（具体技术要点待专业教练确认）；组织分组轮换练习与辅助练习；设置拍摄机位，巡回纠正身体姿态。",
            student_activity="模仿基本站姿；扶栏滑行→放手短距滑行；两人一组互看姿态并小声提示；完成短距双足滑行练习。",
            organization="分 4 组循环（练习区/缓冲/观察区），教师位于场地短边中区，各组间隔拉开。",
            safety_tip="练习区内并行抢道/嬉闹：教师依现场情况制止并重申依次出发；摔倒保护、起身与制动停住的技术要领待专项教练确认后用于教学；保持间距、依次出发。",
            evaluation="分层观察评价（教师拟定的过程性观察目标，非官方技术合格线）：层级①能在扶栏辅助下保持基本站姿；层级②能放手完成短距滑行并保持目视前方；层级③能在较大滑距内保持姿态稳定；另以录像留存供课后 CoachLoop-FS 复核。",
        ),
        Phase(
            phase=TeachingPhase.CLOSING,
            minutes=7,
            content="陆地整理放松；课堂小结；学习评价；器材回收与后续练习提示。",
            teacher_activity="带领放松整理；总结「稳定站姿 / 双足滑行」要点并预告下节课；组织器材回收与有序离场。",
            student_activity="跟随放松；自评本课参与与收获；回收器材、有序离场。",
            organization="集合成圈；教师居中。",
            safety_tip="离场前检查冰面；有序离场，不奔跑。",
            evaluation="学生自评+教师按三层级逐项口头点评（过程性评价，不作成绩判定，不设定官方合格线）。",
        ),
    ]


def _build_load(total: int, group: float, indiv: float, avg_hr: float) -> LoadAccounting:
    """复用确定性负荷核算，返回预计值（待课堂实测验证）。"""
    return calc_load(
        total_minutes=total,
        group_active_min=group,
        individual_active_min=indiv,
        avg_hr=avg_hr,
        kind=MeasurementKind.ESTIMATED,
    )


def _is_verified_kb_entry(entry, min_score: float = _KB_MIN_SCORE) -> bool:
    """只有可信人审已确认支持当前教学陈述的 A 级正文才可采用。"""
    return (kb_adapter is not None and
            kb_adapter.classify_evidence(entry, min_score=min_score)
            is kb_adapter.EvidenceGrade.A)


def _build_kb_evidence(entries) -> list:
    """仅将人审确认支持当前陈述的 A 级证据纳入教案。"""
    evs = []
    for e in entries or []:
        if not _is_verified_kb_entry(e):
            continue
        content = (getattr(e, "content", "") or "").strip()
        if not content:
            continue
        citation = f"{getattr(e, 'source_file')} | 原PDF第{getattr(e, 'page')}页"
        evs.append(EvidenceEntry(
            statement=f"【人工核验A级教学依据】{kb_adapter.DEFAULT_STATEMENT}",
            source=EvidenceSource.KB_EVIDENCE,
            citation=citation,
        ))
    return evs


def build_draft(inp: LessonPlanDraftInput, kb_evidence: Optional[list] = None) -> LessonPlan:
    """确定性生成七要素教案草稿。"""
    total = inp.total_minutes
    audience_full = f"{inp.audience}·{inp.student_count}人·{inp.skill_level}"

    flow = TeachingFlow(total_minutes=total, phases=_build_phases())
    load = _build_load(total, inp.group_active_min, inp.individual_active_min, inp.avg_hr)
    # 密度/心率数值为依据输入活动时间推算的设计目标，尚未由课堂环节安排实测验证（保留"预计值"口径）
    load = load.model_copy(
        update={
            "note": "群体/个体密度与平均心率均为预计值（设计目标，依据输入活动时间推算），"
                    "尚未由课堂环节安排实测验证，不得声称必然达标；待课堂实测后按实际活动时间/心率复核。"
        }
    )
    tier_plan, grouping = _build_grouping_and_tiers()
    staffing = _build_staffing(inp.conditions)

    # 证据来源/状态记录：课标未接入→unverified，不虚构引用；无已审核事件→不引入事件证据，且经 guard 复校验。
    kb_evs = _build_kb_evidence(kb_evidence)
    evidence_log = [
        EvidenceEntry(
            statement=f"教学对象：{audience_full}；教学主题：{inp.theme}；教学条件：{inp.conditions}。",
            source=EvidenceSource.TEACHER_INPUT,
        ),
        EvidenceEntry(
            statement=("除已列明的人审A级陈述外，其他课程标准和冰场安全规范依据尚未核实。"
                       if kb_evs else unverified_kb()),
            source=EvidenceSource.UNVERIFIED, citation=None,
        ),
        EvidenceEntry(
            statement="45分钟三段式时间分配与负荷比例为本方案设计假设，须经教师按班级实际复核；"
                      "预计心率/活动时间均为预计值，待课堂实测验证。",
            source=EvidenceSource.DESIGN_ASSUMPTION,
        ),
        EvidenceEntry(
            statement="CoachLoop-FS 视频姿态特征（膝角/躯干倾角/髋踝偏移）为可选辅助观察；"
                      "未经教练审核的姿态事件不得描述为已确认技术错误。",
            source=EvidenceSource.DESIGN_ASSUMPTION,
        ),
    ] + kb_evs  # 仅人工核验支持当前陈述的A级证据标记 kb_evidence；否则维持 unverified
    violations = validate_event_claims(evidence_log)
    if violations:
        raise ValueError("；".join(violations))  # 防御：不允许任何未审核事件被写成已确认错误

    plan = LessonPlan(
        title=f"花样滑冰·{inp.theme}（{total} 分钟·教师审核稿）",
        teacher_input=TeacherInput(
            audience=audience_full,
            theme=inp.theme,
            conditions=inp.conditions,
            class_data_available=inp.class_data_available,
        ),
        guiding_ideology=GuidingIdeology(
            content=(
                "围绕“健康第一”理念，通过冰上双足滑行与身体姿态控制学习，落实运动能力、健康行为与体育品德三个维度的可观察目标。"
                + ("（核心素养三维度的人工核验依据见证据清单 kb_evidence；不代表其他教学论断已核实。）" if kb_evs else "（课标依据：知识库未核实，不虚构出处。）")
            ),
            motor_competence="掌握安全基本站姿与短距双足滑行，能保持重心平稳、目视前方（具体技术标准待专业教练确认）。",
            healthy_behavior="养成课前热身与装备/冰面检查习惯，学会摔倒后原地待援的安全行为。",
            sports_ethics="遵守冰场秩序与器材管理规定，尊重同伴、互相提示。",
        ),
        teaching_material_analysis=TeachingMaterialAnalysis(
            technical_composition="冰上双足滑行由“基本站姿—推冰滑行—制动停住”构成，核心是身体姿态控制（膝部微屈、躯干适度前倾、头平视、重心在两脚间）。",
            key_points="保持平稳基本站姿与目视前方，双足平刃着冰。",
            difficulties="平衡掌控与身体姿态放松，避免重心后坐或紧张僵直。",
            progression="承接上一课的冰上站立，本节课过渡到短距滑行，为后续转弯与单足滑行铺垫。",
            note_2d_limitation="膝角/躯干倾角/髋踝偏移为二维视频可观测几何量，不等同于真实重心、冰刀用刃或经证实的专项技术错误；本课不设置技术角度合格阈值，具体动作标准待专业教练确认。",
        ),
        learner_analysis=LearnerAnalysis(
            student_profile=audience_full + "，为冰上双足滑行零基础到起步阶段。",
            common_difficulties="重心后坐、双腿紧张僵直、不敢放手滑行。",
            tiered_plan=tier_plan,
            note="已确认事实来自教师输入；未经审核姿态事件与待核实推测另以证据来源标记，不作确定结论。",
        ),
        venue_equipment=VenueEquipment(
            zones="练习区/缓冲停区/观察区（冰场货物区域按现场实际划分）。",
            route="绕固定标志桶单向短距滑行路线。",
            observation_position="教师位于场地短边中区，便于同时观察 4 组。",
            grouping=grouping,
            equipment_list="冰鞋、护具（头盔/护膝/护腕）、标志桶若干、备用护栏（按冰场实际配置）。",
            camera_position="固定支架对角机位，录制全体练习画面（可选，用于课后 CoachLoop-FS 反馈）。",
        ),
        safety_precautions=SafetyPrecautions(
            risk_screening="课前由教师按学校制度做健康问询与身体不适筛查（本 AI 不进行医疗判断）。",
            ice_check="开课前检查冰面平整、无裂缝异物、护栏完好。",
            equipment_check="逐人检查冰鞋刀刃、护具系带，尺码合适。",
            staffing=staffing,
            zone_management="练习区与缓冲区隔离，组间保持间距；教师依现场情况管理并行抢道并强调依次出发。",
            emergency_flow="摔倒后先原地待援或依教练指示扶栏等待；若受伤或无法起身，保持原地并立即示意教师，由教师按学校应急预案处置。",
            medical_note="涉及伤病/呼吸系统疾病/身体不适，仅提醒教师按学校既有制度核查，AI 不擅自诊断或处理医疗问题；摔倒保护、起身方式与制动停住等技术要领待专项教练确认后用于教学。",
        ),
        teaching_flow=flow,
        load_accounting=load,
        evidence_log=evidence_log,
        review_status=ReviewStatus.DRAFT,
        plan_version="1.0",
    )
    return plan


def draft_to_json(plan: LessonPlan) -> str:
    """输出可序列化 JSON（供后续接入 Coze 工作流/教师审核界面）。"""
    return plan.model_dump_json(indent=2, ensure_ascii=False)


def main() -> None:  # CLI 演示入口
    parser = argparse.ArgumentParser(description="花样滑冰教案草稿生成器（任务1，确定性，无大模型）")
    parser.add_argument("--audience", default="小学三年级", help="教学对象")
    parser.add_argument("--student-count", type=int, default=30, help="学生人数")
    parser.add_argument("--skill-level", default="初学者", help="技术水平")
    parser.add_argument("--theme", default="冰上双足滑行与身体姿态控制", help="教学主题")
    parser.add_argument("--conditions", default="标准冰场1片；教练2人+教师1人；冰鞋/护具/标志桶若干", help="教学条件")
    parser.add_argument("--total-minutes", type=int, default=45, help="总课时（仅支持45）")
    parser.add_argument("--group-active-min", type=float, default=36.0, help="群体活动时间(分钟)")
    parser.add_argument("--individual-active-min", type=float, default=25.0, help="个体有效练习时间(分钟)")
    parser.add_argument("--avg-hr", type=float, default=145.0, help="预计平均心率(次/分)")
    parser.add_argument("--kb", action="store_true", help="尝试一次真实知识库检索并采纳可核验命中")
    parser.add_argument("--output", default="-", help="输出文件路径（默认 - 打印到标准输出）")
    args = parser.parse_args()

    inp = LessonPlanDraftInput(
        audience=args.audience,
        student_count=args.student_count,
        skill_level=args.skill_level,
        theme=args.theme,
        conditions=args.conditions,
        total_minutes=args.total_minutes,
        group_active_min=args.group_active_min,
        individual_active_min=args.individual_active_min,
        avg_hr=args.avg_hr,
        class_data_available=False,
    )
    kb_evidence = None
    if args.kb and kb_adapter is not None:
        try:
            resp = kb_adapter.retrieve_kb()
            # 检索仅产生候选正文；build_draft 仍要求独立可信人审记录
            kb_evidence = [h for hl in resp["hits"].values() for h in hl]
            print(f"[kb] 检索完成：{len(kb_evidence)} 条候选正文（未经人工核验不用于正式教学论断）")
        except Exception as exc:  # 知识库不可用→降级，不虚构
            print(f"[kb] 检索不可用，降级为未核实：{exc}")
            kb_evidence = None
    plan = build_draft(inp, kb_evidence=kb_evidence)
    payload = draft_to_json(plan)
    if args.output == "-":
        print(payload)
    else:
        with open(args.output, "w", encoding="utf-8") as fd:
            fd.write(payload + "\n")
        print(f"已写入: {args.output}")


if __name__ == "__main__":
    main()