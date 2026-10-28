"""姿态特征计算的纯几何函数。

输入均为 2D 归一化图像坐标（x 向右、y 向下）。所有结果为 2D 投影平面内
的可观测几何量；任何结果都不得被解释为真实重心、冰刀压力或三维姿态测量。
"""
import math
from typing import Tuple

Point = Tuple[float, float]

# 极小长度阈值：低于此视为零长度（退化）
_EPS = 1e-9


class DegenerateGeometryError(ValueError):
    """几何退化异常（如关键点重合、零长度投影）。"""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _norm(dx: float, dy: float) -> float:
    return math.hypot(dx, dy)


def _clamp_cos(value: float) -> float:
    return max(-1.0, min(1.0, value))


def angle_at_vertex(a: Point, b: Point, c: Point) -> float:
    """二维夹角：顶点 b，两臂 b->a 与 b->c，返回 [0,180] 度。

    当任一臂长度 < _EPS（重合/零长度）抛 DegenerateGeometryError。
    """
    v1x = a[0] - b[0]
    v1y = a[1] - b[1]
    v2x = c[0] - b[0]
    v2y = c[1] - b[1]
    n1 = _norm(v1x, v1y)
    n2 = _norm(v2x, v2y)
    if n1 < _EPS or n2 < _EPS:
        raise DegenerateGeometryError("zero_length_arm")
    cos = (v1x * v2x + v1y * v2y) / (n1 * n2)
    return math.degrees(math.acos(_clamp_cos(cos)))


def knee_angle_2d(hip: Point, knee: Point, ankle: Point) -> float:
    """膝关节二维夹角：vertex=膝，两臂膝->髋、膝->踝。"""
    return angle_at_vertex(hip, knee, ankle)


def torso_pitch_deg(shoulder_mid: Point, hip_mid: Point) -> float:
    """躯干倾角（大小，度）：躯干轴（肩中点->髋中点）与竖直轴的夹角。

    竖直参考在图像 y-向下坐标系中为 (0,1)（即画面竖直方向）。
    返回 [0,180] 的倾角大小；正负/朝前朝后需依滑行方向推断，本模块不提供。
    躯干轴零长度时抛 DegenerateGeometryError。
    """
    vx = hip_mid[0] - shoulder_mid[0]
    vy = hip_mid[1] - shoulder_mid[1]
    n = _norm(vx, vy)
    if n < _EPS:
        raise DegenerateGeometryError("zero_length_torso")
    cos = _clamp_cos(vy / n)  # dot(轴单位向量, 竖直单位向量(0,1)) = vy/n
    return math.degrees(math.acos(cos))


def hip_ankle_offset_norm(hip_mid: Point, ankle: Point) -> float:
    """髋踝相对水平偏移（图像平面 x），按腿长归一化。

    定义 = (hip_x - ankle_x) / |hip_ankle|，|hip_ankle| 为该腿 2D 投影长度。
    仅反映图像水平位置关系，不代表真实重心/支撑点在三维空间的位置。
    腿长 < _EPS 时抛 DegenerateGeometryError。
    """
    vx = hip_mid[0] - ankle[0]
    vy = hip_mid[1] - ankle[1]
    n = _norm(vx, vy)
    if n < _EPS:
        raise DegenerateGeometryError("zero_length_leg")
    return vx / n