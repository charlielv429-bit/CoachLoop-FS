"""V4-MVP：姿态变化事件检测与时间段统计。

只复用既有视频姿态特征（knee_angle_deg / torso_pitch_deg / hip_ankle_offset_norm）
与关键点质量统计，对姿态序列做轻量平滑与变化检测，把连续异常变化帧合并为事件，
并标记数据质量风险（review_required）。

明确边界（非花滑评分、非技术诊断）：
- 本模块基于 2D 图像平面可观测几何量，仅供教练复核参考。
- 不推断双腿遮挡、真实重心或冰刀用刃；这些判断须由教练结合 3D/冰面信息复核。
- 采用可配置的探索性阈值，不构成动作正确性标准。
"""
import math
from statistics import median
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# V4 关注的三个姿态特征（键名须与 V2 FeatureResult 输出字段一致）
FEATURE_KEYS: List[str] = ["knee_angle_deg", "torso_pitch_deg", "hip_ankle_offset_norm"]

# 特征 → 默认探索性阈值（偏离稳健基线的绝对量）
DEFAULT_THRESHOLDS: Dict[str, float] = {
    "knee_angle_deg": 10.0,
    "torso_pitch_deg": 4.0,
    "hip_ankle_offset_norm": 0.12,
}

DEFAULT_SMOOTH_WINDOW = 5      # 居中移动平均窗口（轻量平滑）
DEFAULT_VISIBILITY_THRESHOLD = 0.75  # 平均可见度低于此值标记低可见度

_DISCLAIMERS: List[str] = [
    "本结果基于 2D 图像平面可观测几何量，仅供教练复核参考，非动作评分或技术诊断。",
    "不依据 2D 数据推断双腿遮挡、真实重心位置或冰刀用刃，相关结论需教练结合 3D/冰面复核。",
    "下列阈值为可配置的探索性参数，不构成任何动作正确性标准。",
]


class EventConfig(BaseModel):
    """可配置的探索性检测参数（非评分标准）。"""
    knee_threshold_deg: float = Field(DEFAULT_THRESHOLDS["knee_angle_deg"], description="膝角偏离基线阈值（度）")
    torso_threshold_deg: float = Field(DEFAULT_THRESHOLDS["torso_pitch_deg"], description="躯干倾角偏离基线阈值（度）")
    hip_ankle_threshold_norm: float = Field(DEFAULT_THRESHOLDS["hip_ankle_offset_norm"], description="髋踝偏移偏离基线阈值（归一化）")
    smooth_window: int = Field(DEFAULT_SMOOTH_WINDOW, description="轻量居中移动平均窗口（帧）")
    visibility_threshold: float = Field(DEFAULT_VISIBILITY_THRESHOLD, description="平均可见度阈值，低于即低可见度")
    min_event_frames: int = Field(1, description="事件最少持续帧数（>=1）")

    def threshold_for(self, key: str) -> float:
        mapping = {
            "knee_angle_deg": self.knee_threshold_deg,
            "torso_pitch_deg": self.torso_threshold_deg,
            "hip_ankle_offset_norm": self.hip_ankle_threshold_norm,
        }
        return float(mapping[key])


class ChangeEvent(BaseModel):
    """单个连续异常变化事件。"""
    feature: str = Field(..., description="所属特征名")
    frame_start: int = Field(..., description="事件起始帧索引")
    frame_end: int = Field(..., description="事件结束帧索引（含）")
    start_time_ms: float = Field(..., description="起始时间（毫秒）")
    end_time_ms: float = Field(..., description="结束时间（毫秒）")
    duration_ms: float = Field(..., description="持续时长（毫秒）")
    n_frames: int = Field(..., description="事件覆盖帧数")
    deviation_max: float = Field(..., description="事件内相对稳健基线的最大偏离量（变化幅度）")
    swing: float = Field(..., description="事件内平滑信号的最大-最小原始差（实际变化幅度）")


class QualitySegment(BaseModel):
    """一段连续低质量/低可见度区间。"""
    frame_start: int = Field(..., description="起始帧")
    frame_end: int = Field(..., description="结束帧")
    start_time_ms: float = Field(..., description="起始时间（毫秒）")
    end_time_ms: float = Field(..., description="结束时间（毫秒）")
    reason: str = Field(..., description="风险原因（low_visibility / missing / undetected / degenerate）")
    detail: float = Field(default=0.0, description="相关量化指标（如最低可见度）")


class EventDetectionOutput(BaseModel):
    """V4 事件检测整体输出（结构化 JSON）。"""
    source: Dict[str, Any] = Field(..., description="来源信息：mode=real / is_mock=false / 视频路径 / fps")
    config: EventConfig = Field(..., description="本次使用到的检测参数")
    is_mock: bool = Field(False, description="是否人工 MOCK 数据（真实视频恒为 false）")
    event_count: Dict[str, Any] = Field(..., description="各特征事件数与总事件数，注意同一时间段可能被多个特征同时标记")
    events: List[ChangeEvent] = Field(default=[], description="合并后的变化事件列表")
    spike_anomalies: List[int] = Field(default=[], description="疑似跟踪异常/数据突跳的孤立异常帧（需人工复核）")
    low_visibility_segments: List[QualitySegment] = Field(default=[], description="低可见度片段")
    undetected_or_missing_frames: List[int] = Field(default=[], description="未检出/缺失关键点/退化几何的帧")
    review_required: bool = Field(False, description="是否建议教练复核数据质量")
    review_reasons: List[str] = Field(default=[], description="建议复核的原因")
    disclaimers: List[str] = Field(default_factory=lambda: list(_DISCLAIMERS), description="边界声明（非评分/非诊断）")
    reserved_coach_review: Dict[str, Any] = Field(
        default_factory=lambda: {
            "review_status": "pending",
            "needs_coach_review": True,
            "coach_notes": "",
            "coach_verdict": None,
        }
    )


def _centered_ma(vals: List[float], window: int) -> List[float]:
    """居中移动平均（边缘用可用邻居求平均，保持序列等长）。"""
    n = len(vals)
    if n == 0:
        return []
    if window <= 1:
        return [float(v) for v in vals]
    half = window // 2
    out: List[float] = []
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        seg = vals[lo:hi]
        out.append(sum(seg) / len(seg))
    return out


def _merge_events(abnormal: List[bool], sampled: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把连续异常帧（按帧索引相邻）合并为事件。

    sampled: 与 abnormal 等长的帧信息（frame_idx / timestamp_ms / smoothed / baseline）。
    返回合并后的事件（含边界帧、时长、偏离量、摆幅）。
    """
    events: List[Dict[str, Any]] = []
    idx = 0
    n = len(abnormal)
    while idx < n:
        if not abnormal[idx]:
            idx += 1
            continue
        j = idx
        # 合并连续异常帧（帧索引相邻才合并）
        while j + 1 < n and abnormal[j + 1] and sampled[j + 1]["frame_idx"] == sampled[j]["frame_idx"] + 1:
            j += 1
        group = sampled[idx: j + 1]
        s0, s1 = group[0], group[-1]
        deviations = [abs(g["smoothed"] - g["baseline"]) for g in group]
        smooth_vals = [g["smoothed"] for g in group]
        events.append(
            {
                "frame_start": s0["frame_idx"],
                "frame_end": s1["frame_idx"],
                "start_time_ms": s0["timestamp_ms"],
                "end_time_ms": s1["timestamp_ms"],
                "n_frames": len(group),
                "deviation_max": round(float(max(deviations)), 3),
                "swing": round(float(max(smooth_vals) - min(smooth_vals)), 3),
            }
        )
        idx = j + 1
    return events


def _analyze_feature(
    feature_key: str,
    points: List[Dict[str, Any]],
    threshold: float,
    smooth_window: int,
    min_event_frames: int,
) -> Dict[str, Any]:
    """对单个特征序列做平滑 + 变化检测 + 事件合并 + 孤立突跳标记。

    points: [{frame_idx, timestamp_ms, value}]，value 非 None、有限。
    """
    vals = [float(p["value"]) for p in points]
    if not vals:
        return {"smoothed": [], "baseline": None, "abnormal": [], "spikes": [], "events": []}
    smoothed = _centered_ma(vals, smooth_window)
    baseline = float(median(smoothed))
    sampled = [
        {"frame_idx": p["frame_idx"], "timestamp_ms": p["timestamp_ms"], "smoothed": sm, "baseline": baseline}
        for p, sm in zip(points, smoothed)
    ]
    abnormal = [abs(sm - baseline) > threshold for sm in smoothed]

    # 孤立突跳：该帧异常但相邻（该特征序列内）帧均正常 -> 疑似跟踪异常/数据突跳
    n = len(abnormal)
    spikes: List[int] = []
    for i in range(n):
        if not abnormal[i]:
            continue
        left_ab = abnormal[i - 1] if i > 0 else False
        right_ab = abnormal[i + 1] if i < n - 1 else False
        if not left_ab and not right_ab:
            spikes.append(points[i]["frame_idx"])

    events_raw = _merge_events(abnormal, sampled)
    events = [e for e in events_raw if e["n_frames"] >= min_event_frames]
    return {
        "smoothed": smoothed,
        "baseline": baseline,
        "abnormal": abnormal,
        "spikes": spikes,
        "events": events,
    }


def detect_changes(
    frames: List[Dict[str, Any]],
    config: Optional[EventConfig] = None,
    source: Optional[Dict[str, Any]] = None,
    is_mock: bool = False,
) -> EventDetectionOutput:
    """从逐帧 V2 结果中检测变化事件与数据质量风险。

    参数:
        frames: 逐帧记录列表，至少含 frame_idx/timestamp_ms/detected/keypoint_stats/features。
                可直接取自 /tmp/pose_result.json 的 frames（与 V2 VideoPoseOutput 兼容）。
        config: 可选检测参数；缺省用探索性默认值。
        source: 来源信息（mode/is_mock/video_path/fps 等），用于结果溯源。
        is_mock: 数据是否人工构造（真实视频恒为 False）。
    """
    cfg = config or EventConfig()
    # 打平特征序列（仅保留有效有限值），并按帧序稳定
    series: Dict[str, List[Dict[str, Any]]] = {k: [] for k in FEATURE_KEYS}
    for f in frames:
        feat = f.get("features") or {}
        for k in FEATURE_KEYS:
            v = feat.get(k)
            if v is not None:
                try:
                    vf = float(v)
                except (TypeError, ValueError):
                    vf = float("nan")
                if math.isfinite(vf):
                    series[k].append(
                        {"frame_idx": int(f["frame_idx"]), "timestamp_ms": float(f.get("timestamp_ms") or 0.0), "value": vf}
                    )
    # 稳定排序（防御：输入可能乱序）
    for k in series:
        series[k].sort(key=lambda p: p["frame_idx"])

    events: List[ChangeEvent] = []
    spike_anomalies: List[int] = []
    counts: Dict[str, Any] = {}
    for k in FEATURE_KEYS:
        thr = cfg.threshold_for(k)
        res = _analyze_feature(k, series[k], thr, cfg.smooth_window, cfg.min_event_frames)
        for e in res["events"]:
            events.append(
                ChangeEvent(
                    feature=k,
                    frame_start=e["frame_start"],
                    frame_end=e["frame_end"],
                    start_time_ms=e["start_time_ms"],
                    end_time_ms=e["end_time_ms"],
                    duration_ms=round(e["end_time_ms"] - e["start_time_ms"], 2),
                    n_frames=e["n_frames"],
                    deviation_max=e["deviation_max"],
                    swing=e["swing"],
                )
            )
        spike_anomalies.extend(res["spikes"])
        counts[k] = len(res["events"])
    events.sort(key=lambda e: (e.frame_start, e.feature))
    spike_anomalies = sorted(set(spike_anomalies))
    counts["total_events"] = len(events)
    counts["note"] = "total_events 为各特征事件数之和；同一时间段可能被多个特征同时标记。"

    # ---- 数据质量风险 ----
    low_vis: List[QualitySegment] = []
    undet_missing: List[int] = []
    # 低可见度片段（按 avg_visibility 低于阈值，帧相邻合并）
    vis_flags: List[bool] = []
    vis_frames: List[Dict[str, Any]] = []
    for f in frames:
        ks = f.get("keypoint_stats") or {}
        av = ks.get("avg_visibility")
        detected = bool(f.get("detected", True))
        missing = int(ks.get("missing", 0) or 0)
        degenerate = bool((f.get("features") or {}).get("degenerate", False))
        if not detected or missing > 0 or degenerate:
            undet_missing.append(int(f["frame_idx"]))
        vis_flags.append((av is not None and float(av) < cfg.visibility_threshold))
        vis_frames.append({"frame_idx": int(f["frame_idx"]), "timestamp_ms": float(f.get("timestamp_ms") or 0.0), "vis": float(av) if av is not None else 0.0})

    i = 0
    n = len(vis_flags)
    while i < n:
        if not vis_flags[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and vis_flags[j + 1] and vis_frames[j + 1]["frame_idx"] == vis_frames[j]["frame_idx"] + 1:
            j += 1
        grp = vis_frames[i: j + 1]
        low_vis.append(
            QualitySegment(
                frame_start=grp[0]["frame_idx"],
                frame_end=grp[-1]["frame_idx"],
                start_time_ms=grp[0]["timestamp_ms"],
                end_time_ms=grp[-1]["timestamp_ms"],
                reason="low_visibility",
                detail=round(min(g["vis"] for g in grp), 3),
            )
        )
        i = j + 1

    reasons: List[str] = []
    if low_vis:
        reasons.append(f"存在 {len(low_vis)} 段平均可见度低于 {cfg.visibility_threshold} 的片段")
    if undet_missing:
        reasons.append(f"存在 {len(undet_missing)} 帧未检出/缺失关键点/退化几何（帧号见 undetected_or_missing_frames）")
    if spike_anomalies:
        reasons.append(f"存在 {len(spike_anomalies)} 个孤立异常/疑似跟踪突跳帧（帧号见 spike_anomalies），需核对是否为遮挡或跟踪误差")

    review_required = bool(low_vis or undet_missing or spike_anomalies)

    return EventDetectionOutput(
        source=dict(source or {}),
        config=cfg,
        is_mock=bool(is_mock),
        event_count=counts,
        events=events,
        spike_anomalies=spike_anomalies,
        low_visibility_segments=low_vis,
        undetected_or_missing_frames=sorted(set(undet_missing)),
        review_required=review_required,
        review_reasons=reasons,
    )