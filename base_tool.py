"""工具基类 — 定义工具箱中所有工具插件的统一接口。

每个工具需继承 BaseTool 并实现 get_name / get_description。
可通过基类访问 theme.Theme 和 widgets 模块中的通用组件。
"""

from PySide6.QtWidgets import QWidget

from theme import Theme


class BaseTool(QWidget):
    """工具箱中所有工具的抽象基类。

    每个工具插件需继承此类并实现 get_name、get_description 方法，
    由主工具箱窗口统一管理导航和内容切换。
    """

    def get_name(self) -> str:
        """返回工具名称，用于导航栏显示。"""
        raise NotImplementedError

    def get_description(self) -> str:
        """返回工具功能描述。"""
        raise NotImplementedError

    def on_activate(self):
        """工具被切换到前台时的回调，子类可重写以执行初始化逻辑。"""
        pass
