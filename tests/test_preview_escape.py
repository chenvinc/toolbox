"""P0 #2 预览 HTML 注入修复的回归测试。

验证 ui.infra.preview_escape 的预览渲染对来自用户文档的题面文本与字体名
做了正确转义：恶意标签/属性被实体化（不触发资源加载或布局破坏），同时仅
保留 <b>/<i>/<u>/<br> 白名单格式化标签；字体名（进入 <style> CSS 上下文）
被剔除可脱离 CSS 字符串的字符，防御 CSS 注入。

本测试从 legacy test_preview_escape 迁移而来，仅变更导入来源（模块已迁至
ui/infra/preview_escape），断言全部保留。
"""
import unittest

from ui.infra.preview_escape import escape_preview_line, sanitize_font_name


class PreviewEscapeTests(unittest.TestCase):
    # ── 1. 恶意标签被完全实体化（不形成可解析标签） ──
    def test_script_tag_neutralized(self):
        out = escape_preview_line("<script>alert(1)</script>")
        self.assertIn("&lt;script&gt;", out)
        self.assertNotIn("<script>", out)
        self.assertNotIn("</script>", out)

    def test_img_onerror_neutralized(self):
        out = escape_preview_line("<img src=x onerror=alert(1)>")
        self.assertIn("&lt;img", out)
        self.assertNotIn("<img", out)

    def test_js_link_neutralized(self):
        out = escape_preview_line("<a href='javascript:alert(1)'>click</a>")
        self.assertIn("&lt;a", out)
        self.assertNotIn("<a", out)

    # ── 2. 白名单格式化标签保留 ──
    def test_whitelist_tags_preserved(self):
        text = "标题 <b>加粗</b> 与 <br> 换行 <i>斜体</i> 与 <u>下划线</u>"
        out = escape_preview_line(text)
        self.assertIn("<b>加粗</b>", out)
        self.assertIn("<br>", out)
        self.assertIn("<i>斜体</i>", out)
        self.assertIn("<u>下划线</u>", out)

    def test_br_self_closing_variants_preserved(self):
        self.assertEqual(escape_preview_line("<br/>"), "<br/>")
        self.assertEqual(escape_preview_line("<br />"), "<br/>")

    def test_plain_text_and_entities(self):
        out = escape_preview_line("1+1 < 2 & 3 > 1")
        self.assertEqual(out, "1+1 &lt; 2 &amp; 3 &gt; 1")

    # ── 3. 字体名 CSS 上下文注入防护 ──
    def test_font_css_injection_blocked(self):
        evil = "'}; body { background: red; font-family: '"
        out = sanitize_font_name(evil)
        for forbidden in ("{", "}", ";", "'", '"', "`"):
            self.assertNotIn(forbidden, out)

    def test_font_style_breakout_blocked(self):
        evil = "x</style><script>alert(1)</script>"
        out = sanitize_font_name(evil)
        self.assertNotIn("</style>", out)
        self.assertIn("&lt;/style&gt;", out)

    def test_normal_font_names_untouched(self):
        for name in ("微软雅黑", "Arial", "Times New Roman"):
            self.assertEqual(sanitize_font_name(name), name)

    # ── 4. 集成：用辅助函数重建预览 HTML 片段并断言整体安全 ──
    def test_assembled_preview_html_is_safe(self):
        malicious_questions = [
            ["<script>alert('xss')</script>", "<img src=y onerror=alert(1)>"],
            ["正常题目 <b>重点</b>"],
        ]
        evil_font = "';</style><h1>hack</h1>"
        parts = []
        for i, q in enumerate(malicious_questions, 1):
            parts.append(f"<div class='q-header'>第 {i} 题</div>")
            for line in q:
                parts.append(f"<div class='q'>{escape_preview_line(line)}</div>")
        html = (
            "<html><head><meta charset='utf-8'>"
            f"<style>body{{font-family:'{sanitize_font_name(evil_font)}';}}</style>"
            "</head><body>" + "\n".join(parts) + "</body></html>"
        )
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&lt;/style&gt;", html)
        self.assertEqual(html.count("</style>"), 1)
        self.assertIn("<b>重点</b>", html)  # 白名单仍生效


if __name__ == "__main__":
    unittest.main()
