#!/usr/bin/env bash
#
# scripts/sign-adhoc.sh — 对 macOS .app 进行 ad-hoc 本地签名并验证
#
# 特性：
#   - 仅使用 macOS 原生工具（codesign / lipo），不依赖任何第三方签名工具。
#   - 签名命令：codesign --sign - --force --deep --options runtime
#     （ad-hoc 身份「-」+ 递归签名 --deep + 启用 hardened runtime --options runtime）
#   - 签名后自动执行 codesign --verify --verbose=2 验证。
#   - 验证失败时输出具体错误并退出非零。
#   - 兼容 arm64 / x86_64；若 .app 为 Universal Binary，codesign 会一并处理所有架构
#     （脚本用 lipo -info 报告可执行文件的实际架构以供核对）。
#
# 用法：
#   scripts/sign-adhoc.sh                 # 使用默认路径 dist/macos/toolbox.app
#   scripts/sign-adhoc.sh "/path/to.app"  # 指定任意 .app
#
set -euo pipefail

# ---- 0. 路径解析 ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_PATH="${1:-$PROJECT_ROOT/dist/macos/toolbox.app}"

# 可选：entitlements 文件路径（可用环境变量 ENTITLEMENTS 覆盖；默认同目录下的 entitlements.plist）
ENTITLEMENTS="${ENTITLEMENTS:-$SCRIPT_DIR/entitlements.plist}"

# ---- 1. 前置检查 ----
if [[ "$(uname)" != "Darwin" ]]; then
  echo "错误：本脚本仅可在 macOS 上运行（需要原生 codesign / lipo）。" >&2
  exit 1
fi

if [[ ! -d "$APP_PATH" ]]; then
  echo "错误：找不到 .app 包：$APP_PATH" >&2
  echo "请先构建：.venv/bin/python -m PyInstaller toolbox-macos.spec" >&2
  exit 1
fi

echo "==> 目标 .app: $APP_PATH"

# 报告可执行文件架构（lipo 为 macOS 原生工具；Universal Binary 会列出多架构）
MAIN_BIN="$APP_PATH/Contents/MacOS/toolbox"
if [[ -f "$MAIN_BIN" ]] && command -v lipo >/dev/null 2>&1; then
  ARCH_INFO="$(lipo -info "$MAIN_BIN" 2>&1 | sed 's/^Non-fat file:.*architecture: //; s/^Architectures in the fat file:.*are: //')"
  echo "==> 可执行文件架构: $ARCH_INFO"
fi

# ---- 2. ad-hoc 签名（含 hardened runtime，--deep 递归签名所有内部组件与架构）----
# 启用 hardened runtime 时必须附带 entitlements，否则 PyInstaller/PySide6 会因
# 库校验 / JIT / 可执行内存限制而在启动时崩溃（表现为双击后闪烁即退出）。
SIGN_ARGS=(--sign - --force --deep --options runtime)
if [[ -f "$ENTITLEMENTS" ]]; then
  SIGN_ARGS+=(--entitlements "$ENTITLEMENTS")
  echo "==> 使用 entitlements: $ENTITLEMENTS"
else
  echo "警告：未找到 entitlements 文件 ($ENTITLEMENTS)，仅做裸 ad-hoc 签名（hardened runtime 下可能启动崩溃）。" >&2
fi

echo "==> 执行：codesign ${SIGN_ARGS[*]} \"$APP_PATH\""
if ! SIGN_OUT="$(codesign "${SIGN_ARGS[@]}" "$APP_PATH" 2>&1)"; then
  echo "错误：codesign 签名失败，输出如下：" >&2
  echo "$SIGN_OUT" >&2
  exit 1
fi
[[ -n "$SIGN_OUT" ]] && echo "$SIGN_OUT"

# ---- 3. 验证签名 ----
echo "==> 执行：codesign --verify --verbose=2"
if VERIFY_OUT="$(codesign --verify --verbose=2 "$APP_PATH" 2>&1)"; then
  echo "$VERIFY_OUT"
  echo "==> 验证通过：签名有效。"
  exit 0
else
  echo "错误：codesign 验证失败！具体输出如下：" >&2
  echo "----- codesign --verify --verbose=2 输出 -----" >&2
  echo "$VERIFY_OUT" >&2
  echo "------------------------------------------------" >&2
  exit 1
fi
