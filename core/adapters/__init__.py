"""外部依赖适配器（零 Qt 依赖；可依赖 python-docx / python-pptx 等后端库）。

适配器实现 core/ports/io.py 定义的端口，把第三方库封装在 core 边界内，
使 services 层无需直接 import 第三方库、可被 mock 注入。
"""
