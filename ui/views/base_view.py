"""视图基类 — 定义工具箱中所有视图插件的统一接口。

替代 legacy ``base_tool.BaseTool``。约定与旧基类一致
（get_name / get_description / on_activate），使 app.py 的注册逻辑零改动。

视图是纯 UI 层：只渲染数据、转发命令（Request）、订阅 ViewModel 信号，
不持有任何业务逻辑。
"""
from __future__ import annotations

from PySide6.QtWidgets import QWidget


class BaseView(QWidget):
    """工具箱中所有视图的抽象基类。

    子类必须实现 get_name / get_description；可选重写 on_activate
    （视图被切换到前台时回调）。
    """

    def get_name(self) -> str:
        """返回视图名称，用于导航栏显示。"""
        raise NotImplementedError

    def get_description(self) -> str:
        """返回视图功能描述（导航栏 tooltip）。"""
        raise NotImplementedError

    def on_activate(self) -> None:
        """视图被切换到前台时的回调，子类可重写以执行初始化逻辑。"""
        pass
