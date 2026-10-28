"""真实 MP4 姿态提取 CLI（需在隔离环境 .venv-video 中运行）。

用法示例：
    PYTHONPATH=src .venv-video/bin/python -m tools.video_analysis.extract_video test.mp4 --side left -o /tmp/pose.json
"""
import argparse
import json
import sys
from typing import List, Optional

from .pose_extractor import DEFAULT_MODEL_PATH, MissingPrerequisiteError, extract_video_pose


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="CoachLoop-FS 真实 MP4 姿态提取（MediaPipe；不做动作评价）"
    )
    parser.add_argument("video", help="获授权测试视频路径")
    parser.add_argument("--side", default="left", choices=["left", "right"], help="判定腿/支撑腿一侧")
    parser.add_argument("--max-frames", type=int, default=None, help="最多处理帧数（可选）")
    parser.add_argument("--model", default=None, help="pose_landmarker.task 路径（默认 assets/models/...）")
    parser.add_argument("--output", "-o", default=None, help="输出 JSON 路径（默认打印 stdout）")
    return parser


def main(argv: Optional[List[str]] = None) -> None:
    args = _build_arg_parser().parse_args(argv)
    try:
        output = extract_video_pose(
            args.video,
            side=args.side,
            max_frames=args.max_frames,
            model_path=args.model or DEFAULT_MODEL_PATH,
        )
    except MissingPrerequisiteError as exc:
        print(f"[OBSTACLE] {exc}", file=sys.stderr)
        sys.exit(3)

    payload = output.model_dump_json(indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(payload)
        print(f"written: {args.output}")
    else:
        sys.stdout.write(payload + "\n")


if __name__ == "__main__":
    main()