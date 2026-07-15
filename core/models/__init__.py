"""领域模型（零 Qt 依赖）。

阶段3 引入结构化 Question 领域模型，替代裸 List[str] 在查重链路中的隐式传递。
"""
from __future__ import annotations

from .question import Question

__all__ = ["Question"]
