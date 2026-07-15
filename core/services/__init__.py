"""业务服务实现（零 Qt 依赖）。"""

from .similarity_service import SimilarityServiceImpl
from .slide_builder import ExtractionServiceImpl, PptxServiceImpl

__all__ = [
    "SimilarityServiceImpl",
    "ExtractionServiceImpl",
    "PptxServiceImpl",
]
