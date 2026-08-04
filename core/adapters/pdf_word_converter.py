"""PDF → Word 转换适配器（封装 PyMuPDF + python-docx）。

实现 core/ports/io.PdfWordConverter。把 PDF 文字按阅读顺序重排为普通段落，
行内 run 保留字体 / 字号 / 颜色 / 粗斜体；可选 .docx 模板作基底文档复用其样式
（清空模板原有正文，写入转换结果）。首版纯文字，不提取图片（与 PdfSlideConverter
的「不栅格化」哲学一致）。

字体归一 / 粗斜体判定复用 PdfSlideConverter 的纯函数（clean_font / is_bold /
is_italic），避免重复实现。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List

import fitz  # PyMuPDF
from docx import Document
from docx.document import Document as _Document
from docx.oxml.ns import qn
from docx.shared import Pt
from docx.text.run import Run

from core.adapters.pdf_slide_converter import (
    clean_font,
    is_bold,
    is_italic,
)
from core.ports.io import PdfWordConverter
from shared.contracts import ConvertPdfToWordRequest, ConvertPdfToWordResult
from shared.errors import PdfReadError, TemplateInvalidError


def _clear_body(doc: _Document) -> None:
    """清空文档正文（段落与表格），保留节 / 样式 / 页眉页脚定义。

    套用模板时据此抹掉模板自带示例内容，仅留样式骨架。
    """
    body = doc.element.body
    for p in list(doc.paragraphs):
        el = p._p
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)
    for tbl in list(doc.tables):
        el = tbl._tbl
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)


def _set_run_format(
    run: Run,
    raw_font: str | None,
    size: float,
    color: int | None,
    flags: int,
) -> None:
    """为一个 Word run 设置字体 / 字号 / 颜色 / 粗斜体。

    同时写入 ``w:rFonts`` 的 ``eastAsia``，确保中文按 PDF 所用中文字体渲染。
    """
    name = clean_font(raw_font)
    run.font.name = name
    run.font.size = Pt(size)
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), name)
    rfonts.set(qn("w:ascii"), name)
    rfonts.set(qn("w:hAnsi"), name)
    if color is not None:
        c = int(color) & 0xFFFFFF
        from docx.dml.color import RGBColor

        run.font.color.rgb = RGBColor(  # type: ignore[no-untyped-call]
            (c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF
        )
    if is_bold(raw_font, flags):
        run.font.bold = True
    if is_italic(raw_font, flags):
        run.font.italic = True


class PdfWordConverterAdapter(PdfWordConverter):
    """按阅读顺序把 PDF 文字逐页搬进 .docx 的可编辑段落。"""

    def convert(
        self,
        request: ConvertPdfToWordRequest,
        on_progress: Callable[[int, int], None],
    ) -> ConvertPdfToWordResult:
        # 基底文档：模板复用其样式，否则空白默认样式。
        if request.template_path:
            try:
                doc = Document(request.template_path)
            except Exception as exc:
                raise TemplateInvalidError(f"模板打开失败：{exc}") from exc
            _clear_body(doc)
        else:
            doc = Document()
            _clear_body(doc)

        try:
            src = fitz.open(request.pdf_path)
        except Exception as exc:
            raise PdfReadError(f"PDF 打开失败：{exc}") from exc

        paragraphs = 0
        runs = 0
        empty_pages: List[int] = []

        try:
            total = int(src.page_count)
            for pi in range(total):
                page = src[pi]
                td = page.get_text("dict")

                # 阅读顺序：块按 y0、行内按 x0 排序（近似单栏/顺序版式）。
                blocks = [
                    b for b in td.get("blocks", []) if b.get("type") == 0
                ]
                blocks.sort(key=lambda b: (b["bbox"][1], b["bbox"][0]))

                page_has_text = False
                for block in blocks:
                    lines = sorted(
                        block.get("lines", []),
                        key=lambda ln: ln["bbox"][1],
                    )
                    for line in lines:
                        spans = [s for s in line.get("spans", []) if s.get("text")]
                        if not spans:
                            continue
                        spans.sort(key=lambda s: s["bbox"][0])

                        para = doc.add_paragraph()
                        for sp in spans:
                            run = para.add_run(sp["text"])
                            _set_run_format(
                                run,
                                sp.get("font"),
                                sp.get("size") or 12,
                                sp.get("color"),
                                sp.get("flags", 0),
                            )
                            runs += 1
                        paragraphs += 1
                        page_has_text = True

                if not page_has_text:
                    empty_pages.append(pi + 1)  # 纯图片页(如封面)，源 PDF 无文字

                on_progress(pi + 1, total)

            doc.save(request.output_path)
        finally:
            src.close()

        return ConvertPdfToWordResult(
            output_path=request.output_path,
            page_count=total,
            paragraph_count=paragraphs,
            run_count=runs,
            empty_pages=empty_pages,
        )
