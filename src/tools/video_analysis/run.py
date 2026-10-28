"""姿态特征计算模块的运行入口（CLI）。

用法示例：
    python -m tools.video_analysis.run assets/mock/pose_keypoints_mock.json --side left
    python -m tools.video_analysis.run assets/mock/pose_keypoints_mock.json -o /tmp/out.json

注意：本模块只处理 MOCK 关键点数据，不做真实视频识别，输出恒带 is_mock=true。
"""
import argparse
import json
import sys
from typing import List

from .features import process_keypoint_dataset
from .keypoint_io import read_keypoint_json


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="CoachLoop-FS 姿态特征计算（仅 MOCK 关键点，非真实视频识别）"
    )
    parser.add_argument("input", help="关键点 JSON 文件路径")
    parser.add_argument(
        "--side", default="left", choices=["left", "right"], help="判定腿/支撑腿一侧，默认 left"
    )
    parser.add_argument(
        "--output", "-o", default=None, help="输出 JSON 路径（默认打印到 stdout）"
    )
    return parser


def main(argv: List[str] | None = None) -> None:
    args = _build_arg_parser().parse_args(argv)

    try:
        dataset = read_keypoint_json(args.input)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(2)

    output = process_keypoint_dataset(dataset, side=args.side)
    payload = output.model_dump_json(indent=2)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(payload)
        print(f"written: {args.output}")
    else:
        sys.stdout.write(payload + "\n")


if __name__ == "__main__":
    main()