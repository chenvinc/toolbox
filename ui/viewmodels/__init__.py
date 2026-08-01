"""视图模型层：持有 core service，转换数据为 UI 友好格式，发射 Qt 信号。

ViewModel 只做胶水逻辑（命令转发 + 事件→信号桥接），不编写任何业务规则。
"""

from .base_viewmodel import BaseViewModel
from .similarity_viewmodel import SimilarityViewModel
from .slide_viewmodel import SlideViewModel
from .json_exam_viewmodel import JsonExamViewModel
from .pdf_slide_viewmodel import PdfSlideViewModel

__all__ = [
    "BaseViewModel",
    "SimilarityViewModel",
    "SlideViewModel",
    "JsonExamViewModel",
    "PdfSlideViewModel",
]
