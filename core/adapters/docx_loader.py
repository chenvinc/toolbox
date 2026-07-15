"""Word 文档加载适配器（封装 python-docx）。"""
from __future__ import annotations

from typing import List

from docx import Document

from core.ports.io import DocumentLoader


class DocxLoaderAdapter(DocumentLoader):
    """通过 python-docx 读取文档段落文本。"""

    def load_paragraphs(self, path: str) -> List[str]:
        doc = Document(path)
        return [para.text for para in doc.paragraphs]
