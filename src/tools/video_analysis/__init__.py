"""CoachLoop-FS 视频分析模块：姿态特征计算（仅 MOCK 关键点，非真实视频识别）。

本模块只做可观测几何量计算（膝角/躯干角/髋踝相对偏移），不做专业动作判定、
不设评价阈值、不推断重心/冰刀压力/内外刃使用。MOCK 数据必须带 is_mock=true 与来源标记。
"""

from .schemas import (
    Landmark,
    KeypointFrame,
    KeypointDataset,
    FeatureResult,
    FrameRecord,
    AnalysisOutput,
)
from .keypoint_io import read_keypoint_json, KeypointValidationError
from .features import extract_features, process_keypoint_dataset
from .geometry import DegenerateGeometryError
from .mp_mapping import POSE_LANDMARK_NAMES, build_keypoint_frame

__all__ = [
    "Landmark",
    "KeypointFrame",
    "KeypointDataset",
    "FeatureResult",
    "FrameRecord",
    "AnalysisOutput",
    "read_keypoint_json",
    "KeypointValidationError",
    "extract_features",
    "process_keypoint_dataset",
    "DegenerateGeometryError",
    "POSE_LANDMARK_NAMES",
    "build_keypoint_frame",
]