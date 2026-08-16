"""视图基类 — 定义工具箱中所有视图插件的统一接口。

替代 legacy ``base_tool.BaseTool``。约定与旧基类一致
（get_name / get_description / on_activate），使 app.py 的注册逻辑零改动。

视图是纯 UI 层：只渲染数据、转发命令（Request）、订阅 ViewModel 信号，
不持有任何业务逻辑。

R-9（A-03）起，基类统一承担「主题单例 + 三样式收集列表 + 模块卡片/字段构造器」，
子类无需各自重复定义 —— 消除 4 份逐字相同的 ``_make_module_card`` /
``_make_labeled_field`` 与列表初始化（见 ``docs/第三方架构评审-核实与整改.md``）。
"""
from __future__ import annotations

from PySide6.QtWidgets import QWidget, QFrame, QVBoxLayout, QLabel

from theme import Theme


class BaseView(QWidget):
    """工具箱中所有视图的抽象基类。

    子类必须实现 get_name / get_description；可选重写 on_activate
    （视图被切换到前台时回调）。

    ``__init__`` 负责初始化所有视图共用的基础状态（主题单例 + 三个样式收集
    列表），子类 ``__init__`` 只需 ``super().__init__()`` 即可获得，无需重复。
    """

    def __init__(self) -> None:
        super().__init__()
        # 主题全局单例（深色/浅色自动切换，集中刷新）。
        self.theme = Theme()
        # 三个样式收集列表，供 _restyle_all 在换肤时统一刷新。
        self._field_labels: list = []
        self._section_labels: list = []
        self._module_cards: list = []

    def get_name(self) -> str:
        """返回视图名称，用于导航栏显示。"""
        raise NotImplementedError

    def get_nav_title(self) -> str:
        """返回导航栏展示标题（图标 + 中文释义），默认回退到 get_name。

        子类应重写以提供更友好的中文入口名，例如「📑 题库转PPT」。
        """
        return self.get_name()

    def get_description(self) -> str:
        """返回视图功能描述（导航栏 tooltip）。"""
        raise NotImplementedError

    def on_activate(self) -> None:
        """视图被切换到前台时的回调，子类可重写以执行初始化逻辑。"""
        pass

    # ── 公共 UI 构造器（R-9 上提，4 视图逐字相同） ──

    def _make_module_card(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        """创建带加粗小标题的浅灰圆角模块卡片，返回 ``(卡片, 内容布局)``。

        卡片加入 ``_module_cards``、标题 ``QLabel`` 加入 ``_section_labels``，
        供 ``_restyle_all`` 在主题切换时统一刷新样式。
        """
        card = QFrame()
        card.setObjectName("module_card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(
            self.theme.page_pad_y, self.theme.spacing,
            self.theme.page_pad_y, self.theme.spacing,
        )
        layout.setSpacing(12)
        header = QLabel(title)
        header.setObjectName("card_title")
        self._section_labels.append(header)
        layout.addWidget(header)
        self._module_cards.append(card)
        return card, layout

    def _make_labeled_field(self, label_text: str, widget: QWidget) -> QWidget:
        """透明 ``QWidget`` + 垂直布局 + 标签（入 ``_field_labels``）+ 控件，返回包裹件。

        标签供 ``_restyle_all`` 在主题切换时统一刷新字号/颜色。
        """
        wrapper = QWidget()
        wrapper.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        label = QLabel(label_text)
        self._field_labels.append(label)
        layout.addWidget(label)
        layout.addWidget(widget)
        return wrapper
