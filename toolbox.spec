# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 — 生成单文件式 ALL IN ONE TOOLBOX 可执行程序。

运行：.\\.venv\\Scripts\\pyinstaller.exe toolbox.spec
输出目录：dist\\ALL IN ONE TOOLBOX.exe
"""
import os

block_cipher = None

# 数据文件：主题与图标（打包后置于 _MEIPASS 基准目录）
added_files = [
    ("theme.qss", "."),
    ("assets", "assets"),
]

a = Analysis(
    ["app.py"],
    pathex=[os.getcwd()],
    binaries=[],
    datas=added_files,
    hiddenimports=[
        # PySide6 子模块（PyInstaller 已知 hook 通常会覆盖，显式声明更稳）
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        # 业务/UI 层按需隐藏导入
        "ui.infra.qt_task_runner",
        "ui.infra.qt_event_emitter",
        "ui.composition",
        "ui.viewmodels.slide_viewmodel",
        "ui.viewmodels.similarity_viewmodel",
        "ui.viewmodels.json_exam_viewmodel",
        "ui.viewmodels.pdf_slide_viewmodel",
        "ui.viewmodels.pdf_word_viewmodel",
        "ui.views.slide_view",
        "ui.views.similarity_view",
        "ui.views.json_exam_view",
        "ui.views.pdf_slide_view",
        "ui.views.pdf_word_view",
        "ui.views.base_view",
        "core.di",
        "core.services",
        "core.adapters",
        "shared.contracts",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "unittest",
        "pydoc",
        "doctest",
        "lib2to3",
        "unittest.mock",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ALL IN ONE TOOLBOX",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/images/logo.png",
)
