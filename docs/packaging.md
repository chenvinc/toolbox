# macOS 打包规范（v1.3）

> 适用范围：`toolbox` 项目在 macOS 下生成标准 `.app` Bundle（PyInstaller 6.21 + Python 3.13 venv）。
> 配套文件：[`toolbox-macos.spec`](../toolbox-macos.spec)、[`scripts/sign-adhoc.sh`](../scripts/sign-adhoc.sh)、[`scripts/entitlements.plist`](../scripts/entitlements.plist)、[`scripts/build-dmg.sh`](../scripts/build-dmg.sh)。
> 本文记录**已实跑验证**的打包流程与踩过的坑，避免重复踩雷。Windows 单文件 `.exe` 构建见 [`toolbox.spec`](../toolbox.spec)。

---

## 0. 一句话流程

```
assets/images/logo.png
      │  sips + iconutil 生成
      ▼
assets/app_icon.icns            ← BUNDLE 的 icon 参数（必须 .icns，不能 .png）
      │
toolbox-macos.spec             ← 标准 one-folder: EXE + COLLECT + BUNDLE
      │  .venv/bin/python -m PyInstaller --distpath dist/macos -y toolbox-macos.spec
      ▼
dist/macos/toolbox.app
      │  ./scripts/sign-adhoc.sh dist/macos/toolbox.app   (可选，ad-hoc / hardened runtime 签名)
      ▼
dist/toolbox-4.1-macos.dmg
      │  ./scripts/build-dmg.sh   (create-dmg 优先，hdiutil 回退)
      ▼
用户双击 DMG → 拖拽 toolbox.app 到 Applications
```

> **one-folder vs one-file**：one-folder 把 Qt 框架等重二进制落磁盘（`Contents/Frameworks`），启动时无需临时解压，
> 冷启动从 ~15-20s 降到 **~370ms**（实测）。one-file 虽然产出单文件更"干净"，但每次启动都要把 ~200MB Qt
> 载荷解压到临时目录，体验极差。详见 [第 4 节](#4-spec-结构关键)。

---

## 1. 环境要求

| 项 | 说明 |
| --- | --- |
| 系统 | macOS（Apple Silicon → `arm64`；Intel → `x86_64`；Universal 由 `codesign` 一并处理） |
| Python | 项目 `.venv`（Python 3.13），PySide6 6.11.1 |
| 构建工具 | PyInstaller 6.21.0（在 `.venv` 内） |
| 原生工具 | `sips` / `iconutil`（图标）、`codesign` / `lipo`（签名与架构检查） |

> **坑 0 —— `.venv/bin/pyinstaller` 的 shebang 失效**：该脚本首行指向已删除的其他项目 venv，直接执行会 `bad interpreter`。务必用模块方式调用：
> ```bash
> .venv/bin/python -m PyInstaller toolbox-macos.spec
> ```

---

## 2. 产物目录约定

构建产物输出到 `dist/macos/`，由命令行 `--distpath` 指定（spec 内不再设 `CONF["distpath"]`，避免 EXE 与 COLLECT 同名冲突）：

```bash
.venv/bin/python -m PyInstaller --distpath dist/macos -y toolbox-macos.spec
```

最终包：`dist/macos/toolbox.app`，标准结构为：
```
toolbox.app/
└── Contents/
    ├── MacOS/toolbox          ← 可执行文件（Mach-O，arm64/x86_64，内嵌 PYZ 字节码）
    ├── Resources/             ← 数据文件 + 二进制（符号链接 → Frameworks）
    ├── Frameworks/            ← 运行时依赖（PySide6 Qt 框架、libpython、python3.13 扩展等）
    ├── _CodeSignature/        ← 签名（ad-hoc 或后续正式签名）
    └── Info.plist             ← 由 PyInstaller 自动生成
```

> one-folder 结构下，`Contents/Resources/` 中的 `.so`/`.dylib` 是指向 `Contents/Frameworks/` 的符号链接，
> 二进制真实文件在 `Frameworks/`。PyInstaller 的 macOS BUNDLE 自动处理此布局。
> `dist/` 已在 `.gitignore` 中，构建产物不入库。

---

## 3. 图标：必须用 `.icns`

macOS `.app` 的 `BUNDLE.icon` 只认 `.icns`（传 `.png` 不会自动转）。用原生工具从现有 `logo.png`(512×512) 生成：

```bash
ICONSET=$(mktemp -d)/tb.iconset && mkdir -p "$ICONSET"
SRC=assets/images/logo.png
sips -z 16 16     "$SRC" --out "$ICONSET/icon_16x16.png"      >/dev/null
sips -z 32 32     "$SRC" --out "$ICONSET/icon_16x16@2x.png"  >/dev/null
sips -z 32 32     "$SRC" --out "$ICONSET/icon_32x32.png"      >/dev/null
sips -z 64 64     "$SRC" --out "$ICONSET/icon_32x32@2x.png"  >/dev/null
sips -z 128 128   "$SRC" --out "$ICONSET/icon_128x128.png"   >/dev/null
sips -z 256 256   "$SRC" --out "$ICONSET/icon_128x128@2x.png">/dev/null
sips -z 256 256   "$SRC" --out "$ICONSET/icon_256x256.png"   >/dev/null
sips -z 512 512   "$SRC" --out "$ICONSET/icon_256x256@2x.png">/dev/null
sips -z 512 512   "$SRC" --out "$ICONSET/icon_512x512.png"   >/dev/null
sips -z 1024 1024 "$SRC" --out "$ICONSET/icon_512x512@2x.png">/dev/null
iconutil --convert icns --output assets/app_icon.icns "$ICONSET"
rm -rf "$(dirname "$ICONSET")"
```

生成物 `assets/app_icon.icns` 在 spec 中通过 `icon="assets/app_icon.icns"` 引用（BUNDLE 与 EXE 各一处）。

---

## 4. spec 结构（关键）

`toolbox-macos.spec` 采用 **标准 one-folder：EXE + COLLECT + BUNDLE** 结构：

```python
exe = EXE(
    pyz, a.scripts,
    [],                    # 二进制不进 EXE → COLLECT（exclude_binaries=True）
    a.zipfiles,
    [],                    # datas 不进 EXE → COLLECT
    [],
    exclude_binaries=True, # ← 关键：a.binaries 全部交给 COLLECT 落磁盘
    name="toolbox",
    console=False,          # 窗口程序，隐藏终端
    codesign_identity=None, # ← 不配置签名身份（后续单独处理）
    icon="assets/app_icon.icns",
    ...
)

coll = COLLECT(
    exe,
    a.binaries,            # ← 全部二进制（libpython、Qt dylib、PySide6 .so）落磁盘
    a.zipfiles,
    a.datas,               # ← 全部数据文件（stdlib、theme.qss、assets）落磁盘
    strip=False,
    upx=True,
    name="toolbox",
)

app = BUNDLE(
    coll,                  # ← 包裹 COLLECT 产出
    name="toolbox.app",
    icon="assets/app_icon.icns",
    bundle_identifier="com.swiper.toolbox",
    version="4.1",
    info_plist={ ... },     # ← Apple 规范键注入（见第 5 节）
)
```

`Analysis(...)` 的 `datas` 沿用项目数据文件：
```python
added_files = [("theme.qss", "."), ("assets", "assets")]
```

### 为什么用 one-folder 而非 one-file

| 指标 | one-file | one-folder |
| --- | --- | --- |
| 冷启动耗时 | ~15-20s（每次解压 ~200MB Qt 到临时目录） | **~370ms**（二进制已在磁盘） |
| 产物形态 | 单个 .app（所有内容内嵌 EXE） | .app 目录（二进制在 Contents/Frameworks） |
| 分发便利性 | 单文件更简洁 | 目录型，需打 DMG 分发 |
| 适用场景 | 极小脚本 | **PySide6 / Qt 等重框架应用（推荐）** |

### 历史踩坑（勿回退）

> ⚠️ **坑 1 —— hybrid 混合拆分（已废弃）**：曾经尝试手动把 `a.binaries` 按 typecode
> 拆分到 EXE（内嵌）和 COLLECT（落盘）两边，导致：
> - EXTENSION `.so` 内嵌 `_MEIPASS` 但依赖的 BINARY dylib 落盘 → rpath 错位 → `Library not loaded: @rpath/...`
> - 反过来 dylib 内嵌但 .so 落盘 → frozen importer 只扫 `_MEIPASS` → `No module named shiboken6`
> - 根因：**EXTENSION 与其依赖的 BINARY 必须同处一个目录**，手动拆分无法保证。
>
> ✅ **标准 one-folder（当前方案）**：全部 binaries 统一落 COLLECT 磁盘，co-location 天然保证。
> `_MEIPASS` = `Contents/Resources/`（磁盘目录，无临时解压）。libpython 也在 COLLECT 磁盘。

---

## 5. Info.plist：用框架自动注入，别手建文件

PyInstaller 的 `BUNDLE` 会**自动生成** `Info.plist`，并通过 `info_plist` 字典把自定义键**合并**进去（后写覆盖前写）。因此**不需要手动创建 plist 文件**，只配参数即可：

```python
info_plist={
    "CFBundleName": "toolbox",
    "CFBundleDisplayName": "toolbox",
    "CFBundleVersion": "4.1",
    "LSMinimumSystemVersion": "11.0",
    "NSPrincipalClass": "NSApplication",
    "NSHighResolutionCapable": True,
    "CFBundleGetInfoString": "toolbox — PySide6 工具箱",
}
```

**下列键由框架自动写入，禁止在 `info_plist` 中重复覆盖**，否则与 bundle 实际结构不一致（尤其 `CFBundleExecutable`/`CFBundleIconFile` 写错会导致启动失败）：
`CFBundleExecutable`、`CFBundleIconFile`、`CFBundleIdentifier`、`CFBundlePackageType`、`CFBundleInfoDictionaryVersion`、`CFBundleShortVersionString`、`NSHighResolutionCapable`。

---

## 6. 本地签名（ad-hoc / hardened runtime）

`scripts/sign-adhoc.sh` 仅用 macOS 原生 `codesign`（+`lipo` 仅作架构报告），执行：
```bash
codesign --sign - --force --deep --options runtime "$APP"   # ad-hoc + 启用 hardened runtime
codesign --verify --verbose=2 "$APP"                        # 签名后立即验证
```
失败时打印 `codesign` 具体输出并以退出码 1 结束。用法：
```bash
./scripts/sign-adhoc.sh                                   # 默认路径
./scripts/sign-adhoc.sh "dist/macos/toolbox.app"
```

> ⚠️ **坑 2 —— hardened runtime 必须配 entitlements**：`--options runtime` 启用 hardened runtime 后，PyInstaller/PySide6 应用需要以下权限，否则启动崩溃：
> - `com.apple.security.cs.disable-library-validation`（允许启动器从临时目录 `dlopen` libpython）
> - `com.apple.security.cs.allow-jit`
> - `com.apple.security.cs.allow-unsigned-executable-memory`
>
> 已沉淀在 `scripts/entitlements.plist`，`sign-adhoc.sh` 自动 `--entitlements` 注入。验证：`codesign -d --entitlements - "$APP"` 应看到上述三键。

> 仅本地自测、暂不分发时，可去掉 `--options runtime`（纯 ad-hoc）直接启动，无需 entitlements。

---

## 7. 验证清单（交付前必跑）

```bash
# 1) 包结构
test -d "dist/macos/toolbox.app" && echo ".app OK"
find "dist/macos/toolbox.app/Contents" -maxdepth 1 -type d
file "dist/macos/toolbox.app/Contents/MacOS/toolbox"   # Mach-O 64-bit executable

# 2) Info.plist 关键键
/usr/libexec/PlistBuddy -c "Print" "dist/macos/toolbox.app/Contents/Info.plist"

# 3) 无签名身份（ad-hoc 才开始，正式签名后续做）
codesign -dvvv "dist/macos/toolbox.app" 2>&1 | grep -iE "Signature|TeamIdentifier|flags"

# 4) 启动是否越过 bootloader（headless 下进 Qt 事件循环即算成功）
dist/macos/toolbox.app/Contents/MacOS/toolbox &
sleep 5; kill -9 %1 2>/dev/null   # 5s 内不崩 = 已越过 libpython 加载

# 5) 真机双击运行
open "dist/macos/toolbox.app"
```

---

## 8. 故障排查速查

| 现象 | 原因 | 解决 |
| --- | --- | --- |
| 双击闪退，日志 `Failed to load Python shared library .../_MEIxxx/libpython3.13.dylib (no such file)` | hybrid 混合拆分导致 libpython 内嵌但路径错位 | 改用标准 one-folder（`exclude_binaries=True` + COLLECT 含 `a.binaries`），勿手动拆分 typecode |
| `Library not loaded: @rpath/libshiboken6.dylib` | EXTENSION `.so` 内嵌 `_MEIPASS` 但依赖的 BINARY dylib 落盘，co-location 破坏 | 同上：全部 binaries 统一落 COLLECT 磁盘 |
| 窗口程序无 traceback、静默退出 | `console=False` 隐藏了 stderr | 直接在 Terminal 跑 `Contents/MacOS/...` 看报错；或查 `~/Library/Application Support/logs/{toolbox,crash}.log`（未设 org 时路径即此） |
| 签名后启动崩溃（hardened runtime） | 缺 entitlements | 用 `sign-adhoc.sh`（已注入 `entitlements.plist`）重签 |
| `bad interpreter: .../quiz2slide/.venv/bin/python3` | `.venv/bin/pyinstaller` shebang 失效 | 改用 `.venv/bin/python -m PyInstaller ...` |
| 重建报 `output directory is not empty` | `dist/macos` 已存在 | 加 `-y`：`python -m PyInstaller -y toolbox-macos.spec` |
| 双击弹出“无法打开/已损坏” | Gatekeeper 隔离属性 | 本机产物一般无 quarantine；分发时走正式签名 + 公证 |
| 首次双击窗口闪一下即隐，点 Dock 出图标但无窗口，第三次点击才出现 | macOS 下 Qt 应用未显式激活，窗口停留在后台（应用层问题，非打包） | `app.py` 已在 `__main__` 调 `window.raise_()/activateWindow()` + `_bring_to_front_macos()`（ctypes 调 `activateIgnoringOtherApps:`），并在 `ToolboxApp.changeEvent` 捕获 `ApplicationActivate` 重新置顶。详见 `app.py` |
| 首次点击必闪退、二次才出 dock 图标、多次出现多个图标、长时间等待才出窗口 | 无单实例锁 + one-file 冷启动极慢（~20s）；反复双击派生多个 bootloader 实例互相竞争/原生层被杀（崩溃不落 Python 日志）；窗口未激活被压后台 | `app.py` 三处加固：① `QLocalServer` 单实例守卫——已有实例则连上去请其置顶并退出，杜绝多实例；② `QSplashScreen` 启动闪屏在重初始化前先给反馈；③ 重新启用 `_bring_to_front_macos()` + `changeEvent` 前台激活。**已改 one-folder 提速（~370ms），冷启动不再解压** |
| 冷启动极慢（15-20s） | one-file 模式每次启动把 ~200MB Qt 框架解压到临时目录 | 改用标准 one-folder（`exclude_binaries=True` + COLLECT），二进制落磁盘无需解压 |

---

## 8.5 DMG 打包分发

`scripts/build-dmg.sh` 将 `dist/macos/toolbox.app` 打包为 `dist/toolbox-4.1-macos.dmg`，内含 `.app` 和指向 `/Applications` 的拖拽快捷方式。

```bash
./scripts/build-dmg.sh                    # 默认路径 + 自动读 Info.plist 版本号
APP_PATH="dist/macos/toolbox.app" \
  VERSION=4.1 \
  ./scripts/build-dmg.sh                  # 指定参数
```

### create-dmg（优先）

脚本检测到 `create-dmg` 在 PATH 中时优先使用：
```bash
create-dmg \
  --volname "toolbox" \
  --volicon assets/app_icon.icns \
  --window-pos 200 120 --window-size 620 420 \
  --icon "toolbox.app" 150 200 \
  --hide-extension "toolbox.app" \
  --app-drop-link 450 200 \
  dist/toolbox-4.1-macos.dmg \
  dist/macos/toolbox.app
```

### hdiutil 回退（无 create-dmg 时）

无 `create-dmg` 时自动回退纯原生方案：`hdiutil create -format UDRW` → 挂载 → osascript 设图标位置 → `hdiutil convert -format UDZO`。osascript 步骤有 `|| true` 容错，无 Finder 自动化权限也不会失败。

> ⚠️ **坑 3 —— create-dmg 的 Finder 自动化权限**：create-dmg 内部用 AppleScript 控制 Finder 设图标位置。若终端/IDE 进程未获得 Finder 自动化权限（系统设置 → 隐私与安全性 → 自动化），会报 `execution error: "Finder"遇到一个错误：发生权限违例。 (-10004)`。
>
> 解决：① 在系统设置中授权；或 ② 直接用 hdiutil 回退（功能完整，仅图标坐标未设，拖拽安装不受影响）；或 ③ 在终端手动运行 create-dmg 命令（终端通常已授权）。

> DMG 不签名（标准 UDZO 压缩只读镜像）。分发时走正式 Developer ID 签名 + 公证。

---

## 9. 修订记录

- v1.0（2026-08-20）：初版。确立 one-file EXE + BUNDLE 结构；固化图标生成、distpath、Info.plist 注入、ad-hoc 签名与 entitlements 流程；记录 `libpython` 错位（坑 1）与 hardened runtime entitlements（坑 2）两大雷点。
- v1.1（2026-08-20）：补充首启体验修复。`app.py` 加 `QLocalServer` 单实例守卫（防多实例/竞争崩溃）、`QSplashScreen` 启动闪屏（防误判崩溃反复双击）、`changeEvent`+`_bring_to_front_macos()` 前台激活（防窗口被压后台）。日志路径更正为 `~/Library/Application Support/logs/`。
- v1.2（2026-08-20）：**one-folder 提速改造**。spec 从 one-file（`exclude_binaries=False` 无 COLLECT）改为标准 one-folder（`exclude_binaries=True` + COLLECT + BUNDLE），二进制全部落磁盘 `Contents/Frameworks`，`_MEIPASS` = `Contents/Resources`（无临时解压）。冷启动从 ~15-20s 降到 ~370ms（实测）。记录 hybrid 混合拆分踩坑（EXTENSION/BINARY co-location 破坏 → rpath 错位 / frozen importer 找不到模块）。构建命令改为命令行 `--distpath dist/macos`（spec 内不再设 `CONF["distpath"]`，避免 EXE/COLLECT 同名冲突）。
- v1.3（2026-08-20）：补充 DMG 打包章节（第 8.5 节）。`scripts/build-dmg.sh` 实跑验证：create-dmg 因 Finder 自动化权限违例（-10004）失败，hdiutil 回退成功生成 81M UDZO DMG（含 toolbox.app + Applications 软链）。记录坑 3（create-dmg 自动化权限）。流程图补充 DMG 步骤。配套文件列表补充 `build-dmg.sh`。
