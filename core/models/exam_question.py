"""试卷题目领域模型（零 Qt 依赖）。

表示从 JSON 题目数据解析出的单道题结构化信息，供 core/services 与
core/adapters 之间传递，避免在业务链路中隐式传递裸 dict / 嵌套结构。

图片以占位符 ``[IMGn]`` 形式存在于题干 / 解析文本中，``n`` 与 ``ExamImage.index``
对应；真实图片 URL、所属位置（题干 / 解析）与是否为公式图由 ``images`` 记录。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class ExamImage:
    """单张题目配图，与题干 / 解析文本中的 ``[IMGn]`` 占位符一一对应。"""

    index: int          # 占位符序号 n（对应文本中的 [IMGn]）
    src: str            # 图片 URL
    role: str           # "stem" 题干图 / "solution" 解析图
    is_tex: bool        # 是否为公式图片（LaTeX 渲染，如 isTex=true）


@dataclass
class ExamQuestion:
    """单道题目（题本与解析共用同一份结构化数据）。"""

    number: str                         # 题号，如 "1."（可能含小节前缀）
    question_type: str                  # 题型，如 "单选题"
    stem: str                           # 题干纯文本（已剥离 HTML，含 [IMGx] 占位符）
    options: Dict[str, str] = field(default_factory=dict)  # 选项，键为 "A"/"B"...，值为 "A. xxx" 格式化文本
    correct_answer: str = ""            # 正确答案，如 "D"
    correct_rate: str = ""              # 正确率百分比字符串，如 "38%"
    analysis: str = ""                  # 解析文本（已剥离 HTML，含 [IMGx] 占位符）
    images: List[ExamImage] = field(default_factory=list)  # 本题配图映射（按 index / role / isTex）
