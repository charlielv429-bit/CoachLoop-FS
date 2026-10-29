"""确定性负荷核算：原始数值用于计算和审计，仅展示结果时舍入。"""
import math
from numbers import Real

from .schemas import LoadAccounting, LoadMetric, MeasurementKind

_GROUP_TARGET = 0.75
_INDIVIDUAL_TARGET = 0.50
# 宽松的数据录入有效域，不是学生运动目标或医学安全阈值。
HR_MIN = 20.0
HR_MAX = 250.0


def validate_load_inputs(total_minutes, group_active_min, individual_active_min, avg_hr):
    for name, value in (("total_minutes", total_minutes), ("group_active_min", group_active_min),
                        ("individual_active_min", individual_active_min), ("avg_hr", avg_hr)):
        if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
            raise ValueError(f"{name} 必须是有限数值")
    if total_minutes <= 0 or int(total_minutes) != total_minutes:
        raise ValueError("total_minutes 必须是正整数")
    for value in (group_active_min, individual_active_min):
        if not 0 <= value <= total_minutes:
            raise ValueError("活动时间须在零与总课时之间")
    if not HR_MIN <= avg_hr <= HR_MAX:
        raise ValueError(f"avg_hr 超出数据有效域 [{HR_MIN}, {HR_MAX}]，不是医学安全判定")


def calc_load(total_minutes: int = 45, group_active_min: float = 0.0,
              individual_active_min: float = 0.0, avg_hr: float = 0.0,
              kind: MeasurementKind = MeasurementKind.ESTIMATED) -> LoadAccounting:
    """保留调用参数；无有效心率（包括旧默认0）会明确报错，不再生成伪负荷。

    kind='measured' 表示调用方提供实测值，本模块不推断测量真实性。
    numerator/denominator/result 保留原始计算精度；display_result 仅供展示。
    """
    validate_load_inputs(total_minutes, group_active_min, individual_active_min, avg_hr)
    kind = MeasurementKind(kind)
    estimated = kind is MeasurementKind.ESTIMATED
    label = "预计" if estimated else "实测"
    note = "预计值，待课堂实测验证。" if estimated else "按提供的实测数据核算；不代表医学安全结论。"
    heart = LoadMetric(
        name=f"{label}平均心率", kind=kind,
        formula=f"avg_hr = {float(avg_hr)} 次/分（{label}输入值）",
        numerator=avg_hr, denominator=1.0, unit="次/分", result=avg_hr,
        target="预计范围，待课堂实测验证" if estimated else "实测心率",
    )
    def density(name, key, active, target):
        ratio = active / total_minutes
        return LoadMetric(
            name=name, kind=kind,
            formula=f"{key} = {key}_active_min / total_minutes * 100 = {float(active)} / {total_minutes} * 100",
            numerator=active, denominator=total_minutes, unit="%", result=ratio * 100,
            target=f"≥ {target * 100:.0f}%" if ratio >= target else f"< {target * 100:.0f}%（未达标）",
        )
    return LoadAccounting(
        avg_hr=heart,
        group_density=density("群体运动密度", "group", group_active_min, _GROUP_TARGET),
        individual_density=density("个体练习密度", "individual", individual_active_min, _INDIVIDUAL_TARGET),
        total_minutes=total_minutes, note=note,
    )


def min_activity_for_targets(total_minutes: int = 45) -> dict:
    """反算精确活动时间；展示层可另行格式化，不能回写计算值。"""
    if (isinstance(total_minutes, bool) or not isinstance(total_minutes, Real)
            or not math.isfinite(total_minutes) or total_minutes <= 0
            or int(total_minutes) != total_minutes):
        raise ValueError("total_minutes 必须是有限正整数")
    return {"total_minutes": total_minutes,
            "min_group_active_min": total_minutes * _GROUP_TARGET,
            "min_individual_active_min": total_minutes * _INDIVIDUAL_TARGET,
            "group_target": _GROUP_TARGET, "individual_target": _INDIVIDUAL_TARGET}
