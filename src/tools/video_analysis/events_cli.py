"""V4-MVP 事件检测 CLI：复用 V2 pose_result，输出结构化 JSON 与简洁事件汇总。

仅在主 .venv 中运行（纯逻辑，不依赖 mediapipe/opencv）：
    .venv/bin/python -m tools.video_analysis.events_cli \
        --input /tmp/pose_result.json --output /tmp/event_detection_result.json

可选覆盖探索性阈值（--config 传入 JSON，或 --knee-threshold 等单个覆盖）。
"""
import argparse
import json
import sys
from typing import Any, Dict, List, Optional

from .event_detection import EventConfig, detect_changes

_DEFAULT_INPUT = "/tmp/pose_result.json"
_DEFAULT_OUTPUT = "/tmp/event_detection_result.json"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CoachLoop-FS V4-MVP 姿态变化事件检测（非评分/非诊断）")
    parser.add_argument("--input", default=_DEFAULT_INPUT, help="V2 pose_result JSON 路径")
    parser.add_argument("--output", "-o", default=_DEFAULT_OUTPUT, help="输出 JSON 路径")
    parser.add_argument("--config", default=None, help="可选：EventConfig JSON 路径（部分字段覆盖）")
    parser.add_argument("--knee-threshold", type=float, default=None, help="膝角偏离阈值（度）")
    parser.add_argument("--torso-threshold", type=float, default=None, help="躯干倾角偏离阈值（度）")
    parser.add_argument("--hip-ankle-threshold", type=float, default=None, help="髋踝偏移偏离阈值（归一化）")
    parser.add_argument("--smooth-window", type=int, default=None, help="平滑窗口（帧）")
    parser.add_argument("--print-summary", action="store_true", help="同时打印简洁事件汇总")
    return parser


def _load_config(args: argparse.Namespace) -> EventConfig:
    overrides: Dict[str, Any] = {}
    if args.config:
        with open(args.config, "r", encoding="utf-8") as fh:
            overrides.update(json.load(fh))
    mapping = {
        "knee_threshold_deg": args.knee_threshold,
        "torso_threshold_deg": args.torso_threshold,
        "hip_ankle_threshold_norm": args.hip_ankle_threshold,
        "smooth_window": args.smooth_window,
    }
    for key, val in mapping.items():
        if val is not None:
            overrides[key] = val
    return EventConfig(**overrides)


def _format_time(ms: float) -> str:
    s = ms / 1000.0
    return f"{s:.2f}s"


def _summary(out) -> str:
    ec = out.event_count
    lines: List[str] = [
        f"事件总数: {ec.get('total_events', 0)} (knee={ec.get('knee_angle_deg', 0)}, torso={ec.get('torso_pitch_deg', 0)}, "
        f"hip_ankle={ec.get('hip_ankle_offset_norm', 0)})",
        f"review_required: {out.review_required}",
    ]
    for e in out.events:
        lines.append(
            f"  [{e.feature}] 帧{e.frame_start}-{e.frame_end}  {_format_time(e.start_time_ms)}~{_format_time(e.end_time_ms)}  "
            f"时长{round(e.duration_ms / 1000.0, 2)}s  偏离{e.deviation_max} 摆幅{e.swing}"
        )
    if out.low_visibility_segments:
        lines.append("低可见度片段: " + ", ".join(
            f"{s.reason} 帧{s.frame_start}-{s.frame_end}(可见度{s.detail})" for s in out.low_visibility_segments
        ))
    if out.undetected_or_missing_frames:
        lines.append("未检出/缺失/退化帧: " + ",".join(str(f) for f in out.undetected_or_missing_frames))
    if out.spike_anomalies:
        lines.append("孤立异常/疑似跟踪突跳帧: " + ",".join(str(f) for f in out.spike_anomalies))
    if out.review_reasons:
        lines.append("复盘原因: " + "; ".join(out.review_reasons))
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    try:
        with open(args.input, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        print(f"[OBSTACLE] 输入文件不存在: {args.input}（V4 复用 V2 结果，不重新推理视频）", file=sys.stderr)
        return 4

    frames: List[Dict[str, Any]] = data.get("frames", [])
    if not frames:
        print("[OBSTACLE] 输入 JSON 无 frames", file=sys.stderr)
        return 4

    source: Dict[str, Any] = dict(data.get("source") or {})
    source.setdefault("input_json", args.input)
    source.setdefault("is_mock", bool(source.get("is_mock", False)) or bool(data.get("is_mock", False)))

    out = detect_changes(
        frames=frames,
        config=_load_config(args),
        source=source,
        is_mock=bool(source.get("is_mock", False)),
    )

    payload = out.model_dump_json(indent=2)
    with open(args.output, "w", encoding="utf-8") as fh:
        fh.write(payload)
    print(f"written: {args.output}")

    if args.print_summary:
        print("---- 事件汇总 ----")
        print(_summary(out))
    else:
        print(f"事件数: {out.event_count.get('total_events', 0)} | review_required: {out.review_required}")
    return 0


if __name__ == "__main__":
    sys.exit(main())