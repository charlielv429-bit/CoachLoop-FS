"""V5-MVP 教练事件审核 CLI：复用 V4 事件检测结果生成审核记录。

仅在主 .venv 运行（纯逻辑）：
    PYTHONPATH=src .venv/bin/python -m tools.video_analysis.events_review_cli \
        --input /tmp/event_detection_result.json --output /tmp/event_review_result.json

可选：写入一条审核（演示/供后续 Agent 使用）：
    ... --apply <event_id> --status tracking_error --by coach_zhang --note "疑似跟踪误差"
"""
import argparse
import json
import sys
from typing import List, Optional

from .event_review import (
    EventReviewOutput,
    apply_review,
    build_review_records,
    validate_status,
)

_DEFAULT_INPUT = "/tmp/event_detection_result.json"
_DEFAULT_OUTPUT = "/tmp/event_review_result.json"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CoachLoop-FS V5-MVP 教练事件审核（非诊断）")
    parser.add_argument("--input", default=_DEFAULT_INPUT, help="V4 event_detection JSON 路径")
    parser.add_argument("--output", "-o", default=_DEFAULT_OUTPUT, help="审核结果输出 JSON 路径")
    parser.add_argument("--apply", default=None, help="对指定 event_id 写入一条审核")
    parser.add_argument("--status", default=None, help="审核状态（配合 --apply）")
    parser.add_argument("--by", "--reviewed-by", default=None, help="审核人（配合 --apply）")
    parser.add_argument("--note", default="", help="审核备注（配合 --apply）")
    return parser


def _load_or_build(args, generated_from: str) -> EventReviewOutput:
    try:
        with open(args.output, "r", encoding="utf-8") as fh:
            return EventReviewOutput.model_validate(json.load(fh))
    except (FileNotFoundError, Exception):  # noqa: BLE001 - 不存在或损坏则重建
        with open(args.input, "r", encoding="utf-8") as fh:
            detection = json.load(fh)
        return build_review_records(detection, generated_from)


def _id_map(out: EventReviewOutput) -> dict:
    return {r.event_id: r for r in out.records}


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    validate_status(args.status) if args.status else None

    out = _load_or_build(args, args.input)

    if args.apply:
        target = _id_map(out).get(args.apply)
        if target is None:
            print(f"[OBSTACLE] 未找到 event_id: {args.apply}", file=sys.stderr)
            return 4
        if not args.status or not args.by:
            print("[OBSTACLE] --apply 需同时提供 --status 与 --by", file=sys.stderr)
            return 4
        apply_review(target, args.status, args.by, note=args.note)

    out.finalize()
    with open(args.output, "w", encoding="utf-8") as fh:
        fh.write(out.model_dump_json(indent=2, ensure_ascii=False))
    print(f"written: {args.output}")

    s = out.summary
    print(f"审核记录: {s.get('total', 0)} 条 | 状态分布: {s.get('by_status', {})}")
    if args.apply:
        r = _id_map(out)[args.apply]
        print(f"已更新 {args.apply}: status={args.status} by={args.by} note={args.note!r} history_len={len(r.review_history)}")
    # 打印一条样例（便于验收）
    if out.records:
        sample = out.records[0]
        print("样例记录:")
        print(
            f"  event_id={sample.event_id} | status={sample.review_status.value} | "
            f"frame={sample.original_event['frame_start']}-{sample.original_event['frame_end']} | "
            f"feature={sample.original_event['feature']} | source_video={sample.source.get('video_path')}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())