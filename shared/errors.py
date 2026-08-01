"""统一异常体系（零 Qt 依赖）。

core 抛出这些异常，ui 层捕获并转换为 FailedEvent / Toast 提示。
"""
from __future__ import annotations


class ToolboxError(Exception):
    """所有业务异常的基类。"""


class DocumentReadError(ToolboxError):
    """Word/PPT 文档读取失败。"""


class NoQuestionsExtracted(ToolboxError):
    """未从文档中提取到任何题目。"""


class SimilarityThresholdError(ToolboxError):
    """阈值参数非法。"""


class OutputOverwriteError(ToolboxError, ValueError):
    """输出路径与模板路径相同，拒绝以避免损坏模板。

    同时继承 ValueError，以兼容既有的「相同路径抛 ValueError」契约/测试。
    """


class PptxGenerationError(ToolboxError):
    """PPT 生成失败。"""


class PdfReadError(ToolboxError):
    """PDF 文档读取/解析失败。"""


class TemplateInvalidError(ToolboxError):
    """PPT 模板非法（如模板中没有幻灯片，无法确定参考版式）。"""


class OutputWriteError(ToolboxError):
    """试卷（题本 / 解析）写出失败（输出目录无写入权限、磁盘满等）。

    UI 层据此弹出「重新选择输出目录」的弹窗，区别于普通业务异常。
    """

    def __init__(self, message: str, output_dir: str = "") -> None:
        super().__init__(message)
        self.output_dir = output_dir
