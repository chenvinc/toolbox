"""widgets.py 单元测试（R-7）：把 W-01~W-04 复现断言固化为回归用例，并为 8 个控件建立核心路径覆盖。

背景：此前 ``widgets.py``（871 行）**零测试覆盖**，R-8/R-9 的结构性重构等于无保护作业。
本文件在 R-8/R-9 之前建立安全网，并优先固化第二轮评审复现的 W 类缺陷：

- W-01：``AppButton`` 直接 ``setEnabled(False)`` 不得清空 ``set_actionable`` 设置的禁用原因；
- W-02：``StepperInput`` 的 ± 按钮点击必须对外发射 ``valueChanged``（旧实现仅改内部 spin，外层收不到）；
- W-03：``DropZone`` / ``MultiDropZone`` 传 ``theme=None`` 不得 ``AttributeError``（None 防护曾写半截）；
- W-04：``MultiDropZone.clear_all()`` 经 ``files_selected([])`` 表达清空，可被观测（非功能缺失）。

所有用例在 ``QT_QPA_PLATFORM=offscreen`` 下运行；构造控件前先确保 ``QApplication`` 存在。
"""
import sys
import unittest

from PySide6.QtWidgets import (
    QApplication, QDoubleSpinBox, QSpinBox, QLineEdit, QWidget,
)

from theme import Theme
from widgets import (
    AppButton,
    AnimatedButton,
    AnimatedProgressBar,
    StepperInput,
    ToastNotification,
    DropZone,
    MultiDropZone,
    ErrorDialog,
)


def _app():
    return QApplication.instance() or QApplication(sys.argv)


class AppButtonTests(unittest.TestCase):
    def test_w01_setEnabled_false_preserves_reason(self):
        """W-01 回归：外部直接 setEnabled(False) 不得清空禁用原因。"""
        _app()
        btn = AppButton(text="检查")
        btn.set_actionable(False, "请先选择文件")
        self.assertFalse(btn.isEnabled())
        self.assertEqual(btn.toolTip(), "请先选择文件")
        # 原 W-01 缺陷：此处 setEnabled(False) 会把 reason 清空
        btn.setEnabled(False)
        self.assertEqual(btn.toolTip(), "请先选择文件")
        # 重新启用应清空 reason
        btn.setEnabled(True)
        self.assertEqual(btn.toolTip(), "")
        self.assertTrue(btn.isEnabled())

    def test_set_actionable_true_clears_reason(self):
        _app()
        btn = AppButton(text="检查")
        btn.set_actionable(False, "原因")
        btn.set_actionable(True, "")
        self.assertEqual(btn.toolTip(), "")
        self.assertTrue(btn.isEnabled())

    def test_set_loading_restores_text(self):
        _app()
        # loading_text 由构造期决定（set_loading 的 reason 参数是禁用提示，不是加载文案）
        btn = AppButton(text="开始", loading_text="检测中...")
        btn.set_loading(True, "请稍候")
        self.assertEqual(btn.text(), "检测中...")
        self.assertFalse(btn.isEnabled())
        btn.set_loading(False)
        self.assertEqual(btn.text(), "开始")
        self.assertTrue(btn.isEnabled())

    def test_set_loading_idempotent_keeps_original(self):
        """重复 set_loading(True) 不应把已切换的加载文案误存为 _original_text。"""
        _app()
        btn = AppButton(text="原文本")
        btn.set_loading(True)
        btn.set_loading(True)  # 第二次调用
        btn.set_loading(False)
        self.assertEqual(btn.text(), "原文本")


class AnimatedButtonTests(unittest.TestCase):
    def test_theme_none_constructs(self):
        _app()
        b = AnimatedButton("转换", theme=None)
        self.assertIsNotNone(b)

    def test_loading_toggle(self):
        _app()
        b = AnimatedButton(text="转换")
        b.set_loading(True)
        self.assertEqual(b.text(), "转换中...")
        self.assertFalse(b.isEnabled())
        b.set_loading(False)
        self.assertEqual(b.text(), "转换")
        self.assertTrue(b.isEnabled())


class AnimatedProgressBarTests(unittest.TestCase):
    def test_callback_sets_value(self):
        _app()
        pb = AnimatedProgressBar()
        pb._on_anim_value(42)
        self.assertEqual(pb.value(), 42)

    def test_set_value_animated_no_raise(self):
        _app()
        pb = AnimatedProgressBar()
        pb.setValueAnimated(80)  # 动画需事件循环才推进，此处仅验证不抛异常


class StepperInputTests(unittest.TestCase):
    def test_w02_plus_emits_valueChanged_double(self):
        """W-02 回归：点击 + 必须对外发射 valueChanged（float）。"""
        _app()
        s = StepperInput()  # 默认 QDoubleSpinBox
        received = []
        s.valueChanged.connect(lambda v: received.append(v))
        s.plus_button.click()
        self.assertTrue(received, "点击 + 后 valueChanged 应至少发射一次")
        self.assertAlmostEqual(received[-1], s.value())

    def test_w02_plus_emits_valueChanged_spin(self):
        _app()
        s = StepperInput(spin=QSpinBox())
        received = []
        s.valueChanged.connect(lambda v: received.append(v))
        s.plus_button.click()
        self.assertTrue(received)
        self.assertAlmostEqual(received[-1], s.value())

    def test_value_passthrough(self):
        _app()
        s = StepperInput(spin=QDoubleSpinBox())
        s._spin.setValue(0.5)
        self.assertAlmostEqual(s.value(), 0.5)

    def test_theme_none_constructs(self):
        _app()
        s = StepperInput(theme=None)
        self.assertIsNotNone(s)

    def test_qlineedit_mode_step_and_clamp(self):
        _app()
        le = QLineEdit("0.5")
        s = StepperInput(
            spin=le, min_val=0.0, max_val=1.0, step=0.1, decimals=2, default_value=0.0
        )
        received = []
        s.valueChanged.connect(lambda v: received.append(v))
        s.plus_button.click()
        self.assertAlmostEqual(s.value(), 0.6)
        self.assertTrue(received)
        self.assertAlmostEqual(received[-1], 0.6)
        # 越界 clamp：连点到超过 max
        for _ in range(10):
            s.plus_button.click()
        self.assertAlmostEqual(s.value(), 1.0)


class ToastNotificationTests(unittest.TestCase):
    def test_theme_none_constructs(self):
        _app()
        toast = ToastNotification(None, theme=None)
        self.assertIsNotNone(toast)

    def test_show_message_sets_text(self):
        _app()
        parent = QWidget()
        parent.resize(400, 300)
        toast = ToastNotification(parent, theme=None)
        toast.show_message("保存成功", success=True)
        self.assertIn("保存成功", toast._label.text())


class DropZoneTests(unittest.TestCase):
    def test_w03_theme_none_no_crash(self):
        _app()
        dz = DropZone("拖拽文件", file_filter="文档 (*.docx)", theme=None)
        self.assertIsNotNone(dz)

    def test_set_file_allowed_and_clear(self):
        _app()
        dz = DropZone("拖拽文件", file_filter="文档 (*.docx)")
        cleared, invalid = [], []
        dz.file_cleared.connect(lambda: cleared.append(1))
        dz.invalid_file.connect(lambda p: invalid.append(p))

        self.assertTrue(dz.set_file("/tmp/a.docx"))
        self.assertEqual(dz.get_path(), "/tmp/a.docx")

        # 不合规扩展名：拒绝且不改变已选文件（invalid_file 广播）
        self.assertFalse(dz.set_file("/tmp/b.txt"))
        self.assertEqual(dz.get_path(), "/tmp/a.docx")
        self.assertTrue(invalid)

        # 清空
        dz.clear()
        self.assertEqual(dz.get_path(), "")
        self.assertTrue(cleared)

    def test_drop_event_emits_file_selected(self):
        """dropEvent 路径经 set_file + file_selected 广播（set_file 本身不发射）。"""
        from PySide6.QtCore import QUrl

        _app()

        class _StubMime:
            def __init__(self, urls):
                self._urls = urls

            def hasUrls(self):
                return bool(self._urls)

            def urls(self):
                return self._urls

        class _StubDropEvent:
            def __init__(self, url):
                self._mime = _StubMime([url])

            def mimeData(self):
                return self._mime

        dz = DropZone("拖拽文件", file_filter="文档 (*.docx)")
        received = []
        dz.file_selected.connect(lambda p: received.append(p))
        # 必须用 fromLocalFile 构造，否则 toLocalFile() 在本 Qt 构建返回空串
        dz.dropEvent(_StubDropEvent(QUrl.fromLocalFile("/tmp/a.docx")))
        self.assertEqual(dz.get_path(), "/tmp/a.docx")
        self.assertEqual(received, ["/tmp/a.docx"])

    def test_is_allowed_empty_filter_accepts_all(self):
        _app()
        dz = DropZone("拖拽", file_filter="")
        self.assertTrue(dz._is_allowed("/tmp/anything.xyz"))


class MultiDropZoneTests(unittest.TestCase):
    def test_w03_theme_none_no_crash(self):
        _app()
        mz = MultiDropZone("拖拽文件", file_filter="文档 (*.docx)", theme=None)
        self.assertIsNotNone(mz)

    def test_add_and_remove(self):
        _app()
        mz = MultiDropZone("拖拽文件", file_filter="文档 (*.docx)")
        selected = []
        mz.files_selected.connect(lambda ps: selected.append(ps))
        mz._add_files(["/a.docx", "/b.docx"])
        self.assertEqual(mz.get_paths(), ["/a.docx", "/b.docx"])
        self.assertEqual(selected[-1], ["/a.docx", "/b.docx"])
        mz._remove_path("/a.docx")
        self.assertEqual(mz.get_paths(), ["/b.docx"])
        self.assertEqual(selected[-1], ["/b.docx"])

    def test_w04_clear_all_emits_empty_list(self):
        """W-04 回归：清空经 files_selected([]) 表达，必须可被观测。"""
        _app()
        mz = MultiDropZone("拖拽文件", file_filter="文档 (*.docx)")
        selected, invalid = [], []
        mz.files_selected.connect(lambda ps: selected.append(ps))
        mz.invalid_file.connect(lambda p: invalid.append(p))
        mz._add_files(["/a.docx", "/b.docx"])
        self.assertEqual(mz.get_paths(), ["/a.docx", "/b.docx"])
        # 不合规文件被拒并广播 invalid_file
        mz._add_files(["/c.txt"])
        self.assertTrue(invalid)
        self.assertEqual(mz.get_paths(), ["/a.docx", "/b.docx"])
        # 清空：files_selected([]) 可被观测
        mz.clear_all()
        self.assertEqual(mz.get_paths(), [])
        self.assertEqual(selected[-1], [])


class ErrorDialogTests(unittest.TestCase):
    def test_construct_with_theme(self):
        _app()
        d = ErrorDialog(
            None, Theme(), title="出错了", message="解析失败",
            detail="行 3 出错", extra_label="选择目录",
        )
        self.assertEqual(d.windowTitle(), "出错了")

    def test_extra_clicked_signal(self):
        _app()
        d = ErrorDialog(None, Theme(), title="t", message="m", extra_label="选择目录")
        clicked = []
        d.extraClicked.connect(lambda: clicked.append(1))
        d._on_extra()
        self.assertTrue(clicked)


if __name__ == "__main__":
    unittest.main()
