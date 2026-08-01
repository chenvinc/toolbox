"""文件 IO 端口（零 Qt 依赖，便于 mock 注入）。

外部副作用（读取 Word/PPT、写文件）通过本协议注入，使 core/services
在无真实文件系统、无 GUI 环境下可单元测试。
具体实现（python-docx / python-pptx 封装）位于 core/adapters。
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Protocol, TYPE_CHECKING, runtime_checkable

from shared.contracts import (
    ConvertPdfRequest, ConvertPdfResult,
    GenerateExamRequest, GenerateExamResult,
)

if TYPE_CHECKING:
    from core.models.exam_question import ExamQuestion


@runtime_checkable
class DocumentLoader(Protocol):
    """加载 Word 文档段落文本。"""
    def load_paragraphs(self, path: str) -> List[str]:
        """返回文档所有段落的纯文本列表。"""
        ...


@runtime_checkable
class PptxWriter(Protocol):
    """PPT 写操作封装。"""
    def build(
        self,
        template_path: str,
        questions: List[List[str]],
        font_name: str,
        font_size: int,
        output_path: str,
        line_spacing: float,
        first_line_indent: bool,
        on_progress: Callable[[int, int], None],
    ) -> int:
        """基于模板为每道题生成两页幻灯片并保存，返回生成的页数。"""
        ...


@runtime_checkable
class PdfSlideConverter(Protocol):
    """PDF → PPTX 转换写操作封装（适配 pymupdf + python-pptx）。"""

    def convert(
        self,
        request: ConvertPdfRequest,
        on_progress: Callable[[int, int], None],
    ) -> ConvertPdfResult:
        """按定版管线执行转换并保存 PPTX，返回统计结果。

        ``on_progress(current_page, total_pages)`` 每处理一页回调一次。
        失败抛 ``PdfReadError`` / ``TemplateInvalidError`` 等业务异常。
        """
        ...


@runtime_checkable
class ExamDocxWriter(Protocol):
    """试卷（题本 + 解析）Word 文档写操作封装。"""
    def build(
        self,
        request: GenerateExamRequest,
        questions: List["ExamQuestion"],
        on_progress: Callable[[int, int], None],
        image_cache: Optional[Dict[str, Optional[bytes]]] = None,
    ) -> GenerateExamResult:
        """根据请求与题目数据生成题本与解析文档，返回输出路径。

        ``image_cache`` 为服务层并发预下载好的 ``url -> bytes|None`` 缓存；
        传入时适配器直接使用（不重复下载），否则走惰性回退下载。
        """
        ...
