"""CoachLoop-FS V5-MVP 教练事件审核模块单元测试。

覆盖：审核状态合法性、稳定 event_id（可复现且不同事件唯一）、原始事件/来源
不被审核覆盖、审核结果可追溯（审计轨迹/审核人/时间/备注）。均为纯逻辑测试。
"""
import json
import os
import sys

import pytest

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from tools.video_analysis.event_review import (  # noqa: E402
    EventReviewOutput,
    VALID_REVIEW_STATUSES,
    apply_review,
    build_review_records,
    make_event_id,
    validate_status,
)


def _sample_detection(events=None):
    return {
        "source": {"mode": "real", "is_mock": False, "video_path": "assets/videos/input_skate.mp4", "fps": 30.0},
        "is_mock": False,
        "events": events or [
            {"feature": "knee_angle_deg", "frame_start": 41, "frame_end": 70,
             "start_time_ms": 1366.7, "end_time_ms": 2333.3, "duration_ms": 966.7,
             "n_frames": 30, "deviation_max": 16.228, "swing": 6.228},
            {"feature": "torso_pitch_deg", "frame_start": 260, "frame_end": 287,
             "start_time_ms": 8666.7, "end_time_ms": 9566.7, "duration_ms": 900.0,
             "n_frames": 28, "deviation_max": 11.68, "swing": 7.49},
        ],
    }


class TestStatusValidity:
    def test_valid_statuses_accepted(self):
        for s in VALID_REVIEW_STATUSES:
            assert validate_status(s) == s

    def test_invalid_status_rejected(self):
        with pytest.raises(ValueError, match="非法审核状态"):
            validate_status("wrong_status")


class TestStableEventId:
    def test_same_event_same_id(self):
        a = make_event_id("a.mp4", 41, 70, "knee_angle_deg")
        b = make_event_id("a.mp4", 41, 70, "knee_angle_deg")
        assert a == b and a.startswith("evt_")

    def test_distinct_events_distinct_id(self):
        assert make_event_id("a.mp4", 41, 70, "knee_angle_deg") != make_event_id(
            "a.mp4", 41, 70, "torso_pitch_deg"
        )
        assert make_event_id("a.mp4", 41, 70, "knee_angle_deg") != make_event_id(
            "a.mp4", 42, 70, "knee_angle_deg"
        )
        assert make_event_id("a.mp4", 41, 70, "knee_angle_deg") != make_event_id(
            "b.mp4", 41, 70, "knee_angle_deg"
        )


class TestBuildRecords:
    def test_all_pending_and_source_preserved(self):
        out = build_review_records(_sample_detection(), "/tmp/event_detection_result.json")
        assert out.generated_from == "/tmp/event_detection_result.json"
        assert out.is_mock is False
        assert len(out.records) == 2
        assert all(r.review_status.value == "pending" for r in out.records)
        assert all(r.review_history == [] for r in out.records)
        # 来源溯源保留
        assert out.source["video_path"] == "assets/videos/input_skate.mp4"
        assert out.records[0].source["fps"] == 30.0
        # 原始事件数据保留
        assert out.records[0].original_event["feature"] == "knee_angle_deg"
        assert out.records[0].original_event["frame_start"] == 41

    def test_summary_counts(self):
        out = build_review_records(_sample_detection(), "x.json").finalize()
        assert out.summary["total"] == 2
        assert out.summary["by_status"]["pending"] == 2
        assert out.summary["by_status"]["confirmed"] == 0


class TestOriginalDataNotOverwritten:
    def test_apply_keeps_original_event_unchanged(self):
        out = build_review_records(_sample_detection(), "x.json")
        rec = out.records[0]
        original_snapshot = dict(rec.original_event)
        source_snapshot = dict(rec.source)
        rec2 = apply_review(rec, "tracking_error", "coach_zhang", note="疑似跟踪误差")
        assert rec2 is rec
        # 原始数据与来源未被覆盖
        assert rec.original_event == original_snapshot
        assert rec.source == source_snapshot
        # 审核字段已更新
        assert rec.review_status.value == "tracking_error"
        assert rec.reviewed_by == "coach_zhang"
        assert rec.notes == "疑似跟踪误差"
        assert rec.reviewed_at is not None

    def test_apply_without_by_rejected(self):
        out = build_review_records(_sample_detection(), "x.json")
        with pytest.raises(ValueError, match="reviewed_by"):
            apply_review(out.records[0], "confirmed", "  ")


class TestTraceability:
    def test_audit_history_appended(self):
        out = build_review_records(_sample_detection(), "x.json")
        rec = out.records[0]
        apply_review(rec, "confirmed", "coach_li", reviewed_at="2024-01-01T00:00:01+00:00", note="确认是真实动作")
        apply_review(rec, "normal_movement", "coach_wang", reviewed_at="2024-01-01T00:00:02+00:00", note="复核后判定为常规动作")
        assert len(rec.review_history) == 2
        assert rec.review_history[0].status.value == "confirmed"
        assert rec.review_history[0].reviewed_by == "coach_li"
        assert rec.review_history[0].reviewed_at == "2024-01-01T00:00:01+00:00"
        assert rec.review_history[1].status.value == "normal_movement"
        assert rec.review_history[1].reviewed_by == "coach_wang"
        assert rec.review_history[1].reviewed_at == "2024-01-01T00:00:02+00:00"
        assert rec.review_status.value == "normal_movement"  # 最新状态生效
        assert rec.reviewed_by == "coach_wang"
        assert rec.reviewed_at == "2024-01-01T00:00:02+00:00"

    def test_serialize_roundtrip_preserves_trace(self, tmp_path):
        out = build_review_records(_sample_detection(), "x.json")
        apply_review(out.records[0], "uncertain", "coach_zhang", note="信息不足待补拍")
        payload = out.model_dump_json(indent=2, ensure_ascii=False)
        out2 = EventReviewOutput.model_validate(json.loads(payload))
        assert out2.records[0].review_status.value == "uncertain"
        assert out2.records[0].review_history[0].note == "信息不足待补拍"
        assert out2.records[0].original_event == out.records[0].original_event