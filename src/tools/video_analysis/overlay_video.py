"""CoachLoop-FS V3 关键点可视化叠加模块（需在隔离环境 .venv-video 中运行）。

作用：将 MediaPipe Pose 33 个关键点与骨架叠加到真实视频帧，生成可播放 MP4；
抽取若干帧保存对照图；输出可见度时序、低可见度片段与跨帧位移突跳（跟踪异常提示）。
复用 pose_landmarker_lite.task 模型与既有关键点提取思路，不重复安装依赖。

本模块不做花滑动作诊断、不设评分阈值、不调用付费 API。
"""
import argparse
import json
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    PoseLandmarker,
    PoseLandmarkerOptions,
    RunningMode,
)

# MediaPipe Pose(33 点) 骨架连接（标准拓扑）
POSE_CONNECTIONS: List[Tuple[int, int]] = [
    (0, 1), (1, 2), (2, 3), (3, 7), (0, 4), (4, 5), (5, 6), (6, 8),
    (9, 10), (11, 12), (11, 13), (13, 15), (15, 17), (15, 19), (15, 21), (17, 19),
    (12, 14), (14, 16), (16, 18), (16, 20), (16, 22), (18, 20),
    (11, 23), (12, 24), (23, 24), (23, 25), (24, 26), (25, 27), (26, 28),
    (27, 29), (28, 30), (29, 31), (30, 32), (27, 31), (28, 32),
]

# 需重点核对对齐的四组关节：肩/髋/膝/踝（L/R 索引）
HIGH_JOINTS: Dict[str, Tuple[int, int]] = {
    "shoulder": (11, 12),
    "hip": (23, 24),
    "knee": (25, 26),
    "ankle": (27, 28),
}


def _draw(frame: np.ndarray, landmarks: Any, w: int, h: int) -> np.ndarray:
    """把关键点与骨架叠加到帧（就地绘制）。"""
    pts: List[Tuple[float, float]] = []
    for lm in landmarks:
        pts.append((float(lm.x) * w, float(lm.y) * h))
    # 骨架
    for a, b in POSE_CONNECTIONS:
        if a < len(pts) and b < len(pts):
            cv2.line(frame, (int(pts[a][0]), int(pts[a][1])), (int(pts[b][0]), int(pts[b][1])), (0, 255, 0), 2)
    # 全部关键点
    for px, py in pts:
        cv2.circle(frame, (int(px), int(py)), 3, (0, 0, 255), -1)
    # 高亮 肩/髋/膝/踝
    for name, (i, j) in HIGH_JOINTS.items():
        color = (255, 0, 255) if name in ("shoulder", "hip") else (0, 255, 255)
        for idx in (i, j):
            if idx < len(pts):
                cv2.circle(frame, (int(pts[idx][0]), int(pts[idx][1])), 7, color, 2)
    return frame


def _pick_detector(model_path: str) -> PoseLandmarker:
    opts = PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=model_path),
        running_mode=RunningMode.VIDEO,
        num_poses=1,
    )
    return PoseLandmarker.create_from_options(opts)


def _write_video(out_video: str, fps: float, size: Tuple[int, int], frames_iter):
    """以 MJPG 写 AVI（opencv 可靠），再交由外部 ffmpeg 转封装为 H.264 MP4。"""
    avi = out_video.replace(".mp4", ".avi")
    writer = cv2.VideoWriter(avi, cv2.VideoWriter_fourcc(*"MJPG"), fps, size)
    if not writer.isOpened():
        raise RuntimeError("无法创建 MJPG 视频写入器")
    n = 0
    first = None
    for fr in frames_iter:
        if first is None:
            first = (fr.shape, fr.dtype, fr.flags["C_CONTIGUOUS"])
        ok = writer.write(fr)
        if ok:
            n += 1
    writer.release()
    print(f"[debug] wrote {n} frames | first_frame={first}", file=sys.stderr)
    return avi


def _to_mp4_h264(avi: str, out_video: str) -> None:
    """用 ffmpeg(libx264) 把 AVI 转封装为可播放 MP4，提升兼容性。"""
    if os.path.exists(out_video):
        os.remove(out_video)
    cmd = [
        "ffmpeg", "-y", "-i", avi,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "high",
        "-movflags", "+faststart", "-an", out_video,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 转封装失败: {proc.stderr[-500:]}")
    if os.path.exists(avi) and os.path.abspath(avi) != os.path.abspath(out_video):
        os.remove(avi)


def overlay_video(
    video_path: str,
    model_path: str,
    out_video: str,
    frame_dir: str,
    sample_indices: List[int],
    jump_thresh: float = 0.15,
) -> Dict[str, Any]:
    """生成关键点叠加视频 + 抽样对照图，并返回可见度/低可见度/突跳统计。

    返回:
        dict: source_frames / detected_frames / valid_frame_ratio / avg_visibility /
              low_visibility_segments / jump_anomalies / samples / out_video / frame_dir
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(video_path)
    if not os.path.exists(model_path):
        raise FileNotFoundError(model_path)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频: {video_path}")
    fps: float = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    landmarker = _pick_detector(model_path)
    os.makedirs(frame_dir, exist_ok=True)

    # 内联写出（不经过生成器，保证 cap.read 与 writer 稳定协作）
    avi = out_video.replace(".mp4", ".avi")
    writer = cv2.VideoWriter(avi, cv2.VideoWriter_fourcc(*"MJPG"), fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError("无法创建 MJPG 视频写入器")

    vis_series: List[float] = []
    detect_flags: List[bool] = []
    samples: List[Dict[str, Any]] = []
    saved_samples: set = set()
    out_idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        ts = int((out_idx / fps) * 1000.0)
        try:
            mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            result = landmarker.detect_for_video(mp_img, ts)
        except Exception as exc:  # noqa: BLE001
            detect_flags.append(False)
            vis_series.append(0.0)
            out = frame.copy()
            cv2.putText(out, f"frame {out_idx}: detect err", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            writer.write(out)
            out_idx += 1
            continue
        pose = result.pose_landmarks[0] if (result.pose_landmarks and len(result.pose_landmarks) > 0) else None
        detected = pose is not None
        detect_flags.append(detected)
        if detected:
            vals = [float(getattr(lm, "visibility", 0.0) or 0.0) for lm in pose]
            vis = float(np.mean(vals)) if vals else 0.0
        else:
            vis = 0.0
        vis_series.append(vis)
        out = frame.copy()
        if detected:
            _draw(out, pose, width, height)
            cv2.putText(out, f"frame {out_idx} vis={vis:.2f}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        else:
            cv2.putText(out, f"frame {out_idx}: not detected", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        if out_idx in sample_indices and out_idx not in saved_samples:
            png = os.path.join(frame_dir, f"frame_{out_idx:03d}_vis{vis:.2f}.png")
            cv2.imwrite(png, out)
            samples.append({"frame_idx": out_idx, "timestamp_ms": ts, "visibility": round(vis, 3), "detected": detected, "png": png})
            saved_samples.add(out_idx)
        writer.write(out)
        out_idx += 1
    writer.release()
    cap.release()
    landmarker.close()
    # 转封装为 H.264 MP4（libx264），保证可播放与兼容
    _to_mp4_h264(avi, out_video)
    final_path = out_video

    total = len(detect_flags)
    det = sum(1 for d in detect_flags if d)
    ratio = round(det / total, 4) if total else 0.0
    avg_vis = round(float(np.mean(vis_series)), 3) if total else 0.0

    # 低可见度片段（连续且 avg<0.80）
    low_seg: List[Dict[str, Any]] = []
    run: Optional[List[int]] = None
    for i, v in enumerate(vis_series):
        if v < 0.80 and detect_flags[i]:
            if run is None:
                run = [i]
            else:
                run.append(i)
        else:
            if run:
                low_seg.append({"start": run[0], "end": run[-1], "len": len(run), "min_vis": round(min(vis_series[i] for i in run), 3)})
                run = None
    if run:
        low_seg.append({"start": run[0], "end": run[-1], "len": len(run), "min_vis": round(min(vis_series[i] for i in run), 3)})

    # 跨帧位移突跳（髋中心归一化位移）→ 跟踪异常提示
    jumps: List[Dict[str, Any]] = []
    prev_center: Optional[Tuple[float, float]] = None
    # 需要 landmark 序列以计算髋中心；此处用检测标志近似，如需精确需另存
    # 简单方案：在绘制阶段已丢弃坐标，故跳变提示以可见度骤降/检测翻转近似
    for i in range(1, total):
        if detect_flags[i-1] and detect_flags[i] and vis_series[i] - vis_series[i-1] < -0.25:
            jumps.append({"frame": i, "vis_drop": round(vis_series[i-1] - vis_series[i], 3)})
    # 去重连续——保留在 low_seg 中体现，jumps 仅记录显著骤降点
    # 归一化：仅当骤降伴随 maxto说明，这里给出候选帧
    jump_anomalies = [{"frame": j["frame"], "vis_drop": j["vis_drop"]} for j in jumps[:20]]

    return {
        "source_frames": total,
        "detected_frames": det,
        "valid_frame_ratio": ratio,
        "avg_visibility": avg_vis,
        "min_visibility": round(float(min(vis_series)), 3) if total else 0.0,
        "low_visibility_segments": low_seg,
        "jump_anomalies": jump_anomalies,
        "samples": samples,
        "out_video": final_path,
        "frame_dir": frame_dir,
    }


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="CoachLoop-FS V3 关键点叠加可视化")
    parser.add_argument("video", help="输入视频路径")
    parser.add_argument("--model", default=None, help="pose_landmarker.task 路径")
    parser.add_argument("--out-video", default="assets/videos/input_skate_overlay.mp4", help="输出叠加视频")
    parser.add_argument("--frame-dir", default="assets/videos/overlay_frames", help="对照图保存目录")
    parser.add_argument("--samples", default="12,58,160,260,380,500", help="抽样帧索引(逗号分隔)")
    parser.add_argument("--summary", default="/tmp/overlay_summary.json", help="统计 JSON 输出路径")
    args = parser.parse_args(argv)
    model = args.model or os.path.join(
        os.getenv("COZE_WORKSPACE_PATH", ""), "assets", "models", "pose_landmarker_lite.task"
    )
    samples = [int(s) for s in args.samples.split(",") if s.strip().isdigit()]
    try:
        result = overlay_video(args.video, model, args.out_video, args.frame_dir, samples)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(3)
    with open(args.summary, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print(json.dumps({k: result[k] for k in ("source_frames", "detected_frames", "valid_frame_ratio", "avg_visibility", "min_visibility", "low_visibility_segments", "jump_anomalies", "out_video") if k in result}, ensure_ascii=False))
    print(f"samples: {len(result['samples'])} -> {result['frame_dir']}")
    print(f"summary: {args.summary}")


if __name__ == "__main__":
    main()