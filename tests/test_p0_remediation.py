"""P0 整改回归测试。

覆盖 2026-08-02 P0 计划（R-1 ~ R-5）的最小可验证断言：

- R-1 AppButton.set_actionable(False, reason)：
  禁用态原因通过 ToolTip 暴露（禁用按钮永不触发 mousePressEvent，
  旧实现靠 mousePressEvent 弹 Tip 实为死代码）。
- R-2 DropZone / MultiDropZone 在 theme=None 时回落 Theme() 单例，
  不抛 AttributeError。
- R-3 StepperInput 对原生 QSpinBox / QDoubleSpinBox 透传 valueChanged(float)；
  similarity 阈值步进为单步 0.01（修复重复接线导致的 0.02 双步进）。
- R-4 QSettings 脏值（threshold="not-a-number"）/ 越界值不再使 View 构造
  抛 ValueError（应用无法启动），回落默认 / 区间夹紧。
- R-5 日志落地文件（RotatingFileHandler 写入用户数据目录 logs/toolbox.log），
  sys.excepthook 记录未捕获异常。
"""
import os
import sys
import unittest

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QApplication, QDoubleSpinBox, QSpinBox,
)

from theme import Theme
from widgets import AppButton, DropZone, MultiDropZone, StepperInput
from ui.infra.safe_settings import read_float, read_bool, read_str


def _app():
    return QApplication.instance() or QApplication(sys.argv)


class SafeSettingsTests(unittest.TestCase):
    """R-4 机制级回归：安全读取助手对脏值 / 越界 / 缺失的兜底。"""

    def test_dirty_float_falls_back(self):
        s = QSettings("P0Test", "SafeSettings")
        s.setValue("t", "not-a-number")
        self.assertEqual(read_float(s, "t", 0.8), 0.8)

    def test_valid_float_passes(self):
        s = QSettings("P0Test", "SafeSettings")
        s.setValue("t", 0.75)
        self.assertEqual(read_float(s, "t", 0.8), 0.75)

    def test_out_of_range_clamped(self):
        s = QSettings("P0Test", "SafeSettings")
        s.setValue("t", 5.0)
        self.assertEqual(read_float(s, "t", 0.8, lo=0.5, hi=1.0), 1.0)
        s.setValue("t", 0.1)
        self.assertEqual(read_float(s, "t", 0.8, lo=0.5, hi=1.0), 0.5)

    def test_nan_and_inf_fallback(self):
        s = QSettings("P0Test", "SafeSettings")
        s.setValue("t", float("nan"))
        self.assertEqual(read_float(s, "t", 0.8, lo=0.5, hi=1.0), 0.8)
        s.setValue("t", float("inf"))
        # 非有限值意义不明，回落默认而非夹紧
        self.assertEqual(read_float(s, "t", 0.8, lo=0.5, hi=1.0), 0.8)

    def test_missing_key_default(self):
        s = QSettings("P0Test", "SafeSettings")
        s.remove("missing")
        self.assertEqual(read_float(s, "missing", 0.9, lo=0.5, hi=1.0), 0.9)

    def test_bool_compat_with_string_true_false(self):
        s = QSettings("P0Test", "SafeSettings")
        s.setValue("b", "false")
        self.assertIs(read_bool(s, "b", True), False)
        s.setValue("b", "true")
        self.assertIs(read_bool(s, "b", True), True)
        s.setValue("b", True)
        self.assertIs(read_bool(s, "b", False), True)

    def test_str_none_fallback(self):
        s = QSettings("P0Test", "SafeSettings")
        s.setValue("o", None)
        self.assertEqual(read_str(s, "o", ""), "")
        s.setValue("o", 123)
        self.assertEqual(read_str(s, "o", ""), "123")


class AppButtonActionableTests(unittest.TestCase):
    """R-1 回归：禁用原因经 ToolTip 暴露，且启用/禁用状态与内部标志一致。"""

    @classmethod
    def setUpClass(cls):
        _app()

    def test_actionable_false_sets_tooltip_and_disables(self):
        btn = AppButton(theme=Theme(), text="检查")
        btn.set_actionable(False, "请先选择至少 2 份文档")
        self.assertFalse(btn.isEnabled())
        self.assertEqual(btn.toolTip(), "请先选择至少 2 份文档")
        self.assertFalse(btn._can_click)

    def test_actionable_true_re_enables_and_clears(self):
        btn = AppButton(theme=Theme(), text="检查")
        btn.set_actionable(False, "原因")
        btn.set_actionable(True, "")
        self.assertTrue(btn.isEnabled())
        self.assertEqual(btn.toolTip(), "")
        self.assertTrue(btn._can_click)

    def test_setEnabled_triggers_sync_via_changeEvent(self):
        btn = AppButton(theme=Theme(), text="检查")
        btn.set_actionable(False, "原因")
        # 直接改启用态（模拟外部 setEnabled）也应同步 tooltip/标志
        btn.setEnabled(True)
        self.assertTrue(btn._can_click)
        self.assertEqual(btn.toolTip(), "")


class DropZoneThemeNoneTests(unittest.TestCase):
    """R-2 回归：theme=None 时回落 Theme()，构造不抛 AttributeError。"""

    @classmethod
    def setUpClass(cls):
        _app()

    def test_drop_zone_with_none_theme(self):
        dz = DropZone(
            placeholder_text="拖拽文件", file_filter="All (*)",
            theme=None, variant="secondary",
        )
        self.assertIsNotNone(dz)

    def test_multi_drop_zone_with_none_theme(self):
        mz = MultiDropZone(
            placeholder_text="拖拽文件", file_filter="All (*)",
            theme=None, variant="secondary",
        )
        self.assertIsNotNone(mz)


class StepperInputSignalTests(unittest.TestCase):
    """R-3 回归：原生 SpinBox 的值变化透传为 valueChanged(float)。"""

    @classmethod
    def setUpClass(cls):
        _app()

    def test_double_spin_value_changed_emitted(self):
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 1.0)
        spin.setSingleStep(0.01)
        spin.setDecimals(2)
        stepper = StepperInput(spin=spin, theme=Theme())
        received = []
        stepper.valueChanged.connect(lambda v: received.append(v))
        spin.setValue(0.5)
        self.assertEqual(received, [0.5])

    def test_int_spin_value_changed_emitted(self):
        spin = QSpinBox()
        spin.setRange(0, 100)
        stepper = StepperInput(spin=spin, theme=Theme())
        received = []
        stepper.valueChanged.connect(lambda v: received.append(v))
        spin.setValue(7)
        self.assertEqual(received, [7.0])


class P0AppLevelRegressionTests(unittest.TestCase):
    """应用级回归：脏 QSettings 不崩溃启动；similarity 阈值单步 0.01。

    注意：必须先写脏值再构造 ToolboxApp，且本类自行持有 app 实例，
    不与 test_app_smoke 共享，避免互相污染 QSettings 读数。
    """

    @classmethod
    def setUpClass(cls):
        _app()
        # 模拟用户配置文件被写脏（崩溃残留 / 手改 / 跨版本格式变更）
        s = QSettings("SimilarityChecker", "SimilarityChecker")
        s.setValue("threshold", "not-a-number")
        from app import ToolboxApp
        cls.window = ToolboxApp()
        cls.sim = cls.window._tools[1]

    def test_dirty_threshold_boots_and_falls_back_to_default(self):
        # 脏值不得使 View 构造抛 ValueError；回落默认 0.8
        self.assertAlmostEqual(self.sim._threshold_spin.value(), 0.8, places=5)

    def test_threshold_steps_single_0_01_not_double(self):
        # R-3 修复：similarity 阈值步进为单步 0.01（曾因重复接线变为 0.02）
        val = self.sim._threshold_spin.value()
        self.sim._threshold_stepper.plus_button.click()
        self.assertAlmostEqual(
            self.sim._threshold_spin.value(), val + 0.01, places=5
        )


class LoggingInfraTests(unittest.TestCase):
    """R-5 回归：configure_logging() 落盘到用户数据目录 logs/toolbox.log，
    且未捕获异常经 sys.excepthook 写入该文件。

    注意：configure_logging() 全程只调用一次（setUpClass），避免重复
    添加 handler 与 QStandardPaths 在不同运行阶段解析出不同路径。
    """

    @classmethod
    def setUpClass(cls):
        import app as app_module

        cls.log_path = app_module.configure_logging()

    def test_configure_logging_writes_file(self):
        import logging

        logging.getLogger("toolbox.p0test").info("P0 日志回归自检")
        self.assertTrue(
            os.path.exists(self.log_path),
            f"configure_logging 后未生成日志文件：{self.log_path}",
        )
        with open(self.log_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("P0 日志回归自检", content)

    def test_excepthook_writes_uncaught_to_log(self):
        # 模拟一个未捕获异常，应被 sys.excepthook 写入日志
        def _boom():
            raise RuntimeError("P0 崩溃兜底自检")

        try:
            _boom()
        except RuntimeError:
            sys.excepthook(*sys.exc_info())

        with open(self.log_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("P0 崩溃兜底自检", content)
        self.assertIn("未捕获异常", content)


class LoggingHandleLifecycleTests(unittest.TestCase):
    """R-5 补强回归（第二轮补充意见 #2）：faulthandler 句柄必须由模块级变量
    持有、正常退出经 shutdown_logging() 释放；重复调用 configure_logging
    不得产生两个句柄指向同一文件。"""

    def test_double_call_releases_old_handle(self):
        import app as app_module

        p1 = app_module.configure_logging()
        fh1 = app_module._crash_log_fh
        self.assertIsNotNone(fh1, "首次 configure 后 crash.log 句柄应被持有")
        self.assertFalse(fh1.closed, "首次 configure 后句柄应处于打开状态")
        # 二次调用：应 disable + 关闭旧句柄，再开新句柄（任意时刻至多一个打开的句柄）
        p2 = app_module.configure_logging()
        self.assertEqual(p1, p2)
        fh2 = app_module._crash_log_fh
        self.assertIsNotNone(fh2)
        self.assertTrue(fh1.closed, "旧句柄应在二次 configure 时被关闭，避免两个句柄指向同一文件")
        self.assertIsNot(fh1, fh2, "二次 configure 应持有新句柄，而非复用已关闭的旧句柄")
        self.assertFalse(fh2.closed)
        # 释放后模块级变量归位，不残留打开的句柄
        app_module.shutdown_logging()
        self.assertIsNone(app_module._crash_log_fh)

    def test_shutdown_idempotent(self):
        import app as app_module

        app_module.configure_logging()
        app_module.shutdown_logging()
        # 二次 shutdown 必须安全（正常退出路径可能多次触发）
        app_module.shutdown_logging()
        self.assertIsNone(app_module._crash_log_fh)


if __name__ == "__main__":
    unittest.main()
