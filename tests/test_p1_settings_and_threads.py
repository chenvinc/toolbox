"""P1 #4（阈值配置化）与 P1 #5（线程管理）的回归测试。

#4：验证 CheckerWorker 真正使用传入的 threshold 作为判定阈值（而非硬编码 0.8）。
    技巧：先用 score_question_pair 算出两题的实际相似度 s，再分别以
    s*0.8（应命中）与 min(0.99, s*1.1)（应不命中）作为阈值跑同一次查重，
    断言 duplicate_count 随阈值变化 —— 证明阈值已接线。

#5：验证相似度工具的 _stop_worker/stop_worker 在「无 worker」与「worker 运行中」
    两种情况下都能安全清理（不崩溃、self._worker 置空）。转换线程（Quiz2SlideTool）
    逻辑同源，已在代码审查层面覆盖，此处以相似度工具为代表验证。
"""
import importlib.util
import pathlib
import sys
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location(
    "similarity_checker", ROOT / "similarity_checker.py"
)
_sc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_sc)

CheckerWorker = _sc.CheckerWorker
score_question_pair = _sc.score_question_pair
SimilarityCheckerTool = _sc.SimilarityCheckerTool


def _qa():
    return ["1. 下列哪个是 Python 关键字？", "A. class", "B. def", "C. if", "D. all of the above"]


def _qb():
    # 与 q_a 共享 "def" 选项，但题干与其它选项不同 —— 相似但不相同（0 < s < 1）
    return ["3. Python 中用于定义函数的关键字是？", "A. func", "B. def", "C. lambda", "D. function"]


class P1ThresholdTests(unittest.TestCase):
    def test_threshold_is_wired_not_hardcoded(self):
        q_a, q_b = _qa(), _qb()
        s = score_question_pair(q_a, q_b)["score"]
        self.assertGreater(s, 0.0)
        self.assertLess(s, 1.0)  # 两题相似但不完全相同

        main_path, sec_path = "main.docx", "sec.docx"

        def fake_extract(path, num_pat, opt_pre):
            if path == main_path:
                return [list(q_a)]
            return [list(q_b)]

        # 以真实相似度 s 为中心动态取阈值，证明它是判定边界（而非硬编码 0.8）
        low = s * 0.5                      # 低于真实相似度 → 应命中
        high = s + (1.0 - s) * 0.5         # 高于真实相似度且 < 1.0 → 应不命中

        with patch.object(_sc, "extract_questions", fake_extract):
            w_low = CheckerWorker(main_path, [sec_path], "1.", "A.", low)
            cap_low = {}
            w_low.finished.connect(lambda r: cap_low.update(r))
            w_low.run()

            w_high = CheckerWorker(main_path, [sec_path], "1.", "A.", high)
            cap_high = {}
            w_high.finished.connect(lambda r: cap_high.update(r))
            w_high.run()

        self.assertNotIn("error", cap_low)
        self.assertEqual(cap_low["duplicate_count"], 1,
                         f"阈值 {low:.3f}（< 相似度 {s:.3f}）应命中重复")
        self.assertNotIn("error", cap_high)
        self.assertEqual(cap_high["duplicate_count"], 0,
                         f"阈值 {high:.3f}（> 相似度 {s:.3f}）不应命中重复")


class P1ThreadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls._app = QApplication(sys.argv)
        else:
            cls._app = QApplication.instance()

    def test_stop_worker_noop_when_none(self):
        tool = SimilarityCheckerTool()
        try:
            # 无 worker 时调用不应崩溃，且保持 None
            tool.stop_worker()
            self.assertIsNone(tool._worker)
        finally:
            tool.deleteLater()

    def test_stop_worker_cleans_running_worker(self):
        tool = SimilarityCheckerTool()
        try:
            # 准备输入并启动一次真实后台查重（extract_questions 被打桩，秒回）
            tool._main_path = "main.docx"
            tool._secondary_paths = ["sec.docx"]

            def fake_extract(path, num_pat, opt_pre):
                if path == "main.docx":
                    return [list(_qa())]
                return [list(_qb())]

            with patch.object(_sc, "extract_questions", fake_extract):
                tool._start_one_to_many()  # 内部会 start() 后台线程
                self.assertIsNotNone(tool._worker)
                self.assertTrue(tool._worker.isRunning())
                # 中途停止：应 wait 至结束并 deleteLater，最终置空
                tool._stop_worker()
                self.assertIsNone(tool._worker)
        finally:
            tool.deleteLater()


if __name__ == "__main__":
    unittest.main()
