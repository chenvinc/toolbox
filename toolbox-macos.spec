# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 — 生成标准 macOS .app Bundle（toolbox）。

标准 one-folder 结构（启动快，无临时解压）：
  - EXE 的 PKG 仅含 pyz（Python 字节码）+ a.scripts（极小，几 MB）。
  - COLLECT 把 EXE + 全部 a.binaries + a.datas 落到磁盘 Contents/MacOS。
  - _MEIPASS = Contents/MacOS（磁盘目录），无需每次启动解压数百 MB Qt 框架。
  - BUNDLE 包裹 COLLECT 产出 .app 目录型 bundle。

构建：
    .venv/bin/pyinstaller --distpath dist/macos -y toolbox-macos.spec

输出：dist/macos/toolbox.app

说明：
- 不配置任何代码签名身份（codesign_identity 保持默认 None），签名后续单独处理。
- Info.plist 由 PyInstaller 自动生成，并通过 BUNDLE 的 info_plist 字典注入
  额外的 Apple 规范键。
  下列键由框架自动写入、请勿在 info_plist 中重复覆盖：
  CFBundleExecutable、CFBundleIconFile、CFBundleIdentifier、
  CFBundlePackageType、CFBundleInfoDictionaryVersion、
  CFBundleShortVersionString、NSHighResolutionCapable。

历史坑（已规避，勿回退）：
- 纯 one-file（exclude_binaries=False + a.binaries 全进 EXE）：
  能用，但每次启动把整个 Qt 框架解压到临时目录，冷启动 15~20s，体验极差。
- hybrid 混合拆分（手动把 binaries 分到 EXE + COLLECT 两边）：
  EXTENSION .so 内嵌 _MEIPASS 但其依赖的 BINARY dylib 落盘 → rpath 错位 →
  "Library not loaded: @rpath/..."；或反过来 dylib 在 _MEIPASS 但 .so 落盘 →
  frozen importer 只扫描 _MEIPASS → "No module named shiboken6"。
  根因：EXTENSION 与其依赖的 BINARY 必须同处一个目录，手动拆分无法保证。
- 标准 one-folder（本配置）：全部 binaries 统一落 COLLECT 磁盘，co-location 天然保证，
  _MEIPASS = 磁盘目录无临时解压。libpython 也在 COLLECT 磁盘，bootloader 按目录查找。
"""

import os

block_cipher = None

# 数据文件：主题与图标
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
        # PySide6 子模块
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        # 业务/UI 层
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

# ── 标准 one-folder ────────────────────────────────────────────────────
# exclude_binaries=True：a.binaries 不进 EXE 的 PKG，全部交给 COLLECT 落磁盘。
# EXE 的 PKG 仅含 pyz + scripts，体积小。
exe = EXE(
    pyz,
    a.scripts,
    [],                    # 二进制不进 EXE → COLLECT
    a.zipfiles,
    [],                    # datas 不进 EXE → COLLECT（标准 one-folder 约定）
    [],
    exclude_binaries=True,
    name="toolbox",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=["libpython3.13.dylib"],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/app_icon.icns",
)

# COLLECT：EXE + 全部 binaries + datas + zipfiles 落磁盘。
# _MEIPASS = 此目录（Contents/MacOS），所有 .so / .dylib / stdlib / assets 同处。
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="toolbox",
)

app = BUNDLE(
    coll,
    name="toolbox.app",
    icon="assets/app_icon.icns",
    bundle_identifier="com.swiper.toolbox",
    version="4.1",
    info_plist={
        "CFBundleName": "toolbox",
        "CFBundleDisplayName": "toolbox",
        "CFBundleVersion": "4.1",
        "LSMinimumSystemVersion": "11.0",
        "NSPrincipalClass": "NSApplication",
        "NSHighResolutionCapable": True,
        "CFBundleGetInfoString": "toolbox — PySide6 工具箱",
    },
)
