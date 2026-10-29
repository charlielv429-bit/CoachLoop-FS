"""事件结论由结构化审核状态授权；未确认事件仅允许固定观察模板。"""
from typing import List
from .schemas import (CONFIRMED_STATUS, NON_CONFIRMED_EVENT_STATUSES,
                      EvidenceEntry, EvidenceSource, EventClaim)


def unverified_kb() -> str:
    return "【知识库未核实】当前未接入已检索的课程标准/冰场安全规范，引用不得虚构文件、章节或页码。"


def can_describe_as_confirmed(event_ref) -> bool:
    return event_ref is not None and event_ref.review_status == CONFIRMED_STATUS


def event_observation_statement(event_ref) -> str:
    """不插入自由文本和未经确认的诊断结论。"""
    return (f"事件 {event_ref.event_id}：审核状态 {event_ref.review_status}，"
            "仅记录二维可观测变化，尚未确认为技术错误。")


def validate_event_claims(evidence_log: List[EvidenceEntry]) -> List[str]:
    violations = []
    for ent in evidence_log:
        ref = ent.event_ref
        if ref is None:
            if ent.source == EvidenceSource.REAL_ANALYSIS or ent.event_claim == EventClaim.CONFIRMED_ERROR:
                violations.append("真实事件分析或已确认错误结论必须提供 event_ref")
            continue
        if ref.review_status not in (*NON_CONFIRMED_EVENT_STATUSES, CONFIRMED_STATUS):
            violations.append(f"event_id={ref.event_id} 审核状态无效")
            continue
        if can_describe_as_confirmed(ref):
            continue
        # 保留旧版固定中性观察句的兼容；其他自由文本一律需人审。
        neutral_statements = {
            event_observation_statement(ref),
            "该事件有待审核，尚未确认为错误",
        }
        if ent.event_claim != EventClaim.OBSERVATION or ent.statement not in neutral_statements:
            violations.append(
                f"event_id={ref.event_id} (review_status={ref.review_status}) 尚未经教练确认，"
                "不得描述为已确认技术错误；仅允许结构化 observation 与固定待审核观察表述。"
            )
    return violations
