"""预览 HTML 安全转义（纯函数，零 Qt 依赖）。

QTextBrowser.setHtml 会解析富文本。用户文档中的 <script> / <img src onerror=...>
等标签可能触发资源加载或布局破坏；字体名进入 <style> 的 CSS 字符串上下文，
仅用 html.escape 无法防御 { } 注入。两个辅助函数分别处理正文与 CSS 上下文。

本模块从 legacy ``word_2_slide_tool`` 迁移而来，逻辑保持不变。
"""
from __future__ import annotations

import html as _html
import re as _re

# 仅保留的白名单格式化标签：<b> <i> <u> <br>（含 </b> 与 <br/> 变体）
_PREVIEW_SAFE_TAG_RE = _re.compile(r"&lt;(/?)(br|b|i|u)\b\s*(/?)&gt;", _re.IGNORECASE)


def escape_preview_line(text: str) -> str:
    """转义题面文本用于预览，仅保留 <b>/<i>/<u>/<br> 白名单标签。

    html.escape 把 < > & ' " 全部实体化，先杜绝任何标签/属性注入；
    再用白名单正则把安全的格式化标签还原回来。
    """
    escaped = _html.escape(text)
    return _PREVIEW_SAFE_TAG_RE.sub(r"<\1\2\3>", escaped)


def sanitize_font_name(font_name: str) -> str:
    """净化字体名（进入 <style> CSS 字符串上下文），防御 CSS 注入。

    字体名来自可编辑下拉框（用户可任意输入），先剔除能脱离 CSS 字符串或
    开启新规则的字符 { } ' " ` ;，再 html.escape 处理 < > & 等。
    """
    stripped = _re.sub(r"[{}\"'`;]", "", font_name or "")
    return _html.escape(stripped)
