#!/usr/bin/env bash
# 还原当前所装 ZCode 版本的原版 zcode.cjs（撤掉 adb 补丁）。
# 原版文件按客户端版本号取 zcode.cjs.orig-<版本>（由 re-patch-adb.sh 首次打补丁时保存）；
# 没有对应版本的原版就拒绝，避免把旧版引擎盖进新版客户端。
# 注意：先完全退出 ZCode 再执行，否则可能被进程占用。
# 注意：自动压缩插件（zcode-auto-compact）打在 zcode.cjs 上的引擎补丁也会一并被还原，
#       插件下个会话启动时会自动重新打上。
set -e
DST="${1:-E:/ZCode/resources/glm/zcode.cjs}"
VER=$(powershell -NoProfile -Command "(Get-Item 'E:\ZCode\ZCode.exe').VersionInfo.FileVersion" | tr -d '\r\n')
PATCH_DIR="${ZCODE_PATCH_DIR:-${USERPROFILE:-$HOME}/.zcode/patches}"
SRC="$PATCH_DIR/zcode.cjs.orig-$VER"
[ -f "$SRC" ] || { echo "没有 $VER 的原版备份（$SRC），未做任何修改"; exit 1; }
[ -f "$DST" ] || { echo "未找到 $DST"; exit 1; }
cp "$SRC" "$DST"
echo "已还原: $DST (原始 $VER)"
