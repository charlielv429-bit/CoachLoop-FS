"""关键点 JSON 文件的读取与校验。

强制约束：MOCK 关键点文件必须包含 ``is_mock=true`` 与 ``source``（mock:// 标记），
否则视为无法确认来源而拒绝，防止把模拟结果冒充真实视频识别结果。
"""
import json
import os
from typing import Any, Dict

from .schemas import KeypointDataset

# 允许的模型标注：本版仅 mock-geometry
_ALLOWED_MODELS = {"mock-geometry"}


class KeypointValidationError(ValueError):
    """关键点数据读取/校验失败。"""


def read_keypoint_json(path: str) -> KeypointDataset:
    """读取并校验关键点 JSON 文件。

    参数:
        path: JSON 文件路径（本地或 http/https URL 的本地缓存路径）。
    返回:
        解析并校验通过后的 :class:`KeypointDataset`。
    异常:
        KeypointValidationError: 文件不存在、结构非法、非 mock 或缺来源标记。
    """
    if not os.path.exists(path):
        raise KeypointValidationError(f"关键点文件不存在: {path}")

    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)

    if not isinstance(raw, Dict):
        raise KeypointValidationError("JSON 顶层必须是对象（含 is_mock/source/frames）")

    # 强制 MOCK 标记与来源标记，避免冒充真实识别结果
    if raw.get("is_mock") is not True:
        raise KeypointValidationError(
            "is_mock 必须为 true：本版仅接受明确标注的人工构造 MOCK 关键点数据"
        )
    source = raw.get("source")
    if not isinstance(source, str) or not source.strip() or not source.startswith("mock://"):
        raise KeypointValidationError("source 缺失或非 mock 标记，无法确认数据来源")

    model = raw.get("model", "mock-geometry")
    if model not in _ALLOWED_MODELS:
        raise KeypointValidationError(
            f"model 标注不支持：{model}；本版不允许冒充 MediaPipe 真实识别结果"
        )

    try:
        return KeypointDataset.model_validate(raw)
    except Exception as exc:  # noqa: BLE001 - 统一转为领域校验错误
        raise KeypointValidationError(f"关键点 JSON 结构校验失败: {exc}") from exc