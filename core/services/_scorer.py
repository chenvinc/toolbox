"""题目相似度打分（纯逻辑，零 Qt / 零文件 IO 依赖）。

本模块是从 legacy ``similarity_checker.score_question_pair`` 迁移而来，
打分公式与阈值分支**完全保持一致**，以确保迁移零语义偏差。
输入为 Question 领域对象，内部提取 lines 计算，输出结构化 QuestionScore。
"""
from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher
from typing import List, Tuple

from shared.contracts import QuestionScore
from core.models.question import Question


_WHITESPACE_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^\u4e00-\u9fffA-Za-z0-9]+")


def _normalize_text(text: str) -> str:
    """对题目文本做统一的规范化处理，降低标点和空白差异带来的误判。"""
    if not text:
        return ""
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("‘", "'").replace("’", "'")
    text = text.replace("（", "(").replace("）", ")")
    text = text.replace("【", "[").replace("】", "]")
    text = text.replace("：", ":").replace("；", ";")
    text = text.replace("，", ",").replace("。", ".")
    text = text.replace("、", ",")
    text = _WHITESPACE_RE.sub("", text)
    text = _NON_ALNUM_RE.sub("", text)
    return text.lower()


def _split_question_parts(q_lines: List[str]) -> Tuple[str, str]:
    """将题目拆成题干和选项两部分，便于分别计算相似度。"""
    lines = [line.strip() for line in q_lines if str(line).strip()]
    if not lines:
        return "", ""

    stem_lines: List[str] = []
    option_lines: List[str] = []
    for line in lines:
        if re.match(r"^([A-Z]|[\u4e00-\u9fff])([.、)）])", line):
            option_lines.append(line)
        else:
            stem_lines.append(line)

    if not stem_lines and lines:
        stem_lines = [lines[0]]
    stem = "\n".join(stem_lines)
    options = "\n".join(option_lines)
    return stem, options


def _char_bigram_overlap(a: str, b: str) -> float:
    """用字符级 bigram 的 Jaccard 相似度做轻量级语义近似。"""
    if not a or not b:
        return 0.0
    a_grams = {a[i:i + 2] for i in range(len(a) - 1)}
    b_grams = {b[i:i + 2] for i in range(len(b) - 1)}
    if not a_grams and not b_grams:
        return 0.0
    return len(a_grams & b_grams) / len(a_grams | b_grams)


def _token_overlap(a: str, b: str) -> float:
    """基于字符 token 的重叠率做辅助打分。"""
    if not a or not b:
        return 0.0
    a_tokens = Counter(_normalize_text(a))
    b_tokens = Counter(_normalize_text(b))
    if not a_tokens and not b_tokens:
        return 0.0
    union = set(a_tokens) | set(b_tokens)
    if not union:
        return 0.0
    inter = set(a_tokens) & set(b_tokens)
    return len(inter) / len(union)


def score_questions(qa: Question, qb: Question) -> QuestionScore:
    """为一对题目计算相似度分数，返回可解释的结构化结果。

    Args:
        qa: 题目 A（Question 领域对象）。
        qb: 题目 B（Question 领域对象）。

    Returns:
        QuestionScore：包含总分与各项子比率（stem/option/full/token/bigram）。
    """
    lines_a = qa.lines
    lines_b = qb.lines
    stem_a, options_a = _split_question_parts(lines_a)
    stem_b, options_b = _split_question_parts(lines_b)

    stem_a_norm = _normalize_text(stem_a)
    stem_b_norm = _normalize_text(stem_b)
    option_a_norm = _normalize_text(options_a)
    option_b_norm = _normalize_text(options_b)
    full_a_norm = _normalize_text("\n".join(lines_a))
    full_b_norm = _normalize_text("\n".join(lines_b))

    stem_ratio = SequenceMatcher(None, stem_a_norm, stem_b_norm).ratio()
    option_ratio = SequenceMatcher(None, option_a_norm, option_b_norm).ratio()
    full_ratio = SequenceMatcher(None, full_a_norm, full_b_norm).ratio()
    token_ratio = _token_overlap(stem_a_norm, stem_b_norm)
    bigram_ratio = _char_bigram_overlap(stem_a_norm, stem_b_norm)

    score = 0.5 * full_ratio + 0.25 * stem_ratio + 0.15 * token_ratio + 0.1 * bigram_ratio

    if option_a_norm and option_b_norm:
        score = max(score, 0.55 * stem_ratio + 0.45 * option_ratio)

    if option_a_norm and option_b_norm and option_ratio >= 0.9 and stem_ratio >= 0.5:
        score += 0.15
    elif stem_ratio >= 0.7 and full_ratio >= 0.75:
        score += 0.05

    if stem_ratio >= 0.8 and (option_ratio >= 0.8 or bigram_ratio >= 0.7):
        score = max(score, 0.86)
    if stem_ratio >= 0.95 and option_ratio >= 0.9:
        score = max(score, 0.95)

    score = min(1.0, max(0.0, score))

    reason = "低相似"
    if score >= 0.9:
        reason = "高度相似"
    elif score >= 0.8:
        reason = "较高相似"
    elif score >= 0.7:
        reason = "中等相似"

    return QuestionScore(
        score=round(score, 4),
        reason=reason,
        stem_ratio=round(stem_ratio, 4),
        option_ratio=round(option_ratio, 4),
        full_ratio=round(full_ratio, 4),
        token_ratio=round(token_ratio, 4),
        bigram_ratio=round(bigram_ratio, 4),
    )
