import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MODULE_PATH = ROOT / "similarity_checker.py"

spec = importlib.util.spec_from_file_location("similarity_checker", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SimilarityLogicTests(unittest.TestCase):
    def test_similar_questions_score_highly(self):
        q1 = ["1. 中国的首都是什么？", "A. 北京", "B. 上海", "C. 广州", "D. 深圳"]
        q2 = ["1. 中国首都是哪一个城市？", "A. 北京", "B. 上海", "C. 广州", "D. 深圳"]
        result = module.score_question_pair(q1, q2)
        self.assertGreaterEqual(result["score"], 0.8)

    def test_unrelated_questions_score_lowly(self):
        q1 = ["1. 中国的首都是什么？", "A. 北京", "B. 上海", "C. 广州", "D. 深圳"]
        q2 = ["1. 太阳从哪边升起？", "A. 东边", "B. 西边", "C. 南边", "D. 北边"]
        result = module.score_question_pair(q1, q2)
        self.assertLess(result["score"], 0.7)


class SimilarityFixP0Tests(unittest.TestCase):
    """P0 #1 回归测试：验证 score_question_pair 始终收到 List[str]。

    覆盖三种场景：
      1. 1对1（完全相同题目）→ 高相似
      2. 1对多（主文档 + 多份副文档，其中一份重复）→ CheckerWorker 真实路径能命中
      3. 空输入（[], []）→ 不崩溃且返回合法分数
    """

    def test_1_to_1_identical_scores_high(self):
        q = ["1. 下列哪个是 Python 关键字？", "A. class", "B. def",
             "C. if", "D. all of the above"]
        result = module.score_question_pair(q, list(q))
        self.assertGreaterEqual(result["score"], 0.9)

    def test_empty_input_no_crash(self):
        result = module.score_question_pair([], [])
        self.assertIsInstance(result["score"], float)
        self.assertGreaterEqual(result["score"], 0.0)
        self.assertLessEqual(result["score"], 1.0)
        self.assertIn("reason", result)

    def test_1_to_many_detects_duplicate_with_list_input(self):
        # 主文档：1 道题
        main_q = ["1. 下列哪个是 Python 关键字？", "A. class", "B. def",
                  "C. if", "D. all of the above"]
        # 副文档 1：内容重复（仅换行/排版差异）
        dup_q = ["1. 下列哪个是 Python 关键字？", "A. class", "B. def",
                 "C. if", "D. all of the above"]
        # 副文档 2：无关题目
        other_q = ["2. 中国的首都是哪里？", "A. 北京", "B. 上海",
                   "C. 广州", "D. 深圳"]

        fake_docs = {
            "main.docx": [main_q],
            "dup.docx": [dup_q],
            "other.docx": [other_q],
        }

        def fake_extract(path, num_pat, opt_pre):
            return fake_docs[path]

        original = module.extract_questions
        module.extract_questions = fake_extract
        try:
            from PySide6.QtWidgets import QApplication
            if QApplication.instance() is None:
                _app = QApplication([])  # 仅用于信号机制，不启动事件循环

            # 直接调用 run() 同步执行（不通过 start()），finished 信号同步触发
            worker = module.CheckerWorker(
                "main.docx", ["dup.docx", "other.docx"], "1.", "A.", 0.8
            )
            captured = {}
            worker.finished.connect(lambda res: captured.update(res))
            worker.run()
        finally:
            module.extract_questions = original

        self.assertNotIn("error", captured,
                         msg=f"unexpected error: {captured.get('error')}")
        self.assertEqual(captured["main_count"], 1)
        self.assertEqual(captured["duplicate_count"], 1)
        self.assertEqual(captured["details"][0]["sources"][0]["file"], "dup.docx")
        self.assertGreaterEqual(captured["details"][0]["sources"][0]["score"], 0.8)


if __name__ == "__main__":
    unittest.main()
