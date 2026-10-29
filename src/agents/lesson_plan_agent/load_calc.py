"""教案生成 Agent —— 运动负荷与密度确定性核算。

仅使用确定性算术，产出带公式/分子/分母/单位/结果的指标，并区分预计值与实测值。
无真实心率/有效练习时间时，一律 kind=estimated 并标注"待课堂实测验证"。
"""
from typing import Optional

from .schemas import LoadAccounting, LoadMetric, MeasurementKind

_GROUP_TARGET = 0.75   # 教师常见目标：群体运动密度 ≥ 75%
_INDIVIDUAL_TARGET = 0.50  # 个体练习密度 ≥ 50%


def _rize(value: float, digits: int = 2) -> float:
    return round(float(value), digits)


def calc_load(
    total_minutes: int = 45,
    group_active_min: float = 0.0,
    individual_active_min: float = 0.0,
    avg_hr: float = 0.0,
    kind: MeasurementKind = MeasurementKind.ESTIMATED,
) -> LoadAccounting:
    """确定性核算负荷与密度。

    参数:
        total_minutes: 总课时（分钟），应与教学流程合计一致。
        group_active_min: 群体活动时间（分钟，口径=参与活动时间/总课时）。
        individual_active_min: 个体有效练习时间（分钟，口径=个人练习/总课时）。
        avg_hr: 预计平均心率（次/分）；无实测用预计。
        kind: estimated（预计）或 measured（实测）。
    """
    if total_minutes <= 0:
        raise ValueError("total_minutes 必须 > 0")
    if group_active_min < 0 or individual_active_min < 0:
        raise ValueError("活动时间不能为负")
    if group_active_min > total_minutes:
        raise ValueError("群体活动时间不能超过总课时")
    if individual_active_min > total_minutes:
        raise ValueError("个体练习时间不能超过总课时")

    group_ratio = group_active_min / total_minutes
    indiv_ratio = individual_active_min / total_minutes

    avg_hr_metric = LoadMetric(
        name="预计平均心率",
        kind=kind,
        formula=f"avg_hr = {_rize(avg_hr,1)} 次/分（预测目标/区间，非实测）",
        numerator=_rize(avg_hr, 1),
        denominator=1.0,
        unit="次/分",
        result=_rize(avg_hr, 1),
        target="预计范围，待课堂实测验证" if kind is MeasurementKind.ESTIMATED else "实测心率",
    )
    group_metric = LoadMetric(
        name="群体运动密度",
        kind=kind,
        formula=f"group = group_active_min / total_minutes = {_rize(group_active_min,1)} / {total_minutes}",
        numerator=_rize(group_active_min, 1),
        denominator=float(total_minutes),
        unit="%",
        result=_rize(group_ratio * 100, 2),
        target=f"≥ {_GROUP_TARGET * 100:.0f}%" if group_ratio >= _GROUP_TARGET else f"< {_GROUP_TARGET * 100:.0f}%（未达标）",
    )
    indiv_metric = LoadMetric(
        name="个体练习密度",
        kind=kind,
        formula=f"individual = individual_active_min / total_minutes = {_rize(individual_active_min,1)} / {total_minutes}",
        numerator=_rize(individual_active_min, 1),
        denominator=float(total_minutes),
        unit="%",
        result=_rize(indiv_ratio * 100, 2),
        target=f"≥ {_INDIVIDUAL_TARGET * 100:.0f}%" if indiv_ratio >= _INDIVIDUAL_TARGET else f"< {_INDIVIDUAL_TARGET * 100:.0f}%（未达标）",
    )
    return LoadAccounting(
        avg_hr=avg_hr_metric,
        group_density=group_metric,
        individual_density=indiv_metric,
        total_minutes=total_minutes,
    )


def min_activity_for_targets(total_minutes: int = 45) -> dict:
    """反算满足"群体≥75%、个体≥50%"所需的最小活动时间。"""
    if total_minutes <= 0:
        raise ValueError("total_minutes 必须 > 0")
    return {
        "total_minutes": total_minutes,
        "min_group_active_min": _rize(total_minutes * _GROUP_TARGET, 1),
        "min_individual_active_min": _rize(total_minutes * _INDIVIDUAL_TARGET, 1),
        "group_target": _GROUP_TARGET,
        "individual_target": _INDIVIDUAL_TARGET,
    }