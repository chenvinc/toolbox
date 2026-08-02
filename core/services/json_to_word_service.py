"""JSON→Word 试卷生成服务（零 Qt 依赖）。

编排主流程：
  读取 UI 参数 → 解析 JSON → 并发预下载图片（有限并发，避免被封）→
  生成题本 docx → 生成解析 docx → 写入输出目录 → 推送进度/完成事件。

进度反馈细化为步骤事件：解析中 → 下载图片 x/n → 生成题本 → 生成解析 → 完成。
图片下载失败不中断流程（适配器就地插入灰色占位框），并在最终结果的
``failed_images`` 中记录失败 URL，由 UI 汇总报告。

解析失败 / 输出目录无写入权限等以业务异常抛出，由 ViewModel 的
on_async_error 桥接为失败信号，与 SimilarityServiceImpl / PptxServiceImpl 行为一致。
"""
from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

from typing import Dict, List, Optional

from shared.contracts import (
    EventType,
    ExamCompletedEvent,
    GenerateExamRequest,
    GenerateExamResult,
    ProgressEvent,
)
from core.models.exam_question import ExamQuestion
from core.ports.events import EventEmitter
from core.ports.io import ExamDocxWriter
from core.services._exam_image_fetch import prefetch_images
from core.services._exam_parser import parse_exam_json


class JsonToWordServiceImpl:
    """JSON→Word 试卷生成服务实现，持有 ExamDocxWriter 适配器与事件端口。"""

    def __init__(self, writer: ExamDocxWriter, emitter: EventEmitter) -> None:
        self._writer = writer
        self._emitter = emitter

    def generate(self, request: GenerateExamRequest) -> GenerateExamResult:
        """同步生成题本与解析文档，返回输出路径；失败抛业务异常。"""
        logger.info("开始生成试卷：输入=%s 输出目录=%s", request.input_path, request.output_dir)
        # 步骤一：解析（即时反馈，进度条尚不知总数，先用占位 total=1）
        self._emitter.emit(ProgressEvent(
            type=EventType.EXAM_PROGRESS,
            message="解析中...",
            current=0,
            total=1,
        ))
        # 解析失败（文件缺失 / JSON 非法 / 无题目）会抛出业务异常，
        # 由 ViewModel 桥接为失败信号，无需在此捕获。
        questions: list[ExamQuestion]
        questions, _title = parse_exam_json(request.input_path)

        # 步骤二：并发预下载图片（带步骤总数，进度条据此设定范围）
        image_urls = self._collect_image_urls(questions)
        total = len(image_urls) + 2  # 下载阶段 + 题本 + 解析
        self._emitter.emit(ProgressEvent(
            type=EventType.EXAM_PROGRESS,
            message="解析中...",
            current=0,
            total=total,
        ))

        cache: Dict[str, Optional[bytes]] = {}
        if image_urls:
            cache, _failed = prefetch_images(
                image_urls,
                on_progress=lambda done, n, f: self._emit_download_progress(
                    done, n, f, total
                ),
            )

        # 步骤三/四：生成题本 + 解析（适配器回调映射到整体进度）。
        # 适配器会如实记录「下载失败」与「下载成功但字节不可识别」两类失败，
        # 并在 result.failed_images 中汇总。
        offset = len(image_urls)
        result = self._writer.build(
            request,
            questions,
            on_progress=lambda step, _step_total: self._emit_doc_progress(
                step, offset, total
            ),
            image_cache=cache,
        )

        # 部分图片失败：进度栏警告提示，继续生成（失败清单在最终报告里列出）。
        if result.failed_images:
            self._emitter.emit(ProgressEvent(
                type=EventType.EXAM_PROGRESS,
                message=f"部分图片未能加载（{len(result.failed_images)} 张），继续生成...",
                current=offset,
                total=total,
            ))

        self._emitter.emit(ExamCompletedEvent(result=result))
        return result

    @staticmethod
    def _collect_image_urls(questions: List[ExamQuestion]) -> List[str]:
        """从全部题目中收集去重后的图片地址。"""
        seen: set[str] = set()
        urls: List[str] = []
        for q in questions:
            for im in q.images:
                src = (im.src or "").strip()
                if src and src not in seen:
                    seen.add(src)
                    urls.append(src)
        return urls

    def _emit_download_progress(
        self, done: int, n: int, failed_count: int, total: int
    ) -> None:
        """把单张图片下载完成转译为「下载图片 x/n（失败 m）」进度事件。"""
        msg = f"下载图片 {done}/{n}"
        if failed_count:
            msg += f"（失败 {failed_count}）"
        self._emitter.emit(ProgressEvent(
            type=EventType.EXAM_PROGRESS,
            message=msg,
            current=done,
            total=total,
        ))

    def _emit_doc_progress(self, step: int, offset: int, total: int) -> None:
        """把适配器回传的题本/解析步骤映射为整体进度事件。"""
        if step <= 1:
            msg = "生成题本..."
        else:
            msg = "生成解析..."
        self._emitter.emit(ProgressEvent(
            type=EventType.EXAM_PROGRESS,
            message=msg,
            current=offset + step,
            total=total,
        ))
