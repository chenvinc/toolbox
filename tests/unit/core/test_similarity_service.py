"""SimilarityServiceImpl 单元测试（无 Qt、无 python-docx，全部依赖经 mock 注入）。

验证：
  - 1对多：主文档与重复副文档命中、无关副文档不命中、阈值门控
  - 多对多：跨文档（cross）/ 文档内（internal）重复对识别
  - 空题目 / 不足 2 题 → 抛 NoQuestionsExtracted
  - 事件推送：CHECK_STARTED / CHECK_PROGRESS / CHECK_COMPLETED
"""
import unittest

from shared.contracts import (
    EventType, ManyToManyResult, OneToManyResult,
    SimilarityMode, SimilarityRequest,
)
from shared.errors import NoQuestionsExtracted
from core.services.similarity_service import SimilarityServiceImpl


class PathMapLoader:
    """按路径返回预设段落，模拟 DocumentLoader（python-docx 封装）。"""

    def __init__(self, mapping):
        self._mapping = {k: list(v) for k, v in mapping.items()}
        self.calls = []

    def load_paragraphs(self, path):
        self.calls.append(path)
        return list(self._mapping[path])


class CollectingEmitter:
    def __init__(self):
        self.events = []
        self._handlers = []

    def emit(self, event):
        self.events.append(event)
        for h in self._handlers:
            h(event)

    def on_event(self, handler):
        self._handlers.append(handler)


# 题目段落（能被 parse_questions 解析为 1 道题）
MAIN_PARA = [
    "1. 下列哪个是 Python 关键字？", "A. class", "B. def",
    "C. if", "D. all of the above",
]
DUP_PARA = list(MAIN_PARA)  # 与 MAIN 完全相同
OTHER_PARA = [
    "2. 中国的首都是哪里？", "A. 北京", "B. 上海",
    "C. 广州", "D. 深圳",
]
# 同一文档内的两道"相似"题（用于 internal 对测试）
SIM_PARA = [
    "1. 下列哪个是 Python 关键字？", "A. class", "B. def",
    "C. if", "D. all of the above",
    "2. 下面哪个属于 Python 关键字？", "A. class", "B. def",
    "C. if", "D. all of the above",
]


class OneToManyTests(unittest.TestCase):
    def _svc(self, mapping):
        return SimilarityServiceImpl(PathMapLoader(mapping), CollectingEmitter())

    def test_detects_duplicate_across_secondary(self):
        svc = self._svc({
            "main.docx": MAIN_PARA,
            "dup.docx": DUP_PARA,
            "other.docx": OTHER_PARA,
        })
        res = svc.check(SimilarityRequest(
            mode=SimilarityMode.ONE_TO_MANY,
            main_path="main.docx",
            secondary_paths=["dup.docx", "other.docx"],
            threshold=0.8,
        ))
        self.assertIsInstance(res, OneToManyResult)
        self.assertEqual(res.main_count, 1)
        self.assertEqual(res.duplicate_count, 1)
        self.assertEqual(res.details[0].sources[0].file, "dup.docx")
        self.assertGreaterEqual(res.details[0].sources[0].score, 0.8)
        # 无关副文档不应命中
        files = {s.file for s in res.details[0].sources}
        self.assertNotIn("other.docx", files)

    def test_threshold_gates_match(self):
        svc = self._svc({
            "main.docx": MAIN_PARA,
            "dup.docx": DUP_PARA,
        })
        # 把阈值提到 0.99，相同题目(=1.0)仍命中；但无关题不命中
        high = svc.check(SimilarityRequest(
            mode=SimilarityMode.ONE_TO_MANY,
            main_path="main.docx", secondary_paths=["dup.docx"],
            threshold=0.99,
        ))
        self.assertEqual(high.duplicate_count, 1)

    def test_main_without_questions_raises(self):
        svc = self._svc({"main.docx": ["这是一段没有题号的普通文本"]})
        with self.assertRaises(NoQuestionsExtracted):
            svc.check(SimilarityRequest(
                mode=SimilarityMode.ONE_TO_MANY,
                main_path="main.docx", secondary_paths=[],
                threshold=0.8,
            ))

    def test_emits_progress_and_completed_events(self):
        emitter = CollectingEmitter()
        svc = SimilarityServiceImpl(PathMapLoader({
            "main.docx": MAIN_PARA, "dup.docx": DUP_PARA,
        }), emitter)
        svc.check(SimilarityRequest(
            mode=SimilarityMode.ONE_TO_MANY,
            main_path="main.docx", secondary_paths=["dup.docx"],
            threshold=0.8,
        ))
        types = [e.type for e in emitter.events]
        self.assertIn(EventType.CHECK_STARTED, types)
        self.assertIn(EventType.CHECK_PROGRESS, types)
        self.assertIn(EventType.CHECK_COMPLETED, types)

    def test_internal_check_when_no_secondary(self):
        """未传入副文档 → 默认对主文档内部查重，识别文档内重复。"""
        svc = self._svc({"main.docx": SIM_PARA})
        res = svc.check(SimilarityRequest(
            mode=SimilarityMode.ONE_TO_MANY,
            main_path="main.docx", secondary_paths=[],  # 关键：无副文档
            threshold=0.8,
        ))
        self.assertIsInstance(res, OneToManyResult)
        self.assertTrue(res.internal, "应标记为内部查重")
        self.assertEqual(res.main_count, 2)
        self.assertEqual(res.duplicate_count, 1)
        self.assertEqual(res.details[0].index, 1)
        # 命中来源应指向文档内第 2 题
        self.assertEqual(res.details[0].sources[0].index, 2)
        self.assertGreaterEqual(res.details[0].sources[0].score, 0.8)

    def test_internal_check_no_duplicates(self):
        """主文档内无重复题时，内部查重返回 0 重复且仍标记 internal。"""
        svc = self._svc({"main.docx": MAIN_PARA + OTHER_PARA})
        res = svc.check(SimilarityRequest(
            mode=SimilarityMode.ONE_TO_MANY,
            main_path="main.docx", secondary_paths=[],
            threshold=0.8,
        ))
        self.assertTrue(res.internal)
        self.assertEqual(res.main_count, 2)
        self.assertEqual(res.duplicate_count, 0)
        self.assertEqual(res.details, [])


class ManyToManyTests(unittest.TestCase):
    def _svc(self, mapping):
        return SimilarityServiceImpl(PathMapLoader(mapping), CollectingEmitter())

    def test_cross_document_pair_detected(self):
        svc = self._svc({
            "a.docx": MAIN_PARA,
            "b.docx": DUP_PARA,   # 与 a 完全相同
            "c.docx": OTHER_PARA,
        })
        res = svc.check(SimilarityRequest(
            mode=SimilarityMode.MANY_TO_MANY,
            all_paths=["a.docx", "b.docx", "c.docx"],
            threshold=0.8,
        ))
        self.assertIsInstance(res, ManyToManyResult)
        self.assertEqual(res.total_questions, 3)
        self.assertEqual(res.document_count, 3)
        self.assertEqual(len(res.duplicate_pairs), 1)
        pair = res.duplicate_pairs[0]
        self.assertEqual(pair.pair_type, "cross")
        self.assertGreaterEqual(pair.score, 0.8)
        self.assertIn(pair.q1_file, ("a.docx", "b.docx"))

    def test_internal_pair_detected(self):
        svc = self._svc({"d.docx": SIM_PARA})
        res = svc.check(SimilarityRequest(
            mode=SimilarityMode.MANY_TO_MANY,
            all_paths=["d.docx"],
            threshold=0.8,
        ))
        self.assertEqual(res.total_questions, 2)
        self.assertEqual(len(res.duplicate_pairs), 1)
        self.assertEqual(res.duplicate_pairs[0].pair_type, "internal")

    def test_less_than_two_questions_raises(self):
        svc = self._svc({"only.docx": MAIN_PARA})
        with self.assertRaises(NoQuestionsExtracted):
            svc.check(SimilarityRequest(
                mode=SimilarityMode.MANY_TO_MANY,
                all_paths=["only.docx"], threshold=0.8,
            ))


if __name__ == "__main__":
    unittest.main()
