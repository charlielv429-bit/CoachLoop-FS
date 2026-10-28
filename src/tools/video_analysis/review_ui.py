"""V5.2 最小教练事件审核界面（本地 HTTP 服务）。

复用 V4 事件结果与 V5 审核模块（event_review），提供一个极简浏览器界面：
- 展示事件的时间段/特征/偏离幅度/审核状态；
- 点击事件跳转到对应视频时间（同源服务视频位流，带 Range 支持）；
- 四种人工审核（confirmed/normal_movement/tracking_error/uncertain）+ 备注；
- 审核结果经 event_review.apply_review 持久化到 JSON 文件，刷新不丢失；
- 演示审核写入独立 demo 文件并强制 `[demo]` 标记，与真实教练结果隔离。

仅使用 Python 标准库；不做动作诊断、不接大模型、不新增数据库。
用法：
    PYTHONPATH=src .venv/bin/python -m tools.video_analysis.review_ui --port 8766
"""
import argparse
import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from .event_review import EventReviewOutput, apply_review, build_review_records, validate_status

_WS = os.getenv("COZE_WORKSPACE_PATH", "")
V4_INPUT = os.path.join("/tmp", "event_detection_result.json")
REAL_PATH = os.path.join("/tmp", "coach_review.json")        # 真实教练审核（独立文件）
DEMO_PATH = os.path.join("/tmp", "coach_review.demo.json")   # 演示审核（独立文件，[demo] 隔离）
VIDEO_PATH = os.path.join(_WS, "assets", "videos", "input_skate.mp4")
STATIC_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "review_ui_static.html")

_DEMO_REVIEWER = "[demo]演示教练"  # 演示审核强制署名标记


def _load_review(path: str) -> EventReviewOutput:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return EventReviewOutput.model_validate(json.load(fh))
    except (FileNotFoundError, Exception):  # noqa: BLE001 不存在/损坏则从 V4 重建（全 pending）
        with open(V4_INPUT, "r", encoding="utf-8") as fh:
            detection = json.load(fh)
        return build_review_records(detection, V4_INPUT).finalize()


def _save_review(out: EventReviewOutput, path: str) -> None:
    out.finalize()
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(out.model_dump_json(indent=2, ensure_ascii=False))


def _ensure_real() -> EventReviewOutput:
    out = _load_review(REAL_PATH)
    if not os.path.exists(REAL_PATH):
        _save_review(out, REAL_PATH)
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "CoachReviewUI/1.0"

    # ---------- 基础 ----------
    def _json(self, code: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, path: str) -> None:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                body = fh.read().encode("utf-8")
        except FileNotFoundError:
            self.send_error(404, "静态页缺失")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args) -> None:  # 静默，避免噪音
        pass

    # ---------- 视频（Range 支持，供点击跳转）----------
    def _serve_video(self) -> None:
        if not os.path.exists(VIDEO_PATH):
            self._json(200, {"playable": False, "reason": "沙箱视频不可访问（文件缺失），无法播放，请勿依赖伪播放"})
            return
        size = os.path.getsize(VIDEO_PATH)
        range_header = self.headers.get("Range")
        start, end = 0, size - 1
        status = 200
        if range_header and range_header.startswith("bytes="):
            try:
                spec = range_header.split("=", 1)[1].split(",", 1)[0]
                if "-" in spec:
                    a, b = spec.split("-", 1)
                    start = int(a) if a else 0
                    end = int(b) if b else size - 1
                status = 206
            except Exception:  # noqa: BLE001
                start, end, status = 0, size - 1, 200
        end = min(end, size - 1)
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with open(VIDEO_PATH, "rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                chunk = fh.read(min(1 << 20, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    # ---------- API ----------
    def _read_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    def _handle_events(self, path: str) -> None:
        if path == "/api/events":
            out = _ensure_real()
            self._json(200, {"review": out.model_dump(), "demo": False})
            return
        if path == "/api/demo":
            out = _load_review(DEMO_PATH)
            self._json(200, {"review": out.model_dump(), "demo": True})
            return
        self._json(404, {"error": "not found"})

    def _apply(self, demo: bool) -> None:
        body = self._read_body()
        event_id = str(body.get("event_id") or "")
        status = str(body.get("status") or "")
        reviewer = str(body.get("reviewed_by") or "").strip()
        note = str(body.get("note") or "")
        try:
            validate_status(status)
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return
        if demo:
            reviewer = _DEMO_REVIEWER if not reviewer else f"{_DEMO_REVIEWER};{reviewer}"
            note = (note + " [demo]") if note else "[demo]"
            out = _load_review(DEMO_PATH)
            path = DEMO_PATH
        else:
            out = _ensure_real()
            path = REAL_PATH
            if not reviewer:
                self._json(400, {"error": "真实教练审核 review_by 不能为空"})
                return
        rec = next((r for r in out.records if r.event_id == event_id), None)
        if rec is None:
            self._json(404, {"error": f"未找到 event_id: {event_id}"})
            return
        apply_review(rec, status, reviewer, note=note)
        _save_review(out, path)
        self._json(200, {"ok": True, "review": out.model_dump(), "demo": demo})

    def _api_review(self, demo: bool) -> None:
        self._apply(demo)

    def _api_demo_path(self):
        # 兼容旧名
        return self._apply(demo=True)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            self._html(STATIC_PATH)
        elif path == "/favicon.ico":
            self.send_response(204); self.end_headers()
        elif path == "/video":
            self._serve_video()
        elif path in ("/api/events", "/api/demo"):
            self._handle_events(path)
        elif path == "/demo/reset":
            self._reset_demo()
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/review":
            self._api_review(demo=False)
        elif path == "/api/demo/review":
            self._api_review(demo=True)
        elif path == "/api/demo/reset":
            self._reset_demo()
        else:
            self._json(404, {"error": "not found"})

    def _reset_demo(self) -> None:
        with open(V4_INPUT, "r", encoding="utf-8") as fh:
            detection = json.load(fh)
        out = build_review_records(detection, V4_INPUT).finalize()
        # 造一条明确 demo 的示例审核（仅写入 demo 文件）
        first = next((r for r in out.records if r), None)
        if first is not None:
            apply_review(
                first, "tracking_error", _DEMO_REVIEWER,
                note="[demo] 示例：标记为疑似跟踪误差（演示用，非真实教练结论）",
            )
        _save_review(out, DEMO_PATH)
        self._json(200, {"ok": True, "review": out.model_dump(), "demo": True})


def main(argv: Optional = None) -> None:
    parser = argparse.ArgumentParser(description="CoachLoop-FS V5.2 教练审核界面")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args(argv)
    # 预生成真实审核文件（若不存在）
    _ensure_real()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[info] 审核界面已启动: http://{args.host}:{args.port}")
    print(f"[info] 真实审核保存: {REAL_PATH}")
    print(f"[info] 演示审核保存: {DEMO_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()