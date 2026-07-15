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
