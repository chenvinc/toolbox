"""事件契约元测试（R-6）：把 M-04 / M-05 / D-08 / M-07 从文档约束升级为测试强制。

三条测试锁死一整类历史 bug，是把 5 个 🟡（靠文档约束）转绿的最短路径：

- M-04：新增 ``EventType`` 忘记注册进 ``DomainEvent`` Union → 直接失败；
- M-05 + D-08：``EventType`` 跨 VM 串台（两个 VM 抢同一事件）或漏配（事件静默丢弃）
  → 失败；
- M-07：新增 ``BaseView`` 子类忘记注册进 ``ToolboxApp._register_tools`` → 失败。

设计要点：

- ``_WATCHED`` 是 ``BaseViewModel`` 的**类属性**（非实例属性），元测试直接读
  ``VM._WATCHED``，无需实例化任何 VM（避免触发 Qt 事件订阅等副作用）。
- M-04 通过解析 ``DomainEvent`` Union 各事件类的 ``type`` 字段 ``Literal`` 注解实现，
  与实现细节解耦；新增事件类即自动纳入检查。
- M-07 用 ``inspect.getsource`` 静态核验注册点，不实例化 ``ToolboxApp``，
  避免与 test_app_smoke 的真实启动路径争用 QApplication。
"""
import inspect
import unittest
from typing import get_args

from shared.contracts import DomainEvent, EventType

from ui.viewmodels.base_viewmodel import BaseViewModel
from ui.viewmodels.similarity_viewmodel import SimilarityViewModel
from ui.viewmodels.slide_viewmodel import SlideViewModel
from ui.viewmodels.json_exam_viewmodel import JsonExamViewModel
from ui.viewmodels.pdf_slide_viewmodel import PdfSlideViewModel
from ui.views.base_view import BaseView
from ui.views.slide_view import SlideView
from ui.views.similarity_view import SimilarityView
from ui.views.json_exam_view import JsonExamView
from ui.views.pdf_slide_view import PdfSlideView
from app import ToolboxApp


def _flatten_literal(annotation):
    """从字段注解中取出所有 ``Literal`` 字面量值（兼容 Annotated 包裹）。

    ``Literal[EventType.X]`` 经 ``get_args`` 展开后得到的是 ``EventType`` 枚举成员本身，
    而 ``get_args(枚举成员)`` 为空——因此必须对每个叶节点单独判断是否为 ``EventType``。
    """
    # 注解本身就是单个枚举成员（未包 Literal）的退化情形
    if not get_args(annotation) and isinstance(annotation, EventType):
        return [annotation]
    values = []
    for arg in get_args(annotation):
        # Annotated[L, meta...] 时，真正的类型在第一个位置参数
        inner = get_args(arg)[0] if hasattr(arg, "__metadata__") else arg
        sub_args = get_args(inner)
        if sub_args:
            for sub in sub_args:
                if isinstance(sub, EventType):
                    values.append(sub)
        elif isinstance(inner, EventType):
            values.append(inner)
    return values


def _union_event_classes():
    """从 ``DomainEvent`` 注解中取出 Union 的成员事件类。"""
    # DomainEvent = Annotated[Union[...], Field(discriminator="type")]
    annotated = get_args(DomainEvent)
    union = annotated[0]
    return [m for m in get_args(union) if isinstance(m, type)]


def _registered_event_types():
    """收集所有事件类在 ``type`` 字段上声明的 ``Literal`` EventType 值。"""
    covered = set()
    for cls in _union_event_classes():
        field = cls.model_fields["type"]
        for val in _flatten_literal(field.annotation):
            if isinstance(val, EventType):
                covered.add(val)
    return covered


def _all_viewmodel_classes():
    """递归收集 ``BaseViewModel`` 的所有子类。"""
    found = []

    def _walk(cls):
        for child in cls.__subclasses__():
            if child is BaseViewModel:
                continue
            found.append(child)
            _walk(child)

    _walk(BaseViewModel)
    return found


def _leaf_base_views():
    """收集继承 ``BaseView`` 的「叶子」具体视图类（排除中间基类与 BaseView 自身）。"""
    leaves = []

    def _walk(cls):
        kids = [c for c in cls.__subclasses__() if issubclass(c, BaseView)]
        if not kids:
            if cls is not BaseView:
                leaves.append(cls)
        else:
            for k in kids:
                _walk(k)

    _walk(BaseView)
    return leaves


class EventContractTests(unittest.TestCase):
    def test_every_eventtype_registered_in_domainevent_union(self):
        """M-04：每个 ``EventType`` 必须被 ``DomainEvent`` Union 中某事件类的
        ``type`` Literal 覆盖，否则新增事件无法被通道正确判别分发。"""
        covered = _registered_event_types()
        missing = [e for e in EventType if e not in covered]
        self.assertFalse(
            missing,
            f"以下 EventType 未注册进 DomainEvent Union（缺少对应事件类）：{missing}",
        )

    def test_eventtypes_partitioned_across_viewmodels(self):
        """M-05 + D-08：每个 ``EventType`` 恰好被一个 VM 的 ``_WATCHED`` 订阅——
        既防串台（两个 VM 抢同一事件），也防漏配（事件无人订阅被静默丢弃）。"""
        watched_by = {}
        for vm in _all_viewmodel_classes():
            for et in vm._WATCHED:
                watched_by.setdefault(et, []).append(vm.__name__)

        collisions = {et: v for et, v in watched_by.items() if len(v) > 1}
        self.assertFalse(
            collisions,
            f"EventType 被多个 VM 订阅（串台风险）：{collisions}",
        )
        unwatched = [e for e in EventType if e not in watched_by]
        self.assertFalse(
            unwatched,
            f"EventType 未被任何 VM 订阅（漏配，事件将被静默丢弃）：{unwatched}",
        )
        # 订阅集合应恰好等于 EventType 全集，无多订/漏订
        self.assertEqual(
            set(watched_by),
            set(EventType),
            "各 VM 的 _WATCHED 并集与 EventType 全集不一致",
        )

    def test_multivalue_type_literal_has_no_default(self):
        """P1a：``type`` 允许多个 EventType 的事件类（ProgressEvent / FailedEvent）
        不得带默认值——否则漏传 ``type`` 会静默落到第一个枚举值（CHECK_PROGRESS /
        CHECK_FAILED），被 ``_WATCHED`` 过滤后事件无声丢失（串台/丢事件）。
        单值 Literal（如 ``PptxCompletedEvent.type``）允许默认，因其默认即唯一合法值。"""
        for cls in _union_event_classes():
            field = cls.model_fields["type"]
            values = _flatten_literal(field.annotation)
            if len(values) > 1:
                self.assertTrue(
                    field.is_required(),
                    f"{cls.__name__}.type 允许多个 EventType（{values}）却带默认值 "
                    f"{field.default!r}：漏传 type 会静默串台，应去掉默认值强制显式传入",
                )

    def test_every_baseview_subclass_registered_in_app(self):
        """M-07：每个具体 ``BaseView`` 子类必须出现在 ``ToolboxApp._register_tools``，
        否则新增工具虽写了 View 却不会出现在导航中。"""
        concrete = _leaf_base_views()
        self.assertTrue(concrete, "未发现任何 BaseView 子类")
        src = inspect.getsource(ToolboxApp._register_tools)
        unregistered = [c.__name__ for c in concrete if c.__name__ not in src]
        self.assertFalse(
            unregistered,
            f"以下 BaseView 子类未在 ToolboxApp._register_tools 注册：{unregistered}",
        )


if __name__ == "__main__":
    unittest.main()
