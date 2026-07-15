"""后端对外接口定义（Protocol，零 Qt 依赖）。

本包只声明抽象契约，不依赖任何 GUI 库。具体实现可位于 core/services
（纯逻辑）或 ui/infra（Qt 适配），由依赖注入容器组装。
"""
