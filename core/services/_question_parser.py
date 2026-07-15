"""题目文本解析（纯逻辑，零 Qt / 零文件 IO 依赖）。

从段落文本列表中识别题号与选项，提取为题目行列表。
文件读取由 core/adapters/docx_loader.py 负责，本模块只消费字符串列表，
因此可在无 python-docx、无 GUI 的环境下单元测试。
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# 模块级常量
# ---------------------------------------------------------------------------

_VALID_QUESTION_NUM_MIN = 1
_VALID_QUESTION_NUM_MAX = 200
_COMMON_NUM_SEPS = r".．。、，,"


def _is_raw_regex(pattern: str) -> bool:
    """判断字符串是否已经是正则表达式（而非格式示例）。"""
    return bool(re.search(r"\\[dDwWsS]|[+*?\[\]{}^|()]", pattern))


def _build_num_regex(num_pattern: str) -> Tuple[Optional[str], bool]:
    """根据用户输入的题号格式构建正则表达式，返回 (regex_str, needs_validation)。"""
    if not num_pattern or not num_pattern.strip():
        return None, True
    if _is_raw_regex(num_pattern):
        return num_pattern, False
    m = re.match(r"\d+", num_pattern)
    if m:
        sep = num_pattern[m.end():]
        if sep and all(c in _COMMON_NUM_SEPS for c in sep):
            sep_class = _COMMON_NUM_SEPS + r"\-/～~·"
        else:
            sep_class = re.escape(sep) if sep else _COMMON_NUM_SEPS
        return r"\d+\s*[" + sep_class + r"]+", False
    return re.escape(num_pattern), False


def _build_opt_regex(opt_prefix: str) -> Optional[str]:
    """根据用户输入的选项前缀构建正则表达式。"""
    if not opt_prefix or not opt_prefix.strip():
        return None
    if _is_raw_regex(opt_prefix):
        return opt_prefix
    if re.fullmatch(r"[A-Za-z]\W", opt_prefix):
        return "[A-Za-z]" + re.escape(opt_prefix[1:])
    return re.escape(opt_prefix)


_BROAD_NUM_RE = re.compile(
    r"^\s*(\d(?:\s*\d)*)\s*"
    r"[.。,，、．\-/／～~—·⦁・･]+"
    r"\s*"
)
_BROAD_OPT_RE = re.compile(
    r"(?:[(（]\s*)?"
    r"[A-Da-d]"
    r"(?:\s*[.。,，、．)）])"
    r"(?:\s*[)）])?"
)


def _is_valid_question_num(num_str: str) -> bool:
    """校验题号是否在合理范围内（宽泛匹配模式专用）。"""
    try:
        n = int(re.sub(r"\s+", "", num_str))
    except ValueError:
        return False
    return _VALID_QUESTION_NUM_MIN <= n <= _VALID_QUESTION_NUM_MAX


def _split_inline_options(lines: List[str], opt_re: "re.Pattern[str]") -> List[str]:
    """将同一行内包含多个选项的文本拆分为多行。"""
    result: List[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            result.append(line)
            continue
        matches = list(opt_re.finditer(stripped))
        if len(matches) <= 1:
            result.append(line)
        else:
            first_start = matches[0].start()
            if first_start > 0:
                prefix = stripped[:first_start].strip()
                if prefix:
                    result.append(prefix)
            for i, m in enumerate(matches):
                start = m.start()
                if i + 1 < len(matches):
                    end = matches[i + 1].start()
                    result.append(stripped[start:end].rstrip())
                else:
                    result.append(stripped[start:].rstrip())
    return result


def _finish_question(lines: List[str], opt_re: "re.Pattern[str]") -> Optional[List[str]]:
    """完成一道题目的收集，并格式化为行列表。双重校验题干非空与至少2个选项。"""
    if not lines or not lines[0].strip():
        return None
    full_text = "\n".join(lines)
    if len(opt_re.findall(full_text)) < 2:
        return None
    return _split_inline_options(lines, opt_re)


def parse_questions(
    paragraphs: List[str], num_pattern: str, opt_prefix: str
) -> List[List[str]]:
    """从段落文本列表提取所有题目。

    Args:
        paragraphs: 文档段落纯文本列表（由 DocumentLoader 提供）。
        num_pattern: 题号格式示例（如 "1."）或原始正则；空串启用内置宽泛匹配。
        opt_prefix:  选项前缀示例（如 "A."）或原始正则；空串启用内置宽泛匹配。

    Returns:
        List[List[str]] — 每道题为一个行列表（题干 + 选项行）。
    """
    num_re_str, needs_validation = _build_num_regex(num_pattern)
    if num_re_str is None:
        num_re = _BROAD_NUM_RE
        needs_validation = True
    else:
        num_re = re.compile(r"^\s*" + num_re_str)

    opt_re_str = _build_opt_regex(opt_prefix)
    if opt_re_str is None:
        opt_re = _BROAD_OPT_RE
    else:
        opt_re = re.compile(opt_re_str)

    questions: List[List[str]] = []
    current_lines: List[str] = []
    collecting = False

    for text in paragraphs:
        if not text.strip():
            continue
        m = num_re.match(text)
        is_num_start = m is not None and (
            not needs_validation or _is_valid_question_num(m.group(1))
        )
        if is_num_start:
            if collecting and current_lines:
                q = _finish_question(current_lines, opt_re)
                if q is not None:
                    questions.append(q)
            current_lines = [text]
            collecting = True
        elif collecting:
            current_lines.append(text)

    if collecting and current_lines:
        q = _finish_question(current_lines, opt_re)
        if q is not None:
            questions.append(q)

    return questions
