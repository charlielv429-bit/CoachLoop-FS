"""MediaPipe Pose → KeypointFrame 纯映射的单元测试（无需 mediapipe，可在项目 .venv 运行）。"""
import os
import sys

import pytest

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from tools.video_analysis.mp_mapping import (  # noqa: E402
    POSE_LANDMARK_NAMES,
    build_keypoint_frame,
)
from tools.video_analysis.schemas import KeypointFrame  # noqa: E402


class FakeLM:
    """模拟 MediaPipe NormalizedLandmark。"""

    def __init__(self, x, y, z=None, visibility=None):
        self.x = x
        self.y = y
        self.z = z
        self.visibility = visibility


def test_names_length_33():
    assert len(POSE_LANDMARK_NAMES) == 33
    assert POSE_LANDMARK_NAMES[11] == "left_shoulder"
    assert POSE_LANDMARK_NAMES[23] == "left_hip"
    assert POSE_LANDMARK_NAMES[25] == "left_knee"
    assert POSE_LANDMARK_NAMES[27] == "left_ankle"


def test_build_full_33_real():
    lms = [FakeLM(0.1 + i * 0.01, 0.2 + i * 0.01, z=0.0, visibility=0.9) for i in range(33)]
    kf = build_keypoint_frame(5, 16.6, lms, is_mock=False, source="real://mediapipe/clip.mp4")
    assert isinstance(kf, KeypointFrame)
    assert kf.is_mock is False
    assert kf.source.startswith("real://")
    assert len(kf.landmarks) == 33
    name_by_id = {lm.id: lm.name for lm in kf.landmarks}
    assert name_by_id[11] == "left_shoulder" and name_by_id[12] == "right_shoulder"
    assert name_by_id[25] == "left_knee" and name_by_id[27] == "left_ankle"
    assert kf.landmarks[0].x == pytest.approx(0.1)
    assert kf.landmarks[0].visibility == pytest.approx(0.9)
    # 几何依赖的膝/踝坐标能正确读回
    knee = next(lm for lm in kf.landmarks if lm.id == 25)
    ankle = next(lm for lm in kf.landmarks if lm.id == 27)
    assert knee.x == pytest.approx(0.1 + 25 * 0.01)
    assert ankle.x == pytest.approx(0.1 + 27 * 0.01)


def test_undetected_frame_empty():
    kf = build_keypoint_frame(0, 0.0, None)
    assert kf.landmarks == []
    assert kf.is_mock is False  # 真实路径缺检测时即空帧，不做伪造


def test_mock_flag_passthrough():
    kf = build_keypoint_frame(0, 0.0, None, is_mock=True, source="mock://test")
    assert kf.is_mock is True
    assert kf.source == "mock://test"


def test_z_and_visibility_optional():
    kf = build_keypoint_frame(0, 0.0, [FakeLM(0.5, 0.5)])
    assert kf.landmarks[0].z is None
    assert kf.landmarks[0].visibility is None