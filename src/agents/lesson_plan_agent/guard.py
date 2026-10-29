"""教案生成 Agent —— 证据来源与未审核事件保护。

规则：
- 知识库未接入时，任何 kb 证据一律降级为 unverified，citation 必须为 None，禁止虚构出处。
- 未经教练审核（review_status != "confirmed"）的 V4 事件，不得描述为"已确认技术错误"。
"""
from typing import List

from .schemas import CONFIRMED_STATUS, EvidenceEntry


def unverified_kb() -> str:
    """知识库未接入时的事实上下文标记。返回固定提示，且不会携带虚构引用。"""
    return "【知识库未核实】当前未接入已检索的课程标准/冰场安全规范，引用不得虚构文件、章节或页码。"


def can_describe_as_confirmed(event_ref) -> bool:
    """仅教练状态下 confirmed 的事件才可描述为"已确认"；其余一律不可。"""
    if event_ref is None:
        return False
    return event_ref.review_status == CONFIRMED_STATUS


def validate_event_claims(evidence_log: List[EvidenceEntry]) -> List[str]:
    """校验证据中引用的事件是否被错误地描述为已确认。

    对 source == real_analysis 且带 event_ref 的条目：
    - review_status != "confirmed" → 不允许 statement 以"已确认/确诊/确定是错误"等确认性措辞开头。
    返回违反提示列表；为空表示全部合规。
    """
    violations: List[str] = []
    prefixes = ("已确认", "确诊", "确定是错误", "已成定论", "认定为技术错误")
    for ent in evidence_log:
        if ent.event_ref is None:
            continue
        ref = ent.event_ref
        if ref.review_status == CONFIRMED_STATUS:
            continue
        if ent.statement.lstrip().startswith(prefixes):
            violations.append(
                f"event_id={ref.event_id} (review_status={ref.review_status}) 尚未经教练确认，"
                f"不得描述为已确认技术错误。请改为『待审核』措辞。"
            )
    return violations