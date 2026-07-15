"""P0 #3 生成 PPT 的路径冲突校验与私有 API 加固的回归测试。

覆盖：
  1. 输出路径 == 模板路径时 generate_pptx 抛 ValueError（不覆盖/损坏模板）。
  2. 首张幻灯片 sldId 的 r:id 为 None 时 _remove_first_slide 不崩溃（修复点）。
  3. 正常模板（含 1 张首页）能被删除，生成的页数 = 2 * 题数。
  4. 0 张模板降级到 slide_layouts[-1]，仍能正常生成。
  5. 生成的 PPTX 可被 python-pptx 重新打开，文本已写入。

测试用 importlib 直接加载 utils（无 Qt 依赖，无需 offscreen 亦可运行）。
"""
import importlib.util
import os
import pathlib
import sys
import tempfile
import unittest

from pptx import Presentation
from pptx.oxml.ns import qn

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location("utils", ROOT / "utils.py")
_utils = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_utils)

generate_pptx = _utils.generate_pptx
_remove_first_slide = _utils._remove_first_slide
_same_path = _utils._same_path


QUESTIONS = [
    ["1. 第一题题干", "A. 选项一", "B. 选项二"],
    ["2. 第二题题干", "A. 选项甲", "B. 选项乙"],
]


def _make_template(path: str, n_slides: int = 1):
    """创建一个含 n_slides 张幻灯片的模板 pptx。"""
    prs = Presentation()
    for _ in range(n_slides):
        prs.slides.add_slide(prs.slide_layouts[0])
    prs.save(path)
    return path


class GeneratePptxP0Tests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="pptx_test_")

    def tearDown(self):
        for f in os.listdir(self._tmp):
            try:
                os.remove(os.path.join(self._tmp, f))
            except OSError:
                pass
        try:
            os.rmdir(self._tmp)
        except OSError:
            pass

    # ── 1. 路径冲突校验 ──
    def test_same_path_raises_value_error(self):
        tmpl = os.path.join(self._tmp, "t.pptx")
        _make_template(tmpl, 1)
        with self.assertRaises(ValueError) as ctx:
            generate_pptx(tmpl, QUESTIONS, "Arial", 24, tmpl)
        self.assertIn("相同", str(ctx.exception))
        # 模板未被破坏：仍可正常打开且页数未变
        self.assertEqual(len(Presentation(tmpl).slides), 1)

    # ── 2. rId 为 None 时不崩溃 ──
    def test_remove_first_slide_with_none_rid_does_not_crash(self):
        tmpl = os.path.join(self._tmp, "none_rid.pptx")
        _make_template(tmpl, 1)
        prs = Presentation(tmpl)
        # 主动移除首张 sldId 的 r:id 属性，复现崩溃前的前置条件
        sldId = prs.slides._sldIdLst[0]
        sldId.attrib.pop(qn("r:id"), None)
        self.assertIsNone(sldId.get(qn("r:id")))
        # 不应抛异常；首张幻灯片应被移除（或降级不崩溃）
        try:
            _remove_first_slide(prs)
        except Exception as e:  # pragma: no cover - 不应到达
            self.fail(f"_remove_first_slide 在 rId=None 时不应抛异常: {e}")
        # 若成功删除，页数应为 0；若降级，仍为 1 —— 两者均“未崩溃”
        self.assertIn(len(prs.slides), (0, 1))

    # ── 3. 正常删首页，页数正确 ──
    def test_normal_template_removes_first_slide(self):
        tmpl = os.path.join(self._tmp, "normal.pptx")
        _make_template(tmpl, 1)  # 1 张首页
        out = os.path.join(self._tmp, "out.pptx")
        generate_pptx(tmpl, QUESTIONS, "微软雅黑", 20, out)
        # 删除 1 张首页 + 每题 2 页 * 2 题 = 4 页
        self.assertEqual(len(Presentation(out).slides), 4)

    # ── 4. 0 张模板降级 ──
    def test_zero_slide_template_falls_back(self):
        tmpl = os.path.join(self._tmp, "zero.pptx")
        prs = Presentation()
        # 默认新建 Presentation 含 1 张，移除它得到 0 张模板
        sldId_lst = prs.slides._sldIdLst
        for s in list(sldId_lst):
            sldId_lst.remove(s)
        prs.save(tmpl)
        self.assertEqual(len(Presentation(tmpl).slides), 0)
        out = os.path.join(self._tmp, "out_zero.pptx")
        generate_pptx(tmpl, QUESTIONS, "Arial", 24, out)
        self.assertEqual(len(Presentation(out).slides), 4)

    # ── 5. 文本确实写入 ──
    def test_generated_text_present(self):
        tmpl = os.path.join(self._tmp, "txt.pptx")
        _make_template(tmpl, 1)
        out = os.path.join(self._tmp, "out_txt.pptx")
        generate_pptx(tmpl, QUESTIONS, "Arial", 24, out)
        texts = []
        for slide in Presentation(out).slides:
            for shape in slide.shapes:
                if shape.has_text_frame:
                    texts.append(shape.text_frame.text)
        blob = "\n".join(texts)
        self.assertIn("第一题题干", blob)
        self.assertIn("选项甲", blob)

    # ── 辅助函数 ──
    def test_same_path_helper(self):
        self.assertTrue(_same_path("/a/b.pptx", "/a/b.pptx"))
        self.assertFalse(_same_path("/a/b.pptx", "/a/c.pptx"))


if __name__ == "__main__":
    unittest.main()
