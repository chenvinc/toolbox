"""JSON 题目数据解析（零 Qt 依赖，无文件副作用）。

将粉笔题库导出的 JSON 解析为结构化题目列表（ExamQuestion）。
重点处理项：
  - 题干 / 解析来自 ``contentHtml``（或回退 ``questionStem`` / ``solution.analysis``），
    需剥离所有 HTML 标签、Angular 组件属性（``_ngcontent-*``）与内联样式，
    并把 ``<img>`` 替换为 ``[IMGn]`` 占位符（n 由 images 数组的 index 决定）。
  - 选项为 dict（``{A:{text,html}, ...}``）或 list，提取纯文本并格式化为 ``A. xxx``。
  - 正确率归一化为百分比字符串（``"38 %"`` → ``"38%"``）。
  - 答案取自 ``correctAnswer``（兼容旧字段 ``answer``）。
  - images 数组按 index 建立占位符→URL 映射，并记录 role / isTex。

文件读取与异常包装由调用方（service）负责。
"""
from __future__ import annotations

import html as _html
import json
import re
from typing import Any, Dict, List, Tuple

from shared.errors import DocumentReadError, NoQuestionsExtracted

from core.models.exam_question import ExamImage, ExamQuestion

# 选项键的稳定排序（A→B→C→D…），保证题本输出顺序一致。
_OPTION_ORDER = ["A", "B", "C", "D", "E", "F", "G", "H"]

# HTML 剥离相关正则
_BLOCK_CLOSE_RE = re.compile(r"</(p|div|h[1-6]|li|tr|table)>", re.I)
_BR_RE = re.compile(r"<br\s*/?>", re.I)
# 图片标签：<img ...> 或 Angular <image-viewer ...> 等以 image 开头的标签
_IMG_RE = re.compile(r"<img\b[^>]*>|<image\b[^>]*>", re.I)
_SRC_RE = re.compile(r'src\s*=\s*["\']([^"\']*)["\']', re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def _normalize_src(src: str) -> str:
    """归一化图片地址：``//host/...`` 与 ``http://`` 统一为 ``https://`` 以便匹配。"""
    s = (src or "").strip()
    if s.startswith("//"):
        return "https:" + s
    if s.startswith("http://"):
        return "https:" + s[len("http://"):]
    return s


def _strip_html(raw_html: str, images: List[Dict[str, Any]]) -> str:
    """把 HTML 转为纯文本，并把 ``<img>`` 替换为与 images 数组 index 对应的 ``[IMGn]``。

    - 移除所有标签、Angular 属性（``_ngcontent-*`` 等）、内联样式。
    - 块级结束标签 / ``<br>`` 转为换行，保留段落结构。
    - ``<img src=...>`` 通过 src 匹配 images 数组得到 index，渲染为 ``[IMG{index}]``；
      无法匹配时退化为顺序编号（并保留计数避免与题干预解析混淆）。
    - 文本中的字面 ``[IMGn]``（如 solution.analysis 已带占位符）不受影响，直接保留。
    """
    if not raw_html:
        return ""

    # 建立 src -> index 映射（用于把 <img> 对应到正确的 [IMGn]）
    src_to_index: Dict[str, int] = {}
    for im in images:
        s = _normalize_src(im.get("src", ""))
        if s:
            idx = im.get("index")
            if isinstance(idx, int):
                src_to_index[s] = idx

    counter = [0]

    def _replace_img(match: "re.Match[str]") -> str:
        tag = match.group(0)
        sm = _SRC_RE.search(tag)
        if sm:
            idx = src_to_index.get(_normalize_src(sm.group(1)))
            if idx is not None:
                return f"[IMG{idx}]"
        counter[0] += 1
        return f"[IMG{counter[0]}]"

    text = _IMG_RE.sub(_replace_img, raw_html)
    text = _BLOCK_CLOSE_RE.sub("\n", text)
    text = _BR_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = _html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _strip_inline(raw: str) -> str:
    """选项等短文本的轻量去标签（图片直接丢弃，不生成占位符）。"""
    if not raw:
        return ""
    text = _TAG_RE.sub("", raw)
    return _html.unescape(text).strip()


def _option_text(val: Any) -> str:
    """从单个选项原始值中提取纯文本（兼容 dict(text/html) 与纯字符串）。"""
    if isinstance(val, str):
        return _strip_inline(val)
    if isinstance(val, dict):
        t = val.get("text")
        if t:
            return _strip_inline(str(t))
        return _strip_inline(val.get("html", "") or "")
    return ""


def _extract_options(raw_options: Any) -> Dict[str, str]:
    """提取并格式化选项为 ``{"A": "A. 186", "B": "B. 187", ...}``，空选项跳过。

    兼容两种结构：
      - dict：``{"A": {text, html}, ...}``（按字母序优先，再补非标准键）
      - list：``[{key/text/html}, ...]``（按出现顺序分配 A/B/C/D）
    """
    if isinstance(raw_options, dict):
        items: List[Tuple[Any, Any]] = list(raw_options.items())
    elif isinstance(raw_options, list):
        items = [(None, v) for v in raw_options]
    else:
        return {}

    result: Dict[str, str] = {}
    letter_idx = 0
    for key, val in items:
        if isinstance(key, str) and key.strip():
            letter = key.strip()
        else:
            letter = _OPTION_ORDER[letter_idx] if letter_idx < len(_OPTION_ORDER) else str(letter_idx + 1)
        letter_idx += 1
        text = _option_text(val)
        if text:  # 空选项跳过
            result[letter] = f"{letter}. {text}"
    return result


def _format_correct_rate(raw: Any) -> str:
    """正确率归一化为百分比字符串：``"38 %"`` → ``"38%"``，``0.68`` → ``"68%"``。"""
    if raw is None:
        return ""
    s = str(raw).strip()
    if not s:
        return ""
    if "%" in s:
        return re.sub(r"\s+", "", s)  # 去掉 "38 %" 中的空格
    try:
        num = float(s)
    except ValueError:
        return s
    if 0 < num <= 1:  # 小数型百分比
        num *= 100
    return f"{round(num)}%"


def _to_exam_image(raw: Dict[str, Any]) -> ExamImage:
    """把 images 数组元素转为 ExamImage 领域模型。"""
    return ExamImage(
        index=int(raw.get("index", 0) or 0),
        src=str(raw.get("src", "") or ""),
        role=str(raw.get("role", "") or ""),
        is_tex=bool(raw.get("isTex", False)),
    )


def parse_exam_json(path: str) -> Tuple[List[ExamQuestion], str]:
    """解析 JSON 题目文件为题目列表与试卷标题。

    Args:
        path: JSON 文件路径。

    Returns:
        ``(questions, page_title)``；questions 至少包含 1 道题。

    Raises:
        DocumentReadError: 文件无法读取 / JSON 解析失败 / 结构非法。
        NoQuestionsExtracted: 未解析到任何题目。
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError as exc:
        raise DocumentReadError(f"文件不存在：{path}") from exc
    except json.JSONDecodeError as exc:
        raise DocumentReadError(f"JSON 解析失败：{path}（{exc}）") from exc
    except OSError as exc:
        raise DocumentReadError(f"文件读取失败：{path}（{exc}）") from exc

    if not isinstance(data, dict):
        raise DocumentReadError(f"JSON 顶层结构非法（应为对象）：{path}")

    raw_questions = data.get("questions")
    if not isinstance(raw_questions, list) or not raw_questions:
        raise NoQuestionsExtracted(f"未从 JSON 中提取到任何题目：{path}")

    page_title: str = data.get("pageTitle", "") or "专项练习"

    questions: List[ExamQuestion] = []
    for idx, q in enumerate(raw_questions):
        if not isinstance(q, dict):
            continue

        images: List[Dict[str, Any]] = q.get("images") or []
        # 题干：优先 contentHtml（含 HTML），其次 questionStem / contentText（已大致为纯文本）
        stem_html = q.get("contentHtml") or q.get("questionStem") or q.get("contentText") or ""
        stem = _strip_html(stem_html, images)

        options = _extract_options(q.get("options", {}) or {})

        solution = q.get("solution", {}) or {}
        analysis_html = solution.get("analysis", "") if isinstance(solution, dict) else ""
        analysis = _strip_html(analysis_html, images)

        correct_answer = str(q.get("correctAnswer") or q.get("answer") or "")
        correct_rate = _format_correct_rate(q.get("correctRate"))

        exam_images = [_to_exam_image(im) for im in images]

        questions.append(
            ExamQuestion(
                number=str(q.get("questionNumber", f"{idx + 1}.")),
                question_type=str(q.get("questionType", "")),
                stem=stem,
                options=options,
                correct_answer=correct_answer,
                correct_rate=correct_rate,
                analysis=analysis,
                images=exam_images,
            )
        )

    if not questions:
        raise NoQuestionsExtracted(f"未从 JSON 中提取到任何题目：{path}")

    return questions, page_title


def read_page_title(path: str) -> str:
    """仅读取试卷标题（不解析题目），读取失败时回退到默认标题。"""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return "专项练习"
    if isinstance(data, dict):
        return data.get("pageTitle", "") or "专项练习"
    return "专项练习"
