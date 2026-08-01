"""跨平台打开文件夹工具（统一四处散落的「打开文件夹」实现）。

此前 slide_view / pdf_slide_view 用 `subprocess.Popen`，similarity_view / json_exam_view
用 `os.system`，且 `folder:` 前缀剥离逻辑分散、异常有的静默吞有的仅 warning。
统一到此一处：剥离 `folder:` 前缀、跨平台派发、使用 `subprocess.Popen`（不阻塞、
不触发 shell 注入），并对打开失败做统一 logging。
"""
from __future__ import annotations

import logging
import subprocess
import sys

logger = logging.getLogger(__name__)

# 富文本链接中用于表示「在文件管理器打开此目录」的协议前缀
_FOLDER_SCHEME = "folder:"


def open_folder(path: str) -> None:
    """在系统文件管理器中打开 ``path`` 指定的目录（跨平台）。

    - 自动剥离富文本链接前缀 ``folder:``；
    - ``path`` 既可以是目录，也可以是文件（由调用方决定是否先 ``os.path.dirname``）；
    - 跨平台：Windows → ``explorer``，macOS → ``open``，其它 → ``xdg-open``；
    - 统一用 ``subprocess.Popen``，并对打开失败做 warning 级 logging（不抛异常）。
    """
    folder = path
    if isinstance(folder, str) and folder.startswith(_FOLDER_SCHEME):
        folder = folder[len(_FOLDER_SCHEME):]
    folder = folder.strip().strip("'").strip('"')
    if not folder:
        return

    if sys.platform == "win32":
        cmd = ["explorer", folder]
    elif sys.platform == "darwin":
        cmd = ["open", folder]
    else:
        cmd = ["xdg-open", folder]

    try:
        subprocess.Popen(cmd)
    except Exception as exc:  # noqa: BLE001 - 系统调用，失败仅提示
        logger.warning("打开文件夹失败: %s (%s)", folder, exc)
