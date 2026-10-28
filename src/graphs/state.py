from typing import Any
from pydantic import BaseModel, Field


class GlobalState(BaseModel):
    """工作流全局状态，保存原始输入与过程产物，各节点输出自动合并于此。

    说明：本工作流为通用技术框架，不做花滑专业判断；目标群体、动作标准、
    评价指标与正式报告均待专业同学确认。输入字段使用 Any 以支持在
    校验节点中以确定性代码完成字段存在性、类型与非空判断。
    """
    # ---- 原始输入 ----
    student_id: Any = Field(default=None, description="学员唯一标识")
    skill_code: Any = Field(default=None, description="技能编码")
    duration_min: Any = Field(default=None, description="训练时长（分钟）")
    observation: Any = Field(default=None, description="原始观察记录文本")
    stability_score: Any = Field(default=None, description="稳定性得分（可选，候选评分范围 0-10）")

    # ---- 过程/输出产物 ----
    run_status: str = Field(default="pending", description="运行状态：valid / invalid")
    validation_result: dict = Field(default={}, description="字段级校验结果（按字段返回 valid/error）")
    feedback: dict = Field(default={}, description="结构化模拟反馈")
    mock: bool = Field(default=True, description="反馈是否为模拟数据")
    errors: list = Field(default=[], description="字段错误信息列表")


class GraphInput(BaseModel):
    """工作流的输入（开始节点）"""
    student_id: Any = Field(default=None, description="学员唯一标识（必填）")
    skill_code: Any = Field(default=None, description="技能编码（必填，须在候选技能范围内）")
    duration_min: Any = Field(default=None, description="训练时长（分钟，必填，须大于 0）")
    observation: Any = Field(default=None, description="原始观察记录文本（必填）")
    stability_score: Any = Field(default=None, description="稳定性得分（可选，范围 0-10）")


class GraphOutput(BaseModel):
    """工作流的输出（结束节点）"""
    run_status: str = Field(..., description="运行状态：valid / invalid")
    validation_result: dict = Field(default={}, description="字段级校验结果")
    feedback: dict = Field(default={}, description="结构化模拟反馈")
    mock: bool = Field(default=True, description="反馈是否为模拟数据")
    errors: list = Field(default=[], description="字段错误信息列表")


class ValidateInput(BaseModel):
    """校验节点的输入"""
    student_id: Any = Field(default=None, description="学员唯一标识")
    skill_code: Any = Field(default=None, description="技能编码")
    duration_min: Any = Field(default=None, description="训练时长（分钟）")
    observation: Any = Field(default=None, description="原始观察记录文本")
    stability_score: Any = Field(default=None, description="稳定性得分（可选，0-10）")


class ValidateOutput(BaseModel):
    """校验节点的输出"""
    run_status: str = Field(..., description="运行状态：valid / invalid")
    validation_result: dict = Field(default={}, description="字段级校验结果")
    errors: list = Field(default=[], description="结构化字段错误列表（含 missing_field/invalid_type/empty）")
    duration_min: Any = Field(default=None, description="标准化后的训练时长（整数）")
    stability_score: Any = Field(default=None, description="标准化后的稳定性得分（整数或空）")


class ValidateStatusInput(BaseModel):
    """条件分支的输入：根据校验状态决定后续走向"""
    run_status: str = Field(..., description="校验后的运行状态")


class FeedbackInput(BaseModel):
    """模拟反馈节点的输入（仅校验通过后触发）"""
    student_id: Any = Field(default=None, description="学员唯一标识")
    skill_code: Any = Field(default=None, description="技能编码")
    duration_min: Any = Field(default=None, description="训练时长（分钟）")
    observation: Any = Field(default=None, description="原始观察记录文本")
    stability_score: Any = Field(default=None, description="稳定性得分（可选，0-10）")


class FeedbackOutput(BaseModel):
    """模拟反馈节点的输出"""
    feedback: dict = Field(default={}, description="结构化模拟反馈")
    mock: bool = Field(default=True, description="反馈是否为模拟数据")


class FinalizeInput(BaseModel):
    """收尾节点的输入"""
    run_status: str = Field(..., description="运行状态：valid / invalid")
    validation_result: dict = Field(default={}, description="字段级校验结果")
    feedback: dict = Field(default={}, description="结构化模拟反馈")
    mock: bool = Field(default=True, description="反馈是否为模拟数据")
    errors: list = Field(default=[], description="字段错误信息列表")


class FinalizeOutput(BaseModel):
    """收尾节点的输出"""
    run_status: str = Field(..., description="运行状态：valid / invalid")
    validation_result: dict = Field(default={}, description="字段级校验结果")
    feedback: dict = Field(default={}, description="结构化模拟反馈")
    mock: bool = Field(default=True, description="反馈是否为模拟数据")
    errors: list = Field(default=[], description="字段错误信息列表")