"""业务服务端口（零 Qt 依赖）。

接口方法禁止返回任何 UI 对象（QPixmap / QWidget / Signal 等）。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from shared.contracts import (
    ExtractQuestionsRequest, ExtractQuestionsResult,
    GeneratePptxRequest, GeneratePptxResult,
    SimilarityRequest, SimilarityResult,
)


@runtime_checkable
class SimilarityService(Protocol):
    """题目查重服务。"""
    def check(self, request: SimilarityRequest) -> SimilarityResult:
        """同步执行查重，返回结构化结果。"""
        ...


@runtime_checkable
class ExtractionService(Protocol):
    """Word 题目提取服务。"""
    def extract(self, request: ExtractQuestionsRequest) -> ExtractQuestionsResult:
        ...


@runtime_checkable
class PptxService(Protocol):
    """PPT 生成服务。"""
    def generate(self, request: GeneratePptxRequest) -> GeneratePptxResult:
        ...
