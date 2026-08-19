"""前后端共享通信契约（零 Qt 依赖）。

所有 Request/Response 均为 Pydantic BaseModel，带完整类型提示与文档字符串。
前后端禁止直接传递裸 dict —— 一律通过本模块定义的模型。
"""
from __future__ import annotations

from enum import Enum
from typing import Annotated, Dict, List, Literal, Optional, Union

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


class ExamLineSpacingType(str, Enum):
    """JSON→Word 试卷行间距预设（与 UI 下拉一致）。"""
    SINGLE = "1倍行距"
    ONE_HALF = "1.5倍行距"
    DOUBLE = "2倍行距"
    CUSTOM = "自定义"


class EventType(str, Enum):
    """后端向前端推送的事件类型。

    ⚠️ **专属约定（重要）**：每个 ``EventType`` 值**只属于一个工具**，不得跨工具复用。
    所有 ViewModel 共用同一个 ``QtEventEmitter``，若两个工具复用同一 ``EventType``，
    会造成事件串台（一个工具的事件被另一个工具的 VM 误处理）。
    历史上 ``SlideViewModel`` 曾误监听 ``CHECK_FAILED``（属 SimilarityChecker），
    已解耦（见 docs/architecture.md §8 问题 #3）。新增工具时务必新增专属类型
    （如 ``MYTOOL_PROGRESS``），切勿借用既有类型。
    """
    CHECK_STARTED = "check_started"
    CHECK_PROGRESS = "check_progress"
    CHECK_COMPLETED = "check_completed"
    CHECK_FAILED = "check_failed"
    EXTRACT_COMPLETED = "extract_completed"
    EXTRACT_FAILED = "extract_failed"
    PPTX_PROGRESS = "pptx_progress"
    PPTX_COMPLETED = "pptx_completed"
    PPTX_FAILED = "pptx_failed"
    EXAM_PROGRESS = "exam_progress"
    EXAM_COMPLETED = "exam_completed"
    EXAM_FAILED = "exam_failed"
    PDF_PROGRESS = "pdf_progress"
    PDF_COMPLETED = "pdf_completed"
    PDF_FAILED = "pdf_failed"
    WORD_PROGRESS = "word_progress"
    WORD_COMPLETED = "word_completed"
    WORD_FAILED = "word_failed"


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
    """1对多模式下，某题命中的副文档来源。

    ``index`` 仅用于主文档内部查重（internal=True）场景，指向与之重复的
    文档内第 N 题；常规 1对多（主文档 vs 副文档）下为 None。
    """
    file: str
    score: float
    reason: str
    index: Optional[int] = Field(
        default=None,
        description="命中题在源文档中的题号（主文档内部查重时指向文档内第 N 题）",
    )


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
    internal: bool = Field(
        default=False,
        description="是否为主文档内部查重（副文档未传入时触发，details 的 source.index 指向文档内题号）",
    )


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


class GenerateExamRequest(BaseModel):
    """从 JSON 题目数据生成 Word 题本与解析文档。

    排版设置（字体 / 字号 / 行间距 / 首行缩进）对题本文档与解析文档同时生效。
    """

    input_path: str = Field(..., description="输入 JSON 题目数据文件路径")
    output_dir: str = Field(
        "", description="输出目录；为空时默认与输入 JSON 同目录"
    )
    font_name: str = Field(
        "宋体/Times New Roman", description="字体（CJK / Latin 组合名）"
    )
    font_size_name: str = Field("五号", description="Word 字号名（如 五号 / 小四）")
    line_spacing_type: ExamLineSpacingType = ExamLineSpacingType.ONE_HALF
    line_spacing_value: float = Field(
        1.5, ge=0.1, le=5.0, description="自定义行距倍数（仅 line_spacing_type=CUSTOM 时生效）"
    )
    first_line_indent: bool = Field(
        True, description="首行缩进 2 字符（开启时题本/解析正文段落缩进）"
    )


class GenerateExamResult(BaseModel):
    """试卷（题本 + 解析）生成结果。"""
    question_book_path: str
    analysis_path: str
    question_count: int
    failed_images: List[str] = Field(
        default_factory=list,
        description="下载失败的图片 URL 列表；为空表示全部成功",
    )


class ConvertPdfRequest(BaseModel):
    """将 PDF 文档转换为可编辑文字的 PPTX（以模板母版为底）。

    转换策略（与 docs/pdf2pptx_final.py 定版管线一致）：
    - 以模板第 1 页所用版式为每页底子，继承母版/主题/图片背景；
    - 页面上只放可编辑文字框（保留字体/字号/颜色/粗斜体/坐标），不生成图片、
      不触碰页面级背景；
    - 坐标按 (slide 尺寸 / PDF 页面尺寸) 动态缩放，兼容任意尺寸 PDF。
    """

    pdf_path: str = Field(..., min_length=1, description="输入 PDF 文件路径")
    template_path: str = Field(..., min_length=1, description="PPT 模板路径（.pptx）")
    output_path: str = Field(..., min_length=1, description="输出 PPTX 文件路径")


class ConvertPdfResult(BaseModel):
    """PDF → PPTX 转换结果统计。"""

    output_path: str
    page_count: int = Field(ge=0, description="生成的幻灯片页数")
    textbox_count: int = Field(0, ge=0, description="生成的文本框总数")
    run_count: int = Field(0, ge=0, description="生成的文字 run 总数")
    empty_pages: List[int] = Field(
        default_factory=list,
        description="源 PDF 中无文字的页码（1-based，如纯图片封面页）",
    )


class ConvertPdfToWordRequest(BaseModel):
    """将 PDF 文档转换为可编辑文字的 Word（.docx）。

    转换策略（与 core/adapters/pdf_word_converter.py 一致）：
    - 按阅读顺序（块按 y、行内按 x）把 PDF 文字重排为普通段落；
    - 行内 run 保留字体/字号/颜色/粗斜体；
    - 可选 .docx 模板作基底文档，复用其样式 / 版面定义；
    - 首版纯文字，不提取图片（图片提取列为后续增强）。
    """

    pdf_path: str = Field(..., min_length=1, description="输入 PDF 文件路径")
    template_path: str = Field(
        "", description="可选 Word 模板路径（.docx）；为空则使用默认样式"
    )
    output_path: str = Field(..., min_length=1, description="输出 Word 文件路径（.docx）")


class ConvertPdfToWordResult(BaseModel):
    """PDF → Word 转换结果统计。"""

    output_path: str
    page_count: int = Field(ge=0, description="源 PDF 页数")
    paragraph_count: int = Field(0, ge=0, description="生成的段落总数")
    run_count: int = Field(0, ge=0, description="生成的文字 run 总数")
    empty_pages: List[int] = Field(
        default_factory=list,
        description="源 PDF 中无文字的页码（1-based，如纯图片封面页）",
    )


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
    """通用进度事件（查重/提取/PPT生成/试卷生成复用）。

    ``type`` 为**必填**（无默认值）：本字段允许 5 个取值，若带默认值，
    漏传 ``type`` 会静默落到 ``CHECK_PROGRESS``，被 ViewModel 的 ``_WATCHED``
    过滤后事件无声丢失（串台/丢事件，见 tests/test_event_contract.py）。
    """
    type: Literal[
        EventType.CHECK_PROGRESS, EventType.PPTX_PROGRESS,
        EventType.EXAM_PROGRESS, EventType.PDF_PROGRESS,
        EventType.WORD_PROGRESS,
    ]
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
    """查重/提取/PPT 生成失败事件（与 ProgressEvent 同理，type 必填无默认）。"""
    type: Literal[
        EventType.CHECK_FAILED, EventType.EXTRACT_FAILED, EventType.PPTX_FAILED
    ]
    message: str


class PptxCompletedEvent(_BaseEvent):
    type: Literal[EventType.PPTX_COMPLETED] = EventType.PPTX_COMPLETED
    result: GeneratePptxResult


class ExamCompletedEvent(_BaseEvent):
    """试卷生成完成事件。"""
    type: Literal[EventType.EXAM_COMPLETED] = EventType.EXAM_COMPLETED
    result: GenerateExamResult


class PdfCompletedEvent(_BaseEvent):
    """PDF → PPTX 转换完成事件。"""
    type: Literal[EventType.PDF_COMPLETED] = EventType.PDF_COMPLETED
    result: ConvertPdfResult


class PdfFailedEvent(_BaseEvent):
    """PDF → PPTX 转换失败事件。"""
    type: Literal[EventType.PDF_FAILED] = EventType.PDF_FAILED
    message: str


class WordCompletedEvent(_BaseEvent):
    """PDF → Word 转换完成事件。"""
    type: Literal[EventType.WORD_COMPLETED] = EventType.WORD_COMPLETED
    result: ConvertPdfToWordResult


class WordFailedEvent(_BaseEvent):
    """PDF → Word 转换失败事件。"""
    type: Literal[EventType.WORD_FAILED] = EventType.WORD_FAILED
    message: str


class ExamFailedEvent(_BaseEvent):
    """试卷生成失败事件。"""
    type: Literal[EventType.EXAM_FAILED] = EventType.EXAM_FAILED
    message: str


# 事件联合类型（按 type 判别）
DomainEvent = Annotated[
    Union[
        CheckStartedEvent, CheckCompletedEvent, ExtractCompletedEvent,
        PptxCompletedEvent, ExamCompletedEvent, ExamFailedEvent,
        PdfCompletedEvent, PdfFailedEvent,
        WordCompletedEvent, WordFailedEvent,
        ProgressEvent, FailedEvent,
    ],
    Field(discriminator="type"),
]
