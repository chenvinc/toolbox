"""题目领域模型（零 Qt 依赖）。

阶段3 引入结构化 Question，替代裸 ``List[str]`` 在查重链路中的隐式传递。
携带 ``source_file`` / ``index`` 便于结果回溯到原始文档与题号。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class Question:
    """领域模型：一道题目。

    Attributes:
        lines: 题目文本行列表（题干 + 选项行），与解析层 / 打分层契约一致。
        source_file: 来源文档名（basename），用于查重结果回溯。
        index: 题号（1-based）；主文档场景下由服务层填充。
    """

    lines: List[str] = field(default_factory=list)
    source_file: str = ""
    index: int = 0

    @property
    def text(self) -> List[str]:
        """题目文本行（题干 + 选项），与 ``score_questions`` 契约一致。"""
        return self.lines
