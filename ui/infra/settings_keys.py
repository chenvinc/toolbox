"""QSettings 键名集中管理。

各工具的键名按其 ``QSettings(org, app)`` 作用域隔离（见各 View 的构造）。
此处仅集中字面量，**保持原字符串值不变**，避免破坏已有用户持久化设置；
同时消除散落字符串带来的拼写 / 命名不一致隐患（架构书 §8 问题 #8）。

命名规范：全小写 + 下划线，语义对齐——同一概念在各工具内使用相同键名
（如字体统一 ``font_name``、选项前缀统一 ``opt_prefix``）。
"""
from __future__ import annotations


class JsonExamKeys:
    """JsonExam 工具（QSettings org/app = "JsonExam"）。"""

    FONT_NAME = "font_name"
    FONT_SIZE_NAME = "font_size_name"
    LINE_SPACING_TYPE = "line_spacing_type"
    LINE_SPACING_VALUE = "line_spacing_value"
    FIRST_LINE_INDENT = "first_line_indent"  # 真布尔（v4.0 起，兼容旧 "true"/"false" 字符串）
    OUTPUT_DIR = "output_dir"


class SimilarityKeys:
    """SimilarityChecker 工具（QSettings org/app = "SimilarityChecker"）。"""

    THRESHOLD = "threshold"
    NUM_PATTERN = "num_pattern"
    OPT_PREFIX = "opt_prefix"


class SlideKeys:
    """Quiz2Slide 工具（QSettings org/app = "Quiz2Slide"）。"""

    QUESTION_NUM_FMT = "question_num_fmt"
    OPT_PREFIX = "opt_prefix"
    FONT_NAME = "font_name"


class PdfSlideKeys:
    """Pdf2Slide 工具（QSettings org/app = "Pdf2Slide"）。"""

    TEMPLATE_PATH = "template_path"
