"""CoachLoop-FS 视频分析模块（姿态特征计算）单元测试。

覆盖：纯几何函数、JSON 读取/校验、逐帧特征提取、缺失/退化/异常数据处理、
结构化 JSON 输出。均为逻辑测试，不依赖任何外部服务。
"""
import math
import os
import sys

import pytest

# 将项目 src 加入 PYTHONPATH（与运行环境一致：COZE_WORKSPACE_PATH + /src）
_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from tools.video_analysis.geometry import (  # noqa: E402
    DegenerateGeometryError,
    angle_at_vertex,
    hip_ankle_offset_norm,
    knee_angle_2d,
    torso_pitch_deg,
)
from tools.video_analysis.keypoint_io import (  # noqa: E402
    KeypointValidationError,
    read_keypoint_json,
)
from tools.video_analysis.schemas import (  # noqa: E402
    KeypointDataset,
    KeypointFrame,
    Landmark,
)
from tools.video_analysis.features import process_keypoint_dataset, extract_features  # noqa: E402

MOCK_PATH = os.path.join(_ROOT, "assets", "mock", "pose_keypoints_mock.json")

EPS = 1e-3


# ---------------- 纯几何函数 ----------------
class TestGeometry:
    def test_angle_right_angle(self):
        # 顶点 b=(0,1)，臂到 a=(0,0) 与 c=(1,1)：应为 90 度
        assert abs(angle_at_vertex((0, 0), (0, 1), (1, 1)) - 90.0) < EPS

    def test_knee_angle_straight(self):
        # 髋(0,0) 膝(0,1) 踝(0,2)：180 度
        assert abs(knee_angle_2d((0, 0), (0, 1), (0, 2)) - 180.0) < EPS

    def test_knee_angle_bent(self):
        # 髋(0,0) 膝(1,1) 踝(2,2) 共线应 180；构造 90 度屈膝：
        # 髋(0,0) 膝(0,1) 踝(-1,1)
        assert abs(knee_angle_2d((0, 0), (0, 1), (-1, 1)) - 90.0) < EPS

    def test_torso_vertical(self):
        # 肩中点(0,1) 髋中点(0,2)：与竖直(0,1)夹角 0
        assert abs(torso_pitch_deg((0, 1), (0, 2)) - 0.0) < EPS

    def test_torso_lean_45(self):
        # 肩中点(0,0)，髋中点(1,1)：躯干轴(1,1)与竖直(0,1)夹角 45 度
        assert abs(torso_pitch_deg((0, 0), (1, 1)) - 45.0) < EPS

    def test_hip_ankle_offset(self):
        # 髋中点(1,1)，踝(0,2)：腿长 sqrt2，水平偏移 1 => 1/sqrt2≈0.707
        assert abs(hip_ankle_offset_norm((1, 1), (0, 2)) - (1.0 / math.sqrt(2.0))) < EPS

    def test_degenerate_raises(self):
        with pytest.raises(DegenerateGeometryError):
            knee_angle_2d((0, 0), (0, 0), (1, 1))  # 膝与髋重合 -> 零长度腿
        with pytest.raises(DegenerateGeometryError):
            torso_pitch_deg((0.5, 0.5), (0.5, 0.5))  # 肩髋重合 -> 零长度躯干


# ---------------- JSON 读取与校验 ----------------
class TestKeypointIO:
    def test_read_mock_json(self):
        ds = read_keypoint_json(MOCK_PATH)
        assert isinstance(ds, KeypointDataset)
        assert ds.is_mock is True
        assert ds.source.startswith("mock://")
        assert len(ds.frames) == 4

    def test_reject_non_mock(self):
        import json
        import tempfile

        data = {
            "is_mock": False,
            "source": "real://mediapipe/xxx",
            "model": "mock-geometry",
            "frames": [],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            json.dump(data, fh)
            path = fh.name
        try:
            with pytest.raises(KeypointValidationError, match="is_mock 必须为 true"):
                read_keypoint_json(path)
        finally:
            os.unlink(path)

    def test_reject_without_source(self):
        import json
        import tempfile

        data = {"is_mock": True, "source": "", "model": "mock-geometry", "frames": []}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            json.dump(data, fh)
            path = fh.name
        try:
            with pytest.raises(KeypointValidationError, match="source"):
                read_keypoint_json(path)
        finally:
            os.unlink(path)

    def test_reject_non_mock_model(self):
        import json
        import tempfile

        data = {
            "is_mock": True,
            "source": "mock://x",
            "model": "mediapipe_pose",  # 冒充真实识别结果 -> 拒绝
            "frames": [],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            json.dump(data, fh)
            path = fh.name
        try:
            with pytest.raises(KeypointValidationError, match="model 标注不支持"):
                read_keypoint_json(path)
        finally:
            os.unlink(path)


# ---------------- 特征提取与缺失/退化处理 ----------------
_IDS = {"left_shoulder": 11, "right_shoulder": 12, "left_hip": 23, "right_hip": 24,
        "left_knee": 25, "right_knee": 26, "left_ankle": 27, "right_ankle": 28}


def _lm(name, x, y):
    return Landmark(id=_IDS[name], name=name, x=x, y=y, visibility=1.0)


def _frame(points):
    return KeypointFrame(frame_idx=0, timestamp_ms=0.0, is_mock=True,
                         source="mock://test", landmarks=[_lm(n, x, y) for n, x, y in points])


class TestFeatures:
    def test_healthy_frame(self):
        # 侧视角基本姿态：屈膝
        pts = [
            ("left_shoulder", 0.48, 0.30), ("right_shoulder", 0.52, 0.30),
            ("left_hip", 0.50, 0.55), ("right_hip", 0.54, 0.55),
            ("left_knee", 0.62, 0.70), ("left_ankle", 0.47, 0.92),
        ]
        feat = extract_features(_frame(pts))
        # 膝角应显著小于 180（屈膝），且为可计算浮点值
        assert feat.knee_angle_deg is not None
        assert 0.0 < feat.knee_angle_deg < 180.0
        assert feat.torso_pitch_deg is not None and feat.torso_pitch_deg >= 0.0
        assert feat.hip_ankle_offset_norm is not None
        assert feat.missing_required == []
        assert feat.degenerate is False

    def test_missing_knee_ankle(self):
        pts = [
            ("left_shoulder", 0.48, 0.30), ("right_shoulder", 0.52, 0.30),
            ("left_hip", 0.50, 0.55), ("right_hip", 0.54, 0.55),
            # 缺 left_knee 与 left_ankle
        ]
        feat = extract_features(_frame(pts))
        assert feat.knee_angle_deg is None
        assert feat.hip_ankle_offset_norm is None
        assert "left_knee" in feat.missing_required
        assert "left_ankle" in feat.missing_required
        # 躯干仍可计算
        assert feat.torso_pitch_deg is not None

    def test_degenerate_zero_length_knee(self):
        pts = [
            ("left_shoulder", 0.48, 0.30), ("right_shoulder", 0.52, 0.30),
            ("left_hip", 0.50, 0.72), ("right_hip", 0.54, 0.72),
            ("left_knee", 0.50, 0.72),  # 膝与髋重合
            ("left_ankle", 0.47, 0.92),
        ]
        feat = extract_features(_frame(pts))
        assert feat.knee_angle_deg is None
        assert feat.degenerate is True
        assert "knee" in feat.degeneracy_reason

    def test_abnormal_nan_treated_missing(self):
        pts = [
            ("left_shoulder", 0.48, 0.30), ("right_shoulder", 0.52, 0.30),
            ("left_hip", 0.50, 0.55), ("right_hip", 0.54, 0.55),
            ("left_knee", math.nan, 0.70),  # NaN 视为缺失
            ("left_ankle", 0.47, 0.92),
        ]
        feat = extract_features(_frame(pts))
        assert feat.knee_angle_deg is None
        assert "left_knee" in feat.missing_required

    def test_invalid_side_raises(self):
        with pytest.raises(ValueError):
            extract_features(_frame([("left_shoulder", 0.0, 0.0)]), side="center")


# ---------------- 整体处理与结构化 JSON 输出 ----------------
class TestPipeline:
    def test_process_dataset_from_file(self):
        ds = read_keypoint_json(MOCK_PATH)
        out = process_keypoint_dataset(ds, side="left")
        assert out.source["is_mock"] is True
        assert out.source["mode"] == "mock"
        assert out.source["source"].startswith("mock://")
        assert len(out.frames) == 4
        # f0 正常计算出膝角
        assert out.frames[0].features.knee_angle_deg is not None
        # f2 缺膝/踝 -> 膝角为 None 且记录缺失
        assert out.frames[2].features.knee_angle_deg is None
        # f3 膝髋重合 -> 退化
        assert out.frames[3].features.degenerate is True
        # 教练审核字段预留且不填判定
        assert out.reserved_coach_review["review_status"] == "pending"
        assert out.reserved_coach_review["coach_verdict"] is None

    def test_json_output_is_structured(self, tmp_path):
        ds = read_keypoint_json(MOCK_PATH)
        out = process_keypoint_dataset(ds, side="left")
        payload = out.model_dump_json()
        import json as _json

        parsed = _json.loads(payload)
        assert parsed["source"]["is_mock"] is True
        assert parsed["source"]["model"] == "mock-geometry"
        assert "frames" in parsed and "summary" in parsed and "errors" in parsed
        assert "reserved_coach_review" in parsed

        out_path = tmp_path / "out.json"
        out_path.write_text(payload, encoding="utf-8")
        assert out_path.exists()