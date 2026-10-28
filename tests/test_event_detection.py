"""CoachLoop-FS V4-MVP 事件检测模块单元测试。

覆盖：无事件、连续事件合并、低质量帧（可见度/缺失）标记 review_required、
缺失特征（None）时的稳健处理、孤立突跳标记。均为纯逻辑测试，不依赖外部服务。
"""
import os
import sys

import pytest

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from tools.video_analysis.event_detection import (  # noqa: E402
    EventConfig,
    detect_changes,
)


def _frame(fi, ts, knee=None, torso=None, hip=None, detected=True, vis=None, missing=0, degenerate=False):
    return {
        "frame_idx": fi,
        "timestamp_ms": ts,
        "detected": detected,
        "keypoint_stats": {"avg_visibility": vis, "missing": missing},
        "features": {
            "knee_angle_deg": knee,
            "torso_pitch_deg": torso,
            "hip_ankle_offset_norm": hip,
            "degenerate": degenerate,
        },
    }


def _mk(n, build):
    """构造 n 帧序列，build(fi, ts)->组装帧参数。"""
    frames = []
    for fi in range(n):
        frames.append(build(fi, round(fi * 33.33, 2)))
    return frames


def _steady(n=40, knee=170.0, torso=3.0, hip=0.0, vis=0.9):
    return _mk(
        n,
        lambda fi, ts: _frame(fi, ts, knee=knee + (-0.5 if fi % 3 == 0 else 0.3),
                               torso=torso + (-0.2 if fi % 2 == 0 else 0.1),
                               hip=hip + (-0.01 if fi % 4 == 0 else 0.0),
                               vis=vis),
    )


class TestNoEvents:
    def test_steady_track_no_events(self):
        out = detect_changes(_steady(40), source={"mode": "real", "is_mock": False})
        assert out.is_mock is False
        assert out.event_count["total_events"] == 0
        assert out.events == []
        assert out.review_required is False
        assert out.spike_anomalies == []


class TestEventMerge:
    def test_consecutive_abnormal_frames_merge_into_single_event(self):
        # 帧 8-12 膝角显著偏离基线，属同一连续变化事件，应合并为一个事件
        def build(fi, ts):
            knee = 145.0 if 8 <= fi <= 12 else 170.0
            return _frame(fi, ts, knee=knee, torso=3.0, hip=0.0, vis=0.9)

        out = detect_changes(_mk(40, build), source={"mode": "real", "is_mock": False})
        knee_events = [e for e in out.events if e.feature == "knee_angle_deg"]
        assert len(knee_events) == 1, f"期望合并为 1 个事件，实际 {len(knee_events)}"
        ev = knee_events[0]
        assert 8 <= ev.frame_start
        assert ev.frame_end <= 12
        assert ev.frame_end >= ev.frame_start
        assert ev.n_frames >= 1
        assert ev.duration_ms >= 0.0
        assert ev.deviation_max > 0.0
        # 不应出现重复计数：事件之间不重叠、按开始帧升序
        assert out.event_count["knee_angle_deg"] == 1

    def test_two_separate_events_not_merged(self):
        # 帧 5-7 与 20-22 两段变化被正常帧隔开 -> 两个事件
        def build(fi, ts):
            knee = 145.0 if (5 <= fi <= 7 or 20 <= fi <= 22) else 170.0
            return _frame(fi, ts, knee=knee, torso=3.0, hip=0.0, vis=0.9)

        out = detect_changes(_mk(40, build), source={"mode": "real", "is_mock": False})
        knee_events = [e for e in out.events if e.feature == "knee_angle_deg"]
        assert len(knee_events) == 2
        assert knee_events[0].frame_start == 5 and knee_events[0].frame_end == 7
        assert knee_events[1].frame_start == 20 and knee_events[1].frame_end == 22


class TestLowQualityFrames:
    def test_low_visibility_and_missing_set_review_required(self):
        frames = _steady(20, vis=0.9)
        frames[6]["keypoint_stats"]["avg_visibility"] = 0.60  # 低可见度
        frames[12]["keypoint_stats"]["missing"] = 5           # 缺失关键点
        frames[14]["detected"] = False                        # 未检出
        out = detect_changes(frames, source={"mode": "real", "is_mock": False})
        assert out.review_required is True
        assert any(s.reason == "low_visibility" for s in out.low_visibility_segments)
        assert 12 in out.undetected_or_missing_frames
        assert 14 in out.undetected_or_missing_frames
        assert len(out.review_reasons) >= 1

    def test_low_visibility_segments_merged(self):
        frames = _steady(20, vis=0.9)
        for fi in (5, 6, 7):
            frames[fi]["keypoint_stats"]["avg_visibility"] = 0.65
        out = detect_changes(frames, source={"mode": "real", "is_mock": False})
        low = [s for s in out.low_visibility_segments if s.reason == "low_visibility"]
        assert len(low) == 1
        assert low[0].frame_start == 5 and low[0].frame_end == 7


class TestMissingFeatures:
    def test_none_feature_does_not_crash(self):
        # knee 特征在某些帧缺失（None），其余特征仍正常参与检测
        def build(fi, ts):
            knee = 150.0 if (10 <= fi <= 12) else (170.0 if fi % 2 == 0 else None)
            return _frame(fi, ts, knee=knee, torso=2.0, hip=0.0, vis=0.9)

        out = detect_changes(_mk(30, build), source={"mode": "real", "is_mock": False})
        # 不应崩溃；torso/hip 恒定 -> 无 torso/hip 事件
        assert out.event_count["torso_pitch_deg"] == 0
        assert out.event_count["hip_ankle_offset_norm"] == 0
        # knee 存在有效值的帧仍可产生事件
        assert isinstance(out.events, list)

    def test_all_features_empty_is_safe(self):
        frames = [_frame(i, i * 33.33, knee=None, torso=None, hip=None, vis=0.9) for i in range(10)]
        out = detect_changes(frames, source={"mode": "real", "is_mock": False})
        assert out.event_count["total_events"] == 0
        assert out.events == []
        assert out.review_required is False


class TestCustomConfig:
    def test_strict_threshold_yields_no_events(self):
        # 阈值调大后，本应触发的变化不再触发
        def build(fi, ts):
            knee = 150.0 if 5 <= fi <= 7 else 170.0
            return _frame(fi, ts, knee=knee, torso=3.0, hip=0.0, vis=0.9)

        out = detect_changes(
            _mk(30, build),
            config=EventConfig(knee_threshold_deg=60.0),  # 远超 20 度偏离
            source={"mode": "real", "is_mock": False},
        )
        assert out.event_count["knee_angle_deg"] == 0