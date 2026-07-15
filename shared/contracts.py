"""前后端共享通信契约（零 Qt 依赖）。

所有 Request/Response 均为 Pydantic BaseModel，带完整类型提示与文档字符串。
前后端禁止直接传递裸 dict —— 一律通过本模块定义的模型。
"""
from __future__ import annotations

from enum import Enum
from typing import Annotated, Dict, List, Literal, Union

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------

class SimilarityMode(str, Enum):
    """查重模式。"""
    ONE_TO_MANY = "1_to_many"      # 主文档 vs 多个副文档
    MANY_TO_MANY = "many_to_many"  # 所有文档两两比对


class LineSpacingType(str, Enum):
    """行间距类型（与现有 UI 下拉一致）。"""
    SINGLE = "1 倍"
    ONE_HALF = "1.5 倍"
    CUSTOM = "自定义"


class EventType(str, Enum):
    """后端向前端推送的事件类型。"""
    CHECK_STARTED = "check_started"
    CHECK_PROGRESS = "check_progress"
    CHECK_COMPLETED = "check_completed"
    CHECK_FAILED = "check_failed"
    EXTRACT_COMPLETED = "extract_completed"
    EXTRACT_FAILED = "extract_failed"
    PPTX_PROGRESS = "pptx_progress"
    PPTX_COMPLETED = "pptx_completed"
    PPTX_FAILED = "pptx_failed"


# ---------------------------------------------------------------------------
# Request（UI → core 命令）
# ---------------------------------------------------------------------------

class SimilarityRequest(BaseModel):
    """发起一次题目查重。"""
    mode: SimilarityMode
    threshold: float = Field(0.8, ge=0.0, le=1.0, description="相似度判定阈值")
    num_pattern: str = Field("1.", description="题号格式示例或原始正则；空串启用内置宽泛匹配")
    opt_prefix: str = Field("A.", description="选项前缀示例或原始正则；空串启用内置宽泛匹配")
    main_path: str = Field("", description="1对多模式主文档路径")
    secondary_paths: List[str] = Field(default_factory=list, description="1对多模式副文档路径")
    all_paths: List[str] = Field(default_factory=list, description="多对多模式全部文档路径")


class ExtractQuestionsRequest(BaseModel):
    """从 Word 文档提取题目。"""
    doc_path: str
    num_pattern: str = "1."
    opt_prefix: str = "A."


class GeneratePptxRequest(BaseModel):
    """基于模板为题目生成 PPT。"""
    template_path: str
    questions: List[List[str]] = Field(default_factory=list, description="每道题为行列表（题干+选项行）")
    font_name: str
    font_size: int = Field(18, ge=9, le=72)
    output_path: str
    line_spacing_type: LineSpacingType = LineSpacingType.SINGLE
    line_spacing_value: float = 1.0
    first_line_indent: bool = True


# ---------------------------------------------------------------------------
# Response（core → UI 结果，替代原裸 dict）
# ---------------------------------------------------------------------------

class QuestionScore(BaseModel):
    """单对题目的相似度评分（替代 score_question_pair 返回的裸 dict）。"""
    score: float = Field(..., ge=0.0, le=1.0)
    reason: str
    stem_ratio: float
    option_ratio: float
    full_ratio: float
    token_ratio: float
    bigram_ratio: float


class SimilaritySource(BaseModel):
    """1对多模式下，某题命中的副文档来源。"""
    file: str
    score: float
    reason: str


class SimilarityDetail(BaseModel):
    """1对多模式下，主文档中一道重复题及其来源。"""
    index: int
    text: List[str]
    sources: List[SimilaritySource]


class OneToManyResult(BaseModel):
    """1对多查重结果。"""
    mode: Literal[SimilarityMode.ONE_TO_MANY] = SimilarityMode.ONE_TO_MANY
    main_count: int
    duplicate_count: int
    details: List[SimilarityDetail]


class SimilarityPair(BaseModel):
    """多对多模式下的一对重复题。"""
    q1_file: str
    q1_index: int
    q1_text: List[str]
    q2_file: str
    q2_index: int
    q2_text: List[str]
    score: float
    reason: str
    pair_type: Literal["internal", "cross"]


class ManyToManyResult(BaseModel):
    """多对多查重结果。"""
    mode: Literal[SimilarityMode.MANY_TO_MANY] = SimilarityMode.MANY_TO_MANY
    total_questions: int
    document_count: int
    doc_questions: Dict[str, int]
    duplicate_pairs: List[SimilarityPair]
    duplicate_rate: float


class ExtractQuestionsResult(BaseModel):
    """题目提取结果。"""
    questions: List[List[str]]


class GeneratePptxResult(BaseModel):
    """PPT 生成结果。"""
    output_path: str
    page_count: int


# 查重结果联合类型（按 mode 判别）
SimilarityResult = Annotated[
    Union[OneToManyResult, ManyToManyResult], Field(discriminator="mode")
]


# ---------------------------------------------------------------------------
# Event（core → UI 推送，统一事件通道）
# ---------------------------------------------------------------------------

class _BaseEvent(BaseModel):
    type: EventType


class ProgressEvent(_BaseEvent):
    """通用进度事件（查重/提取/PPT生成复用）。"""
    type: Literal[EventType.CHECK_PROGRESS, EventType.PPTX_PROGRESS] = EventType.CHECK_PROGRESS
    message: str = ""
    current: int = 0
    total: int = 0


class CheckStartedEvent(_BaseEvent):
    type: Literal[EventType.CHECK_STARTED] = EventType.CHECK_STARTED
    mode: SimilarityMode


class CheckCompletedEvent(_BaseEvent):
    type: Literal[EventType.CHECK_COMPLETED] = EventType.CHECK_COMPLETED
    result: SimilarityResult


class ExtractCompletedEvent(_BaseEvent):
    type: Literal[EventType.EXTRACT_COMPLETED] = EventType.EXTRACT_COMPLETED
    result: ExtractQuestionsResult


class FailedEvent(_BaseEvent):
    type: Literal[
        EventType.CHECK_FAILED, EventType.EXTRACT_FAILED, EventType.PPTX_FAILED
    ] = EventType.CHECK_FAILED
    message: str


class PptxCompletedEvent(_BaseEvent):
    type: Literal[EventType.PPTX_COMPLETED] = EventType.PPTX_COMPLETED
    result: GeneratePptxResult


# 事件联合类型（按 type 判别）
DomainEvent = Annotated[
    Union[
        CheckStartedEvent, CheckCompletedEvent, ExtractCompletedEvent,
        PptxCompletedEvent, ProgressEvent, FailedEvent,
    ],
    Field(discriminator="type"),
]
