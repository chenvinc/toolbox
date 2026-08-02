"""题目查重服务实现（零 Qt 依赖）。

通过注入的 DocumentLoader 读取文档、复用 parse_questions 解析题目，
再调用 score_questions 打分，构造结构化结果并推送事件。
失败以业务异常形式抛出（由 ViewModel 的 on_async_error 桥接为失败信号），
与既有 PptxServiceImpl 行为一致，避免与事件通道重复投递。
"""
from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

import os
from typing import Dict, List, Literal, Tuple

from shared.contracts import (
    CheckCompletedEvent, CheckStartedEvent, EventType, ManyToManyResult,
    OneToManyResult, ProgressEvent, SimilarityDetail, SimilarityMode,
    SimilarityPair, SimilarityRequest, SimilarityResult, SimilaritySource,
)
from shared.errors import NoQuestionsExtracted
from core.models.question import Question
from core.ports.events import EventEmitter
from core.ports.io import DocumentLoader
from core.services._question_parser import parse_questions
from core.services._scorer import score_questions


def _basename(path: str) -> str:
    """取文档 basename，作为查重结果中的来源标识。"""
    return os.path.basename(path)


class SimilarityServiceImpl:
    """题目查重服务（1对多 / 多对多），实现 SimilarityService 端口。"""

    def __init__(self, loader: DocumentLoader, emitter: EventEmitter) -> None:
        self._loader = loader
        self._emitter = emitter

    def check(self, request: SimilarityRequest) -> SimilarityResult:
        """同步执行查重，返回结构化结果；失败抛业务异常。"""
        logger.info("查重开始：mode=%s", request.mode)
        self._emitter.emit(CheckStartedEvent(mode=request.mode))
        if request.mode == SimilarityMode.MANY_TO_MANY:
            return self._check_many_to_many(request)
        return self._check_one_to_many(request)

    # ── 1对多：主文档 vs 多个副文档 ──

    def _check_one_to_many(self, request: SimilarityRequest) -> OneToManyResult:
        main_paras = self._loader.load_paragraphs(request.main_path)
        main_lines = parse_questions(main_paras, request.num_pattern, request.opt_prefix)
        if not main_lines:
            raise NoQuestionsExtracted(f"主文档中未提取到题目：{request.main_path}")

        main_qs = [
            Question(lines=q, source_file=_basename(request.main_path), index=i + 1)
            for i, q in enumerate(main_lines)
        ]

        secondary: Dict[str, List[Question]] = {}
        for path in request.secondary_paths:
            fname = _basename(path)
            paras = self._loader.load_paragraphs(path)
            qs_lines = parse_questions(paras, request.num_pattern, request.opt_prefix)
            if qs_lines:
                secondary[fname] = [Question(lines=q, source_file=fname) for q in qs_lines]

        if not secondary:
            raise NoQuestionsExtracted("所有副文档均未提取到题目")

        total = len(main_qs)
        details: List[SimilarityDetail] = []
        for idx, mq in enumerate(main_qs, 1):
            if idx % 5 == 0:
                self._emitter.emit(ProgressEvent(
                    type=EventType.CHECK_PROGRESS,
                    message=f"比对进度：{idx}/{total}",
                    current=idx,
                    total=total,
                ))
            sources: List[SimilaritySource] = []
            for fname, sec_qs in secondary.items():
                for sq in sec_qs:
                    sc = score_questions(mq, sq)
                    if sc.score >= request.threshold:
                        sources.append(SimilaritySource(
                            file=fname, score=sc.score, reason=sc.reason,
                        ))
                        break
            if sources:
                details.append(SimilarityDetail(
                    index=idx, text=mq.lines, sources=sources,
                ))

        self._emitter.emit(ProgressEvent(
            type=EventType.CHECK_PROGRESS,
            message=f"检测完成：{total} 道题目中，重复 {len(details)} 道",
            current=total,
            total=total,
        ))
        result = OneToManyResult(
            main_count=total, duplicate_count=len(details), details=details,
        )
        self._emitter.emit(CheckCompletedEvent(result=result))
        return result

    # ── 多对多：所有文档两两比对 ──

    def _check_many_to_many(self, request: SimilarityRequest) -> ManyToManyResult:
        all_paths = request.all_paths
        n_docs = len(all_paths)

        all_qs: List[Tuple[str, int, int, Question]] = []
        doc_questions: Dict[str, int] = {}
        for doc_idx, path in enumerate(all_paths):
            fname = _basename(path)
            paras = self._loader.load_paragraphs(path)
            qs_lines = parse_questions(paras, request.num_pattern, request.opt_prefix)
            doc_questions[fname] = len(qs_lines)
            for qi, q in enumerate(qs_lines):
                all_qs.append((fname, doc_idx, qi, Question(lines=q, source_file=fname)))

        total_questions = len(all_qs)
        if total_questions < 2:
            raise NoQuestionsExtracted("所有文档题目总数不足 2 道，无法比对")

        duplicate_pairs: List[SimilarityPair] = []
        total_pairs = total_questions * (total_questions - 1) // 2
        checked = 0
        for i in range(total_questions):
            fname_i, doc_i, _qi, q_i = all_qs[i]
            for j in range(i + 1, total_questions):
                fname_j, doc_j, qj, q_j = all_qs[j]
                checked += 1
                if checked % 500 == 0:
                    self._emitter.emit(ProgressEvent(
                        type=EventType.CHECK_PROGRESS,
                        message=f"比对进度：{checked}/{total_pairs}",
                        current=checked,
                        total=total_pairs,
                    ))
                sc = score_questions(q_i, q_j)
                if sc.score >= request.threshold:
                    pair_type: Literal["internal", "cross"] = (
                        "internal" if doc_i == doc_j else "cross"
                    )
                    duplicate_pairs.append(SimilarityPair(
                        q1_file=fname_i, q1_index=_qi + 1, q1_text=q_i.lines,
                        q2_file=fname_j, q2_index=qj + 1, q2_text=q_j.lines,
                        score=sc.score, reason=sc.reason, pair_type=pair_type,
                    ))

        self._emitter.emit(ProgressEvent(
            type=EventType.CHECK_PROGRESS,
            message=f"比对完成：{total_pairs} 对中，发现 {len(duplicate_pairs)} 对重复",
            current=total_pairs,
            total=total_pairs,
        ))
        result = ManyToManyResult(
            total_questions=total_questions,
            document_count=n_docs,
            doc_questions=doc_questions,
            duplicate_pairs=duplicate_pairs,
            duplicate_rate=round(len(duplicate_pairs) / max(total_pairs, 1), 4),
        )
        self._emitter.emit(CheckCompletedEvent(result=result))
        return result
