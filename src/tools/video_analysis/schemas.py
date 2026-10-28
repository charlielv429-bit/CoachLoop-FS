"""姿态特征计算的数据模型（Pydantic）。

坐标系约定（与 MediaPipe Pose 输出一致）：
- 归一化图像坐标，x 向右为正，y 向下为正；
- 所有角度均为 2D 投影平面内的可观测几何量；
- 不得将任何 2D 特征直接解读为真实重心、冰刀压力或三维身体姿态测量值。
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

# 本版模型标注：仅使用人工构造 MOCK 关键点，不接入 MediaPipe 真实识别
MOCK_MODEL_ID = "mock-geometry"


class Landmark(BaseModel):
    """单个身体关键点（2D 归一化坐标）。"""
    id: int = Field(..., description="MediaPipe Pose landmark 索引")
    name: str = Field(..., description="关键点名称，如 left_knee")
    x: float = Field(..., description="归一化图像横坐标，向右为正")
    y: float = Field(..., description="归一化图像纵坐标，向下为正")
    z: Optional[float] = Field(default=None, description="相对深度（本模块不使用）")
    visibility: Optional[float] = Field(default=None, description="可见度 0-1，可选")


class KeypointFrame(BaseModel):
    """单帧关键点序列。"""
    frame_idx: int = Field(..., description="帧序号（从 0 起）")
    timestamp_ms: Optional[float] = Field(default=None, description="时间戳（毫秒）")
    is_mock: bool = Field(..., description="是否人工构造 MOCK 数据")
    source: str = Field(..., description="数据来源标记，mock 形如 mock://...")
    landmarks: List[Landmark] = Field(..., description="该帧关键点列表（缺失即省略条目）")


class KeypointDataset(BaseModel):
    """关键点 JSON 文件的整体结构。"""
    is_mock: bool = Field(..., description="是否人工构造 MOCK 数据（本版必须为 true）")
    source: str = Field(..., description="数据来源标记，如 mock://manual/forward_outside_edge_L")
    model: str = Field(default=MOCK_MODEL_ID, description="模型标注（本版恒为 mock-geometry）")
    fps: Optional[float] = Field(default=None, description="帧率提示（可选）")
    frames: List[KeypointFrame] = Field(..., description="帧序列")


class FeatureResult(BaseModel):
    """单帧可观测姿态特征（仅几何量，非判定）。"""
    knee_angle_deg: Optional[float] = Field(
        default=None, description="膝关节二维夹角（髋-膝-踝，vertex=膝），矢状面观，缺失/退化时为 null"
    )
    torso_pitch_deg: Optional[float] = Field(
        default=None, description="躯干轴（肩中点-髋中点）相对竖直轴的倾角绝对值，矢状面观，缺失/退化时为 null"
    )
    hip_ankle_offset_norm: Optional[float] = Field(
        default=None,
        description="髋踝相对水平偏移（图像平面 x），按腿长归一化；为可观测几何量，非重心/非三维测量",
    )
    degenerate: bool = Field(default=False, description="是否退化几何（如关键点重合/零长度投影）")
    degeneracy_reason: str = Field(default="", description="退化原因说明")
    missing_required: List[str] = Field(default=[], description="缺失的必需关键点名称列表")


class FrameRecord(BaseModel):
    """单帧输出：特征 + 关键点质量统计。"""
    frame_idx: int = Field(..., description="帧序号")
    timestamp_ms: Optional[float] = Field(default=None, description="时间戳（毫秒）")
    features: FeatureResult = Field(..., description="可观测姿态特征")
    keypoint_stats: Dict[str, Any] = Field(
        default={}, description="关键点质量统计（缺失率/平均可见度），为观测信息，非评价"
    )


class AnalysisOutput(BaseModel):
    """模块整体输出（结构化 JSON）。"""
    source: Dict[str, Any] = Field(..., description="来源信息：mode/is_mock/source/model/fps")
    frames: List[FrameRecord] = Field(..., description="逐帧特征结果")
    summary: Dict[str, Any] = Field(default={}, description="观测统计（检测率/退化帧数，非评分）")
    errors: List[str] = Field(default=[], description="处理过程中的错误或告警")
    reserved_coach_review: Dict[str, Any] = Field(
        default_factory=lambda: {
            "review_status": "pending",
            "needs_coach_review": True,
            "coach_notes": "",
            "coach_verdict": None,
        },
        description="预留教练审核字段（本版一律 pending，不填写任何判定）",
    )