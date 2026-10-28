"""V5-MVP 第一阶段：教练事件审核模块。

复用 V4 事件检测结果（/tmp/event_detection_result.json），为每个事件建立稳定
event_id，维护教练审核状态机（pending / confirmed / normal_movement /
tracking_error / uncertain），记录审核人/审核时间/备注，并**不可变保留**原始
事件数据与来源；提供审计轨迹以保证审核结果可追溯。

边界（非诊断）：
- 本模块不做动作诊断、不自动判定事件性质；初始全部为 pending。
- 不开发前端、不接大模型、不新增数据库；审核结果仅以 JSON 持久化。
- confirmed/normal_movement/tracking_error/uncertain 等由教练（或后续 Agent）
  显式写回，本模块只保证数据结构与追溯。
"""
import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# 合法审核状态（有序：按"无需关注 → 待确认 → 已确认 → 非动作 → 跟踪误差 → 不确定"）
VALID_REVIEW_STATUSES = (
    "pending",
    "confirmed",
    "normal_movement",
    "tracking_error",
    "uncertain",
)


class ReviewStatus(str, Enum):
    PENDING = "pending"              # 待教练审核（新建事件默认）
    CONFIRMED = "confirmed"          # 教练确认为真实动作变化
    NORMAL_MOVEMENT = "normal_movement"  # 教练判定为正常滑行/常规动作，非可疑变化
    TRACKING_ERROR = "tracking_error"    # 教练判定为关键点跟踪误差/数据质量所致
    UNCERTAIN = "uncertain"          # 教练无法判定（信息不足）


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def make_event_id(source_video_path: str, frame_start: int, frame_end: int, feature: str) -> str:
    """为事件生成稳定、可复现、含来源的 event_id。

    同一 (video, frame_start, frame_end, feature) 永远生成同一 id；不同事件
    不同 id（含视频路径避免跨视频冲突）。
    """
    raw = f"{source_video_path}|{frame_start}|{frame_end}|{feature}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"evt_{digest}"


def validate_status(status: str) -> str:
    """校验审核状态合法；非法抛 ValueError。"""
    if status not in VALID_REVIEW_STATUSES:
        raise ValueError(
            f"非法审核状态 {status!r}，合法值: {sorted(VALID_REVIEW_STATUSES)}"
        )
    return status


class ReviewAction(BaseModel):
    """一次审核写回动作（审计轨迹单元）。"""
    status: ReviewStatus = Field(..., description="审核状态")
    reviewed_by: str = Field(..., description="审核人")
    reviewed_at: str = Field(..., description="审核时间（ISO8601 UTC）")
    note: str = Field(default="", description="审核备注/理由")


class EventReviewRecord(BaseModel):
    """单个事件 + 审核信息（原始事件与来源不可变，审核字段可写）。"""
    event_id: str = Field(..., description="稳定且可复现的事件 id")
    # —— 以下为不可变原始快照（来自 V4，审核不覆盖）——
    original_event: Dict[str, Any] = Field(..., description="V4 原始事件数据快照（不可变）")
    source: Dict[str, Any] = Field(..., description="来源溯源（video_path/fps/input_json 等，不可变）")
    created_at: str = Field(..., description="本审核记录创建时间（ISO8601 UTC）")
    # —— 以下为可写审核字段 ——
    review_status: ReviewStatus = Field(default=ReviewStatus.PENDING, description="当前审核状态")
    reviewed_by: Optional[str] = Field(default=None, description="审核人")
    reviewed_at: Optional[str] = Field(default=None, description="最近一次审核时间（ISO8601 UTC）")
    notes: str = Field(default="", description="审核备注/理由")
    review_history: List[ReviewAction] = Field(default=[], description="审计轨迹（按时间追加，可追溯）")
    updated_at: str = Field(..., description="最近更新时间（ISO8601 UTC）")


class EventReviewOutput(BaseModel):
    """教练事件审核整体结构（结构化 JSON，供后续 Agent 消费）。"""
    kind: str = Field(default="coach_event_review", description="文档类型标识")
    version: str = Field(default="1.0", description="模块版本")
    generated_from: str = Field(..., description="来源文件路径（V4 event_detection JSON）")
    source: Dict[str, Any] = Field(..., description="来源溯源（video_path/fps/is_mock 等）")
    is_mock: bool = Field(False, description="是否人工 MOCK 数据（真实规划恒为 false）")
    records: List[EventReviewRecord] = Field(default=[], description="逐事件审核记录")
    summary: Dict[str, Any] = Field(default={}, description="按审核状态的计数汇总")

    def finalize(self) -> "EventReviewOutput":
        """基于 records 重建 summary。"""
        counts: Dict[str, int] = {}
        for r in self.records:
            counts[r.review_status.value] = counts.get(r.review_status.value, 0) + 1
        self.summary = {
            "total": len(self.records),
            "by_status": {s: counts.get(s, 0) for s in VALID_REVIEW_STATUSES},
        }
        return self


def build_review_records(
    event_detection: Dict[str, Any],
    generated_from: str,
) -> EventReviewOutput:
    """从 V4 event_detection JSON 构建审核记录（初始全 pending）。

    参数:
        event_detection: /tmp/event_detection_result.json 反序列化后的 dict。
        generated_from: 来源文件路径。
    """
    source: Dict[str, Any] = dict(event_detection.get("source") or {})
    source.setdefault("is_mock", bool(event_detection.get("is_mock", False)))
    source_video: str = str(source.get("video_path") or source.get("input_json") or "")
    now = _now_iso()

    records: List[EventReviewRecord] = []
    for ev in event_detection.get("events", []):
        fstart = int(ev["frame_start"])
        fend = int(ev["frame_end"])
        feature = str(ev["feature"])
        eid = make_event_id(source_video, fstart, fend, feature)
        records.append(
            EventReviewRecord(
                event_id=eid,
                original_event=dict(ev),  # 原始快照
                source=dict(source),
                created_at=now,
                review_status=ReviewStatus.PENDING,
                review_history=[],
                updated_at=now,
            )
        )
    out = EventReviewOutput(
        generated_from=generated_from,
        source=source,
        is_mock=bool(source.get("is_mock", False)),
        records=records,
    )
    return out.finalize()


def apply_review(
    record: EventReviewRecord,
    status: str,
    reviewed_by: str,
    reviewed_at: Optional[str] = None,
    note: str = "",
) -> EventReviewRecord:
    """显式写回一条审核（人工或后续 Agent 调用）。

    - 校验状态合法；
    - 只更新审核字段，**绝不覆盖** original_event / source；
    - 追加一条审计轨迹（可追溯）。
    """
    validate_status(status)
    if not reviewed_by or not str(reviewed_by).strip():
        raise ValueError("reviewed_by 不能为空")
    at = reviewed_at or _now_iso()
    action = ReviewAction(
        status=ReviewStatus(status),
        reviewed_by=str(reviewed_by).strip(),
        reviewed_at=at,
        note=note,
    )
    record.review_history.append(action)
    record.review_status = action.status
    record.reviewed_by = action.reviewed_by
    record.reviewed_at = action.reviewed_at
    record.notes = note
    record.updated_at = _now_iso()
    return record