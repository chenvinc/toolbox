"""生产环境依赖装配（从 ``app.py`` 抽出，使 ``_apply_global_font`` 名副其实）。

仅负责：
- 用 ``TaskRunner`` / ``EventEmitter`` 组装 core 服务图（ ``Container.build`` ，零 Qt）；
- 构造四个 ``ViewModel``（持有 service + task_runner + event_emitter）。

``app.py`` 只保留窗口与导航。把装配逻辑集中于此，既让「字体方法」名副其实（N-01 根因），
也便于对装配做独立单测，而不必每次都拉起整个 ``QApplication``。
"""
from core.di import Container
from ui.infra.qt_event_emitter import QtEventEmitter
from ui.infra.qt_task_runner import QtTaskRunner
from ui.viewmodels.json_exam_viewmodel import JsonExamViewModel
from ui.viewmodels.pdf_slide_viewmodel import PdfSlideViewModel
from ui.viewmodels.similarity_viewmodel import SimilarityViewModel
from ui.viewmodels.slide_viewmodel import SlideViewModel


def build_container(
    task_runner: QtTaskRunner, event_emitter: QtEventEmitter
) -> Container:
    """组装 core 服务图（外部适配器 → 服务，零 Qt）。"""
    return Container.build(task_runner=task_runner, event_emitter=event_emitter)


def build_view_models(
    task_runner: QtTaskRunner, event_emitter: QtEventEmitter
):
    """构造四个 ViewModel（持有 service + task_runner + event_emitter）。

    新增工具时，在此追加一行 VM 构造并并入返回元组即可。
    """
    container = build_container(task_runner, event_emitter)
    slide_vm = SlideViewModel(
        container.resolve("extraction"),
        container.resolve("pptx"),
        task_runner,
        event_emitter,
    )
    sim_vm = SimilarityViewModel(
        container.resolve("similarity"),
        task_runner,
        event_emitter,
    )
    exam_vm = JsonExamViewModel(
        container.resolve("exam"),
        task_runner,
        event_emitter,
    )
    pdf_vm = PdfSlideViewModel(
        container.resolve("pdf_slide"),
        task_runner,
        event_emitter,
    )
    return slide_vm, sim_vm, exam_vm, pdf_vm
