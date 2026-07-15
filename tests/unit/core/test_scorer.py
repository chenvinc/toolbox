"""题目打分逻辑的回归测试（承接 legacy test_similarity_logic 的打分部分）。

直接测试 core 层 score_questions（零 Qt 依赖，无需 offscreen 即可运行），
覆盖：相似/无关/完全相同/空输入四类场景。多对多查重命中场景由
tests/unit/core/test_similarity_service.py 覆盖。
"""
import unittest

from core.models.question import Question
from core.services._scorer import score_questions


def _q(lines):
    return Question(lines=list(lines))


class ScorerTests(unittest.TestCase):
    def test_similar_questions_score_highly(self):
        q1 = _q(["1. 中国的首都是什么？", "A. 北京", "B. 上海", "C. 广州", "D. 深圳"])
        q2 = _q(["1. 中国首都是哪一个城市？", "A. 北京", "B. 上海", "C. 广州", "D. 深圳"])
        result = score_questions(q1, q2)
        self.assertGreaterEqual(result.score, 0.8)

    def test_unrelated_questions_score_lowly(self):
        q1 = _q(["1. 中国的首都是什么？", "A. 北京", "B. 上海", "C. 广州", "D. 深圳"])
        q2 = _q(["1. 太阳从哪边升起？", "A. 东边", "B. 西边", "C. 南边", "D. 北边"])
        result = score_questions(q1, q2)
        self.assertLess(result.score, 0.7)

    def test_1_to_1_identical_scores_high(self):
        q = _q(["1. 下列哪个是 Python 关键字？", "A. class", "B. def",
                "C. if", "D. all of the above"])
        result = score_questions(q, _q(list(q.lines)))
        self.assertGreaterEqual(result.score, 0.9)

    def test_empty_input_no_crash(self):
        result = score_questions(Question(lines=[]), Question(lines=[]))
        self.assertIsInstance(result.score, float)
        self.assertGreaterEqual(result.score, 0.0)
        self.assertLessEqual(result.score, 1.0)
        self.assertIn("reason", result.reason)

    def test_field_equivalence_with_legacy(self):
        # 与 legacy score_question_pair 返回的子比率字段一一对应
        q1 = _q(["1. 下列哪个是 Python 关键字？", "A. class", "B. def",
                 "C. if", "D. all of the above"])
        q2 = _q(["3. Python 中用于定义函数的关键字是？", "A. func", "B. def",
                 "C. lambda", "D. function"])
        r = score_questions(q1, q2)
        for attr in ("score", "reason", "stem_ratio", "option_ratio",
                     "full_ratio", "token_ratio", "bigram_ratio"):
            self.assertTrue(hasattr(r, attr), f"缺少字段 {attr}")


if __name__ == "__main__":
    unittest.main()
