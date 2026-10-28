from typing import Any, Dict, List, Optional, Union
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from coze_coding_utils.runtime_ctx.context import Context
from graphs.state import ValidateInput, ValidateOutput


def _to_int(value: Any) -> Optional[int]:
    """将输入标准化为整数；无法无歧义转换时返回 None。

    接受：真正的 int（排除 bool）；纯数字字符串（如 "30"、"3"）。
    拒绝：小数（float 或含小数点字符串，如 3.5 / "3.5"）、"abc"、
          空字符串、负号串、布尔值等。
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        s = value.strip()
        if s.isdigit():
            return int(s)
        return None
    return None


def _append_error(errors: List[Dict[str, Any]], field: str, code: str, message: str) -> None:
    """以结构化方式记录字段错误，code 用于区分 missing_field / invalid_type / empty。"""
    errors.append({"field": field, "code": code, "message": message})


def validate_node(state: ValidateInput, config: RunnableConfig, runtime: Runtime[Context]) -> ValidateOutput:
    """
    title: 输入校验与标准化
    desc: 在工作流入口对输入做字段存在性、类型与非空校验，并对 numeric 字段做整数标准化；缺失与类型错误以结构化错误区分。skill_code 仅校验为非空字符串，不做候选白名单拦截，不做范围拦截。
    """
    ctx = runtime.context
    validation_result: Dict[str, Dict[str, Any]] = {}
    errors: List[Dict[str, Any]] = []

    # ---- student_id：必填、字符串、非空 ----
    sid: Any = state.student_id
    if sid is None:
        validation_result["student_id"] = {"valid": False, "error": "缺少必填字段"}
        _append_error(errors, "student_id", "missing_field", "student_id 缺少必填字段")
    elif isinstance(sid, bool) or not isinstance(sid, str):
        validation_result["student_id"] = {"valid": False, "error": "必须为字符串"}
        _append_error(errors, "student_id", "invalid_type", "student_id 类型错误，必须为字符串")
    elif not sid.strip():
        validation_result["student_id"] = {"valid": False, "error": "不能为空"}
        _append_error(errors, "student_id", "empty", "student_id 不能为空")
    else:
        validation_result["student_id"] = {"valid": True, "error": ""}

    # ---- skill_code：必填、非空字符串；不做候选白名单拦截 ----
    sc: Any = state.skill_code
    if sc is None:
        validation_result["skill_code"] = {"valid": False, "error": "缺少必填字段"}
        _append_error(errors, "skill_code", "missing_field", "skill_code 缺少必填字段")
    elif isinstance(sc, bool) or not isinstance(sc, str):
        validation_result["skill_code"] = {"valid": False, "error": "必须为字符串"}
        _append_error(errors, "skill_code", "invalid_type", "skill_code 类型错误，必须为字符串")
    elif not sc.strip():
        validation_result["skill_code"] = {"valid": False, "error": "不能为空"}
        _append_error(errors, "skill_code", "empty", "skill_code 不能为空")
    else:
        validation_result["skill_code"] = {"valid": True, "error": ""}

    # ---- duration_min：必填；接受整数或纯数字字符串，标准化为 int ----
    raw_dur: Any = state.duration_min
    duration_int: Optional[int] = None
    if raw_dur is None:
        validation_result["duration_min"] = {"valid": False, "error": "缺少必填字段"}
        _append_error(errors, "duration_min", "missing_field", "duration_min 缺少必填字段")
    else:
        duration_int = _to_int(raw_dur)
        if duration_int is None:
            validation_result["duration_min"] = {
                "valid": False,
                "error": "必须为整数或纯数字字符串",
            }
            _append_error(errors, "duration_min", "invalid_type", "duration_min 类型错误，必须为整数或纯数字字符串")
        else:
            validation_result["duration_min"] = {"valid": True, "error": ""}

    # ---- observation：必填、字符串、非空 ----
    obs: Any = state.observation
    if obs is None:
        validation_result["observation"] = {"valid": False, "error": "缺少必填字段"}
        _append_error(errors, "observation", "missing_field", "observation 缺少必填字段")
    elif isinstance(obs, bool) or not isinstance(obs, str):
        validation_result["observation"] = {"valid": False, "error": "必须为字符串"}
        _append_error(errors, "observation", "invalid_type", "observation 类型错误，必须为字符串")
    elif not obs.strip():
        validation_result["observation"] = {"valid": False, "error": "不能为空"}
        _append_error(errors, "observation", "empty", "observation 不能为空")
    else:
        validation_result["observation"] = {"valid": True, "error": ""}

    # ---- stability_score：可选；为空(None)则通过；否则接受整数/纯数字字符串并标准化 ----
    raw_ss: Any = state.stability_score
    stability_int: Optional[int] = None
    if raw_ss is None:
        validation_result["stability_score"] = {"valid": True, "error": ""}
    else:
        stability_int = _to_int(raw_ss)
        if stability_int is None:
            validation_result["stability_score"] = {
                "valid": False,
                "error": "必须为整数或纯数字字符串",
            }
            _append_error(errors, "stability_score", "invalid_type", "stability_score 类型错误，必须为整数或纯数字字符串")
        else:
            validation_result["stability_score"] = {"valid": True, "error": ""}

    run_status: str = "valid" if not errors else "invalid"
    return ValidateOutput(
        run_status=run_status,
        validation_result=validation_result,
        errors=errors,
        duration_min=duration_int,
        stability_score=stability_int,
    )