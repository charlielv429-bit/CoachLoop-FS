"""基于 MediaPipe Tasks API 的真实视频姿态提取。

⚠️ 本模块依赖 mediapipe + opencv，仅应在隔离环境 `.venv-video` 中运行，
不会被项目主 `.venv` 导入（也不从包 __init__ 导出）。

真实识别（MP4 → 33 关键点 → 特征）需满足以下前置，缺失时抛出
:class:`MissingPrerequisiteError`（本模块不擅自下载模型或安装系统库）：
  1. 获授权测试视频（video_path）
  2. pose_landmarker.task 模型文件（MediaPipe 不自带，需提供后放入 assets/models）
  3. MediaPipe tasks vision 运行时系统库（如 libEGL.so.1/libGL，缺失需单独批准）

本模块不做动作评价、不设阈值、不判断用刃/重心/动作好坏。
"""
import os
from typing import Any, Dict, List, Optional

import cv2
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    PoseLandmarker,
    PoseLandmarkerOptions,
    RunningMode,
)
from pydantic import BaseModel, Field

from .features import process_keypoint_dataset
from .mp_mapping import build_keypoint_frame
from .schemas import FeatureResult, KeypointDataset, KeypointFrame

DEFAULT_MODEL_PATH = os.path.join(
    os.getenv("COZE_WORKSPACE_PATH", ""), "assets", "models", "pose_landmarker_lite.task"
)


class MissingPrerequisiteError(RuntimeError):
    """缺少视频 / 模型文件 / 系统库等真实识别前置条件。"""


class VideoFrameRecord(BaseModel):
    """单帧视频结果：检测状态 + 关键点统计 + 可观测特征。"""
    frame_idx: int = Field(..., description="帧序号")
    timestamp_ms: float = Field(..., description="时间戳（毫秒）")
    detected: bool = Field(..., description="本帧是否检出人体姿态（false=未检出，保留帧但标记，不做插值冒充）")
    keypoint_stats: Dict[str, Any] = Field(default={}, description="关键点质量统计（观测信息，非评价）")
    features: FeatureResult = Field(..., description="复用姿态特征计算模块的可观测特征")


class VideoPoseOutput(BaseModel):
    """整段视频处理结果。"""
    source: Dict[str, Any] = Field(..., description="来源信息：mode=real / is_mock=false / model=mediapipe_pose")
    keypoints: List[KeypointFrame] = Field(default_factory=list, exclude=True, description="供显式本地适配器取用的原始观测关键点；通用序列化不导出，不插值")
    frames: List[VideoFrameRecord] = Field(..., description="逐帧结果")
    summary: Dict[str, Any] = Field(default={}, description="观测统计，含有效帧比例（valid_frame_ratio）；非评分")
    errors: List[str] = Field(default=[], description="处理错误或告警")
    reserved_coach_review: Dict[str, Any] = Field(
        default_factory=lambda: {
            "review_status": "pending",
            "needs_coach_review": True,
            "coach_notes": "",
            "coach_verdict": None,
        },
        description="预留教练审核字段（本版一律 pending）",
    )


def _marker_options(model_path: str) -> PoseLandmarkerOptions:
    return PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=model_path),
        running_mode=RunningMode.VIDEO,
        num_poses=1,
    )


def _as_obstacle(exc: BaseException, what: str) -> MissingPrerequisiteError:
    msg = str(exc)
    if any(tag in msg for tag in ("libEGL", "libGL", ".so.1", "gl context", "EGL")):
        return MissingPrerequisiteError(
            f"MediaPipe vision 运行时缺少系统库：{msg}（需 libEGL/libGL 等，属系统环境前置，需单独批准安装）"
        )
    return MissingPrerequisiteError(f"{what}: {msg}")


def extract_video_pose(
    video_path: str,
    side: str = "left",
    max_frames: Optional[int] = None,
    model_path: str = DEFAULT_MODEL_PATH,
    include_keypoints: bool = False,
) -> VideoPoseOutput:
    """从 MP4 提取每帧人体关键点并复用 extract_features 计算可观测特征。

    参数:
        video_path: 授权测试视频路径。
        side: 判定腿/支撑腿一侧（left/right），默认 left。
        max_frames: 可选，最多处理帧数。
        model_path: pose_landmarker.task 的路径。
        include_keypoints: 仅显式本地适配器取用原始观测，通用序列化仍排除此字段。
    异常:
        MissingPrerequisiteError: 视频/模型/系统库任一前置缺失。
    """
    if not os.path.exists(video_path):
        raise MissingPrerequisiteError(f"视频文件不存在: {video_path}")
    if not os.path.exists(model_path):
        raise MissingPrerequisiteError(f"缺少 pose_landmarker.task 模型文件: {model_path}")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        cap.release()
        raise MissingPrerequisiteError(f"无法打开视频: {video_path}")
    fps: float = cap.get(cv2.CAP_PROP_FPS) or 30.0

    try:
        landmarker = PoseLandmarker.create_from_options(_marker_options(model_path))
    except Exception as exc:  # noqa: BLE001 - 统一转为可读前置错误
        cap.release()
        raise _as_obstacle(exc, "PoseLandmarker 初始化失败") from exc

    frames: List[KeypointFrame] = []
    detected_flags: list = []
    errors: List[str] = []
    idx = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if max_frames is not None and idx >= max_frames:
                break
            ts: int = int((idx / fps) * 1000.0)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            try:
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                result = landmarker.detect_for_video(mp_image, ts)
            except Exception as exc:  # noqa: BLE001
                if any(tag in str(exc) for tag in ("libEGL", "libGL", ".so.1", "gl context")):
                    raise _as_obstacle(exc, "帧处理失败") from exc
                errors.append(f"frame {idx}: {exc}")
                frames.append(build_keypoint_frame(idx, float(ts), None, source=f"real://mediapipe/{os.path.basename(video_path)}"))
                detected_flags.append(False)
                idx += 1
                continue
            pose_lms = result.pose_landmarks[0] if (result.pose_landmarks and len(result.pose_landmarks) > 0) else None
            detected: bool = pose_lms is not None
            frames.append(
                build_keypoint_frame(
                    idx,
                    float(ts),
                    pose_lms,
                    is_mock=False,
                    source=f"real://mediapipe/{os.path.basename(video_path)}",
                )
            )
            detected_flags.append(detected)
            idx += 1
    finally:
        cap.release()
        landmarker.close()

    dataset = KeypointDataset(
        is_mock=False,
        model="mediapipe_pose",
        source=f"real://mediapipe/{os.path.basename(video_path)}",
        fps=fps,
        frames=frames,
    )
    processed = process_keypoint_dataset(dataset, side=side)

    video_records: List[VideoFrameRecord] = []
    for rec, det in zip(processed.frames, detected_flags):
        video_records.append(
            VideoFrameRecord(
                frame_idx=rec.frame_idx,
                timestamp_ms=rec.timestamp_ms if rec.timestamp_ms is not None else 0.0,
                detected=det,
                keypoint_stats=rec.keypoint_stats,
                features=rec.features,
            )
        )

    total = len(frames)
    det_cnt = sum(1 for d in detected_flags if d)
    summary: Dict[str, Any] = dict(processed.summary)
    summary.update(
        {
            "source_frames": total,
            "detected_frames": det_cnt,
            "valid_frame_ratio": round(det_cnt / total, 4) if total else 0.0,
        }
    )

    source: Dict[str, Any] = {
        "mode": "real",
        "is_mock": False,
        "model": "mediapipe_pose",
        "video_path": video_path,
        "fps": round(fps, 3) if fps else None,
    }
    return VideoPoseOutput(
        source=source,
        keypoints=frames if include_keypoints else [],
        frames=video_records,
        summary=summary,
        errors=processed.errors + errors,
        reserved_coach_review=processed.reserved_coach_review,
    )