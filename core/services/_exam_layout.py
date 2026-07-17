"""试卷排版辅助（零 Qt 依赖）。

集中维护「Word 字号名 → 磅值」映射与「行间距预设 → 倍数」解析，
供 core/services 与 core/adapters 复用，避免拼写/语义分散。
"""
from __future__ import annotations

from typing import Dict

from shared.contracts import ExamLineSpacingType

# Word 中文字号名 → 磅值（pt）。来源：Word 字号标准对照表。
WORD_FONT_SIZE_NAME_TO_PT: Dict[str, float] = {
    "初号": 42.0,
    "小初": 36.0,
    "一号": 26.0,
    "小一": 24.0,
    "二号": 22.0,
    "小二": 18.0,
    "三号": 16.0,
    "小三": 15.0,
    "四号": 14.0,
    "小四": 12.0,
    "五号": 10.5,
    "小五": 9.0,
    "六号": 7.5,
    "小六": 6.5,
    "七号": 5.5,
    "八号": 5.0,
}

# 字号下拉框的可选项（与上方映射键一致，按从大到小排列）。
WORD_FONT_SIZE_NAMES: list[str] = list(WORD_FONT_SIZE_NAME_TO_PT.keys())


def resolve_font_size_pt(font_size_name: str) -> float:
    """将 Word 字号名解析为磅值；未命中时回退到「五号」(10.5pt)。"""
    return WORD_FONT_SIZE_NAME_TO_PT.get(font_size_name, WORD_FONT_SIZE_NAME_TO_PT["五号"])


def resolve_exam_line_spacing(preset: "ExamLineSpacingType | str", custom_value: float) -> float:
    """根据行间距预设解析为实际倍数。

    Args:
        preset: 行间距预设（枚举或枚举值字符串）。
        custom_value: ``CUSTOM`` 时使用的倍数。

    Returns:
        行间距倍数（1.0 / 1.5 / 2.0 / 自定义值）。
    """
    value = preset.value if isinstance(preset, ExamLineSpacingType) else preset
    if value == ExamLineSpacingType.ONE_HALF.value:
        return 1.5
    if value == ExamLineSpacingType.DOUBLE.value:
        return 2.0
    if value == ExamLineSpacingType.CUSTOM.value:
        return custom_value
    return 1.0
