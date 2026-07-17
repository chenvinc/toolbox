"""Root conftest — 将项目根目录加入 sys.path，使 core / shared / ui 等顶层包可被测试导入。

背景：本仓库 tests/unit/core/__init__.py 存在但 tests/__init__.py、tests/unit/__init__.py
缺失，pytest 在 importlib 模式下会把单测模块误判为 ``core.test_xxx``，从而让
``from core.xxx import ...`` 解析到 tests/unit/core 而非真实顶层 core 包（见
docs/新增Tool开发指南.md §5 Q9）。补全 __init__.py 让测试模块归属 ``tests.*`` 命名空间，
本文件再把项目根加入 sys.path，确保真实 core / shared / ui 可被顶层导入。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ROOT_STR = str(ROOT)
if ROOT_STR not in sys.path:
    sys.path.insert(0, ROOT_STR)
