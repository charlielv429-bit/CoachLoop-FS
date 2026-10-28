"""MediaPipe Pose 关键点 → 本模块 KeypointFrame 的纯映射。

不依赖 mediapipe，便于在项目 `.venv` 中做单元测试；真实关键点来自
MediaPipe 1.2 新版 tasks API 的 `NormalizedLandmark`（含 .x/.y/.z/.visibility）。
仅做结构转录，不做任何插值或伪装。
"""
from typing import Any, List, Optional

from .schemas import KeypointFrame, Landmark

# MediaPipe Pose 33 个关键点，顺序即索引 0..32（与几何模块所需 11/12/23/24/25/27 一致）
POSE_LANDMARK_NAMES: List[str] = [
    "nose",
    "left_eye_inner", "left_eye", "left_eye_outer",
    "right_eye_inner", "right_eye", "right_eye_outer",
    "left_ear", "right_ear",
    "mouth_left", "mouth_right",
    "left_shoulder", "right_shoulder",
    "left_elbow", "right_elbow",
    "left_wrist", "right_wrist",
    "left_pinky", "right_pinky",
    "left_index", "right_index",
    "left_thumb", "right_thumb",
    "left_hip", "right_hip",
    "left_knee", "right_knee",
    "left_ankle", "right_ankle",
    "left_heel", "right_heel",
    "left_foot_index", "right_foot_index",
]


def build_keypoint_frame(
    frame_idx: int,
    timestamp_ms: Optional[float],
    pose_landmarks: Any,
    is_mock: bool = False,
    source: str = "real://mediapipe",
) -> KeypointFrame:
    """将 MediaPipe 姿态结果转录为本模块 KeypointFrame。

    参数:
        pose_landmarks: 可迭代的 landmarks（元素含 .x/.y/.z/.visibility）。
            None 或空 -> 返回关键点列表为空、未检出的帧（真实缺失，不做插值）。
    返回:
        仅结构转录的 KeypointFrame；缺失即缺失，绝不生成伪造坐标。
    """
    landmarks: List[Landmark] = []
    if pose_landmarks is not None:
        for i, lm in enumerate(pose_landmarks):
            name = POSE_LANDMARK_NAMES[i] if i < len(POSE_LANDMARK_NAMES) else f"landmark_{i}"
            z = getattr(lm, "z", None)
            vis = getattr(lm, "visibility", None)
            landmarks.append(
                Landmark(
                    id=i,
                    name=name,
                    x=float(getattr(lm, "x", float("nan"))),
                    y=float(getattr(lm, "y", float("nan"))),
                    z=None if z is None else float(z),
                    visibility=None if vis is None else float(vis),
                )
            )
    return KeypointFrame(
        frame_idx=frame_idx,
        timestamp_ms=timestamp_ms,
        is_mock=is_mock,
        source=source,
        landmarks=landmarks,
    )