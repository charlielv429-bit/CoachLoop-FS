"""逐帧姿态特征提取：缺失关键点、退化几何与异常数据处理。

只计算可观测几何量（膝角/躯干角/髋踝相对偏移），不产生评分或花滑诊断。
"""
import math
from typing import Any, Dict, List, Optional, Tuple

from .schemas import (
    AnalysisOutput,
    FeatureResult,
    FrameRecord,
    KeypointDataset,
    KeypointFrame,
)
from .geometry import (
    DegenerateGeometryError,
    angle_at_vertex,
    hip_ankle_offset_norm,
    torso_pitch_deg,
)

# MediaPipe Pose 关键点索引（仅用到肩/髋/膝/踝）
_MP: Dict[str, int] = {
    "left_shoulder": 11,
    "right_shoulder": 12,
    "left_hip": 23,
    "right_hip": 24,
    "left_knee": 25,
    "right_knee": 26,
    "left_ankle": 27,
    "right_ankle": 28,
}

_SIDE_MAP: Dict[str, Dict[str, str]] = {
    "left": {"hip": "left_hip", "knee": "left_knee", "ankle": "left_ankle"},
    "right": {"hip": "right_hip", "knee": "right_knee", "ankle": "right_ankle"},
}

_SUPPORTED_SIDES = frozenset(_SIDE_MAP.keys())


def _resolve(frame: KeypointFrame, name: str) -> Optional[Tuple[float, float]]:
    """按名称/索引取关键点 2D 坐标；缺失或坐标非有限值返回 None。"""
    idx = _MP[name]
    for lm in frame.landmarks:
        if lm.id == idx:
            if lm.x is None or lm.y is None:
                return None
            if not (math.isfinite(lm.x) and math.isfinite(lm.y)):
                return None  # NaN/Inf 视为无效，按缺失处理
            return (float(lm.x), float(lm.y))
    return None


def _midpoint(p1: Optional[Tuple[float, float]], p2: Optional[Tuple[float, float]]) -> Optional[Tuple[float, float]]:
    if p1 is None or p2 is None:
        return None
    return ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0)


def extract_features(frame: KeypointFrame, side: str = "left") -> FeatureResult:
    """从单帧关键点提取可观测姿态特征。

    side: "left" / "right"，选作支撑腿/判定腿的一侧，默认 left。
    异常：
        ValueError: side 取值非法。
    """
    if side not in _SUPPORTED_SIDES:
        raise ValueError(f"不支持的 side: {side}，可选 {sorted(_SUPPORTED_SIDES)}")

    lm = _SIDE_MAP[side]
    leg_hip = _resolve(frame, lm["hip"])
    leg_knee = _resolve(frame, lm["knee"])
    leg_ankle = _resolve(frame, lm["ankle"])
    left_shoulder = _resolve(frame, "left_shoulder")
    right_shoulder = _resolve(frame, "right_shoulder")
    left_hip = _resolve(frame, "left_hip")
    right_hip = _resolve(frame, "right_hip")

    shoulder_mid = _midpoint(left_shoulder, right_shoulder)
    hip_mid = _midpoint(left_hip, right_hip)

    # 记录缺失的必需关键点
    missing: List[str] = []
    for name, point in (
        (f"{side}_hip", leg_hip),
        (f"{side}_knee", leg_knee),
        (f"{side}_ankle", leg_ankle),
        ("left_shoulder", left_shoulder),
        ("right_shoulder", right_shoulder),
        ("left_hip", left_hip),
        ("right_hip", right_hip),
    ):
        if point is None:
            missing.append(name)

    feat = FeatureResult(missing_required=missing)

    def _safe(computable: bool, call, reason_key: str) -> Optional[float]:
        if not computable:
            return None
        try:
            value = call()
        except DegenerateGeometryError as exc:
            feat.degenerate = True
            feat.degeneracy_reason = (
                feat.degeneracy_reason + f";{reason_key}:{exc.reason}"
                if feat.degeneracy_reason
                else f"{reason_key}:{exc.reason}"
            )
            return None
        return round(float(value), 3)

    # 膝关节二维夹角
    feat.knee_angle_deg = _safe(
        leg_hip is not None and leg_knee is not None and leg_ankle is not None,
        lambda: angle_at_vertex(leg_hip, leg_knee, leg_ankle),
        "knee",
    )
    # 躯干倾角（大小）
    feat.torso_pitch_deg = _safe(
        shoulder_mid is not None and hip_mid is not None,
        lambda: torso_pitch_deg(shoulder_mid, hip_mid),
        "torso",
    )
    # 髋踝相对水平偏移（图像平面，归一化）
    feat.hip_ankle_offset_norm = _safe(
        hip_mid is not None and leg_ankle is not None,
        lambda: hip_ankle_offset_norm(hip_mid, leg_ankle),
        "hip_ankle",
    )
    return feat


def _frame_stats(frame: KeypointFrame) -> Dict[str, Any]:
    total = len(frame.landmarks)
    finite = 0
    vis_values: List[float] = []
    for lm in frame.landmarks:
        if lm.x is not None and lm.y is not None and math.isfinite(lm.x) and math.isfinite(lm.y):
            finite += 1
        if lm.visibility is not None:
            vis_values.append(float(lm.visibility))
    avg_vis = round(sum(vis_values) / len(vis_values), 3) if vis_values else None
    return {
        "total": total,
        "finite": finite,
        "missing": total - finite,
        "missing_ratio": round((total - finite) / total, 3) if total else 1.0,
        "avg_visibility": avg_vis,
    }


def process_keypoint_dataset(dataset: KeypointDataset, side: str = "left") -> AnalysisOutput:
    """处理整个关键点数据集，输出结构化结果（含逐帧特征与观测统计）。"""
    records: List[FrameRecord] = []
    errors: List[str] = []

    for frame in dataset.frames:
        try:
            feat = extract_features(frame, side=side)
        except ValueError as exc:
            errors.append(f"frame {frame.frame_idx}: {exc}")
            feat = FeatureResult()
        records.append(
            FrameRecord(
                frame_idx=frame.frame_idx,
                timestamp_ms=frame.timestamp_ms,
                features=feat,
                keypoint_stats=_frame_stats(frame),
            )
        )

    n = len(records)
    knee_ok = sum(1 for r in records if r.features.knee_angle_deg is not None)
    torso_ok = sum(1 for r in records if r.features.torso_pitch_deg is not None)
    offset_ok = sum(1 for r in records if r.features.hip_ankle_offset_norm is not None)
    degenerate = sum(1 for r in records if r.features.degenerate)

    summary: Dict[str, Any] = {
        "n_frames": n,
        "side": side,
        "knee_detect_ratio": round(knee_ok / n, 3) if n else 0.0,
        "torso_detect_ratio": round(torso_ok / n, 3) if n else 0.0,
        "hip_ankle_detect_ratio": round(offset_ok / n, 3) if n else 0.0,
        "degenerate_frames": degenerate,
    }

    source: Dict[str, Any] = {
        "mode": "mock",
        "is_mock": bool(dataset.is_mock),
        "source": dataset.source,
        "model": dataset.model,
        "fps": dataset.fps,
    }

    return AnalysisOutput(source=source, frames=records, summary=summary, errors=errors)