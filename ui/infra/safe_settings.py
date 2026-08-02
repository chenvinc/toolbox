"""QSettings 安全读取助手。

所有 ``settings.value()`` 调用都应经过此处，避免脏值（崩溃残留 / 手改 /
跨版本格式变更）使 View 构造即抛异常、应用无法启动（N-02）。

设计原则：
- 任何无法解析的值一律回落到默认，绝不向外抛 ``ValueError`` / ``TypeError``。
- ``read_float`` 额外支持区间夹紧（clamp），防止持久化的越界值导致控件
  构造 ``setRange`` 断言失败或业务逻辑异常。
- ``read_bool`` 兼容旧版本以字符串 ``"true"`` / ``"false"`` 存储的布尔。
"""
from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import QSettings


def read_float(
    settings: QSettings,
    key: str,
    default: float,
    lo: Optional[float] = None,
    hi: Optional[float] = None,
) -> float:
    raw = settings.value(key, default)
    try:
        v = float(raw)  # float() 对 None / 非法字符串抛出 TypeError / ValueError
    except (TypeError, ValueError):
        return default
    if math.isnan(v) or math.isinf(v):
        return default
    if lo is not None and v < lo:
        v = lo
    if hi is not None and v > hi:
        v = hi
    return v


def read_bool(settings: QSettings, key: str, default: bool) -> bool:
    raw = settings.value(key, default)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in ("1", "true", "yes", "y", "on")
    return default


def read_str(settings: QSettings, key: str, default: str) -> str:
    raw = settings.value(key, default)
    if raw is None:
        return default
    return str(raw)
