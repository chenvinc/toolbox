"""文件 IO 端口（零 Qt 依赖，便于 mock 注入）。

外部副作用（读取 Word/PPT、写文件）通过本协议注入，使 core/services
在无真实文件系统、无 GUI 环境下可单元测试。
具体实现（python-docx / python-pptx 封装）位于 core/adapters。
"""
from __future__ import annotations

from typing import Callable, List, Protocol, runtime_checkable


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
