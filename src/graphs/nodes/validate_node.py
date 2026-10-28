from typing import Any, Dict, List
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from coze_coding_utils.runtime_ctx.context import Context
from graphs.state import ValidateInput, ValidateOutput

# 候选技能编码集合（占位）——目标群体、动作标准待专业同学确认后替换
VALID_SKILL_CODES: set = {"jump", "spin", "spiral", "footwork", "step", "camel"}

# 候选稳定性评分范围
MIN_SCORE = 0.0
MAX_SCORE = 10.0


def _is_str(v: Any) -> bool:
    """判断值是否为字符串类型"""
    return isinstance(v, str) and not isinstance(v, bool)


def _is_number(v: Any) -> bool:
    """判断值是否为数值（排除布尔与字符串）"""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate_node(state: ValidateInput, config: RunnableConfig, runtime: Runtime[Context]) -> ValidateOutput:
    """
    title: 输入校验
    desc: 使用确定性代码对输入做字段存在性、基础类型、非空与候选范围校验，返回逐字段校验结果与错误信息，不调用任何大模型。
    """
    ctx = runtime.context
    validation_result: Dict[str, Dict[str, Any]] = {}
    errors: List[str] = []

    # ---- student_id：必填、字符串、非空 ----
    sid: Any = state.student_id
    if sid is None:
        validation_result["student_id"] = {"valid": False, "error": "缺少必填字段 student_id"}
        errors.append("student_id: 缺少必填字段")
    elif not _is_str(sid):
        validation_result["student_id"] = {"valid": False, "error": "student_id 必须为字符串"}
        errors.append("student_id: 类型错误，必须是字符串")
    elif not sid.strip():
        validation_result["student_id"] = {"valid": False, "error": "student_id 不能为空"}
        errors.append("student_id: 不能为空")
    else:
        validation_result["student_id"] = {"valid": True, "error": ""}

    # ---- skill_code：必填、字符串、非空、候选范围内 ----
    sc: Any = state.skill_code
    if sc is None:
        validation_result["skill_code"] = {"valid": False, "error": "缺少必填字段 skill_code"}
        errors.append("skill_code: 缺少必填字段")
    elif not _is_str(sc):
        validation_result["skill_code"] = {"valid": False, "error": "skill_code 必须为字符串"}
        errors.append("skill_code: 类型错误，必须是字符串")
    elif not sc.strip():
        validation_result["skill_code"] = {"valid": False, "error": "skill_code 不能为空"}
        errors.append("skill_code: 不能为空")
    elif sc.strip() not in VALID_SKILL_CODES:
        validation_result["skill_code"] = {"valid": False, "error": "skill_code 不在候选技能范围内"}
        errors.append("skill_code: 超出候选技能范围")
    else:
        validation_result["skill_code"] = {"valid": True, "error": ""}

    # ---- duration_min：必填、数值、大于 0 ----
    dur: Any = state.duration_min
    if dur is None:
        validation_result["duration_min"] = {"valid": False, "error": "缺少必填字段 duration_min"}
        errors.append("duration_min: 缺少必填字段")
    elif not _is_number(dur):
        validation_result["duration_min"] = {"valid": False, "error": "duration_min 必须为数值"}
        errors.append("duration_min: 类型错误，必须是数值")
    elif dur <= 0:
        validation_result["duration_min"] = {"valid": False, "error": "duration_min 必须大于 0"}
        errors.append("duration_min: 必须大于 0")
    else:
        validation_result["duration_min"] = {"valid": True, "error": ""}

    # ---- observation：必填、字符串、非空 ----
    obs: Any = state.observation
    if obs is None:
        validation_result["observation"] = {"valid": False, "error": "缺少必填字段 observation"}
        errors.append("observation: 缺少必填字段")
    elif not _is_str(obs):
        validation_result["observation"] = {"valid": False, "error": "observation 必须为字符串"}
        errors.append("observation: 类型错误，必须是字符串")
    elif not obs.strip():
        validation_result["observation"] = {"valid": False, "error": "observation 不能为空"}
        errors.append("observation: 不能为空")
    else:
        validation_result["observation"] = {"valid": True, "error": ""}

    # ---- stability_score：可选；若提供则须为数值且在 [0,10] 内 ----
    ss: Any = state.stability_score
    if ss is None:
        validation_result["stability_score"] = {"valid": True, "error": ""}
    elif not _is_number(ss):
        validation_result["stability_score"] = {"valid": False, "error": "stability_score 必须为数值"}
        errors.append("stability_score: 类型错误，必须是数值")
    elif ss < MIN_SCORE or ss > MAX_SCORE:
        validation_result["stability_score"] = {
            "valid": False,
            "error": "stability_score 超出候选评分范围 [0, 10]",
        }
        errors.append("stability_score: 超出候选评分范围")
    else:
        validation_result["stability_score"] = {"valid": True, "error": ""}

    run_status: str = "valid" if not errors else "invalid"
    return ValidateOutput(
        run_status=run_status,
        validation_result=validation_result,
        errors=errors,
    )