#!/usr/bin/env bash
#
# scripts/build-dmg.sh — 将已构建的 macOS .app 打包成可分发 DMG（含 /Applications 拖拽快捷方式）
#
# 特性：
#   - 优先使用第三方 create-dmg（若已安装）；未安装时打印 brew 安装提示并自动回退到
#     纯原生 hdiutil 方案（无需任何第三方依赖）。
#   - DMG 内含一个指向 /Applications 的符号链接，方便用户拖拽安装。
#   - App 图标置于左侧 (150, 200)，Applications 快捷方式置于右侧 (450, 200)。
#   - 输出文件名：[AppName]-[Version]-macos.dmg，写入 dist/ 目录。
#   - DMG 不签名（ad-hoc，即系统默认的未签名/本地磁盘镜像），无需 Developer ID。
#
# 用法：
#   scripts/build-dmg.sh                                    # 使用默认 .app 与版本
#   APP_PATH="/path/to.app" scripts/build-dmg.sh            # 指定 .app
#   VERSION=2.0.0 scripts/build-dmg.sh                       # 覆盖版本号
#   DMG_BASENAME="MyToolbox" scripts/build-dmg.sh           # 覆盖文件名前缀（默认按 AppName 去空格）
#
set -euo pipefail

# ---- 0. 路径解析 ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_PATH="${APP_PATH:-$PROJECT_ROOT/dist/macos/toolbox.app}"
APP_NAME="${APP_NAME:-toolbox}"
DMG_DIR="${DMG_DIR:-$PROJECT_ROOT/dist}"

# 文件名前缀：默认取自 AppName（当前为 toolbox）；可用 DMG_BASENAME 覆盖。
DMG_BASENAME="${DMG_BASENAME:-${APP_NAME// /-}}"

# ---- 1. 前置检查 ----
if [[ "$(uname)" != "Darwin" ]]; then
  echo "错误：本脚本仅可在 macOS 上运行（需要原生 create-dmg / hdiutil）。" >&2
  exit 1
fi

if [[ ! -d "$APP_PATH" ]]; then
  echo "错误：找不到 .app —— $APP_PATH" >&2
  echo "请先构建：.venv/bin/python -m PyInstaller -y toolbox-macos.spec" >&2
  exit 1
fi

if [[ ! -d "$DMG_DIR" ]]; then
  mkdir -p "$DMG_DIR"
fi

# ---- 2. 解析版本号（优先取 .app Info.plist，可经环境变量覆盖）----
VERSION="${VERSION:-}"
if [[ -z "$VERSION" && -f "$APP_PATH/Contents/Info.plist" ]]; then
  VERSION="$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" \
             "$APP_PATH/Contents/Info.plist" 2>/dev/null || true)"
fi
VERSION="${VERSION:-4.1}"

DMG_NAME="${DMG_BASENAME}-${VERSION}-macos.dmg"
DMG_PATH="$DMG_DIR/$DMG_NAME"

# 体积图标（可选）：若存在则用于 DMG 卷图标
VOL_ICON="$PROJECT_ROOT/assets/app_icon.icns"
[[ -f "$VOL_ICON" ]] || VOL_ICON=""

echo "==> 目标 .app : $APP_PATH"
echo "==> 版本号    : $VERSION"
echo "==> 输出 DMG  : $DMG_PATH"

# 若已存在同名 DMG 先移除，避免 create-dmg/hdiutil 报错
rm -f "$DMG_PATH"

# ---- 3. 路径 A：create-dmg（若存在）----
if command -v create-dmg >/dev/null 2>&1; then
  echo "==> 使用 create-dmg 打包"
  CREATE_DMG_ARGS=(
    --volname "$APP_NAME"
    --window-pos 200 120
    --window-size 620 420
    --icon "$APP_NAME.app" 150 200
    --hide-extension "$APP_NAME.app"
    --app-drop-link 450 200
  )
  if [[ -n "$VOL_ICON" ]]; then
    CREATE_DMG_ARGS+=(--volicon "$VOL_ICON")
  fi

  if ! CREATE_OUT="$(create-dmg "${CREATE_DMG_ARGS[@]}" "$DMG_PATH" "$APP_PATH" 2>&1)"; then
    echo "错误：create-dmg 执行失败，输出如下：" >&2
    echo "$CREATE_OUT" >&2
    exit 1
  fi
  [[ -n "$CREATE_OUT" ]] && echo "$CREATE_OUT"

# ---- 4. 路径 B：纯 hdiutil 回退（未安装 create-dmg 时）----
else
  echo "提示：未检测到 create-dmg。"
  echo "      如需更精致的窗口布局，可先安装：brew install create-dmg"
  echo "==> 回退到原生 hdiutil 方案打包"

  STAGING="$(mktemp -d)"
  TMP_DMG="$(mktemp -d)/tmp.dmg"

  # 4.1 准备暂存目录：复制 .app + 建 /Applications 软链
  cp -R "$APP_PATH" "$STAGING/"
  ln -s /Applications "$STAGING/Applications"

  # 4.2 创建可读写镜像（UDRW）
  if ! hdiutil create -volname "$APP_NAME" -srcfolder "$STAGING" -ov -format UDRW "$TMP_DMG" >/dev/null 2>&1; then
    echo "错误：hdiutil create 失败。" >&2
    rm -rf "$STAGING" "$(dirname "$TMP_DMG")"
    exit 1
  fi

  # 4.3 挂载（不自动打开 Finder，使用受控的挂载点路径以避免卷名含空格导致的解析问题）
  MNT="$(mktemp -d)"
  if ! hdiutil attach "$TMP_DMG" -nobrowse -noautoopen -mountpoint "$MNT" >/dev/null 2>&1; then
    echo "错误：无法挂载临时镜像。" >&2
    rm -rf "$STAGING" "$(dirname "$TMP_DMG")" "$MNT"
    exit 1
  fi

  # 4.4 用 Finder/AppleScript 设置窗口与图标位置（需要 GUI 会话；headless 下尽力而为）
  osascript <<EOF 2>/dev/null || true
    tell application "Finder"
      tell disk "$APP_NAME"
        open
        set current view of container window to icon view
        set toolbar visible of container window to false
        set statusbar visible of container window to false
        set the bounds of container window to {100, 100, 700, 480}
        set theViewOptions to the icon view options of container window
        set arrangement of theViewOptions to not arranged
        set icon size of theViewOptions to 128
        set position of item "$APP_NAME.app" of container window to {150, 200}
        set position of item "Applications" of container window to {450, 200}
        update without registering applications
        delay 1
        close
      end tell
    end tell
EOF

  # 4.5 卸载
  hdiutil detach "$MNT" -force >/dev/null 2>&1 || true

  # 4.6 转换为压缩只读镜像（UDZO，即最终 DMG，未签名）
  if ! hdiutil convert "$TMP_DMG" -format UDZO -o "$DMG_PATH" -ov >/dev/null 2>&1; then
    echo "错误：hdiutil convert 失败。" >&2
    rm -rf "$STAGING" "$(dirname "$TMP_DMG")"
    exit 1
  fi

  # 4.7 清理
  rm -rf "$STAGING" "$(dirname "$TMP_DMG")"
fi

# ---- 5. 校验并报告 ----
if [[ ! -f "$DMG_PATH" ]]; then
  echo "错误：DMG 未成功生成。" >&2
  exit 1
fi

echo "==> 校验 DMG 完整性..."
if hdiutil imageinfo "$DMG_PATH" >/dev/null 2>&1; then
  echo "✅ DMG 已生成：$DMG_PATH"
  echo "   大小：$(du -h "$DMG_PATH" | awk '{print $1}')"
else
  echo "错误：生成的 DMG 无法通过 hdiutil imageinfo 校验。" >&2
  exit 1
fi
