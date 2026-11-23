#!/usr/bin/env bash
# 还原未打补丁的原始 zcode.cjs（撤掉 adb 补丁）。
# 注意：先完全退出 ZCode 再执行，否则可能被进程占用。
set -e
SRC="${ZCODE_PATCH_DIR:-${USERPROFILE:-$HOME}/.zcode/patches}/zcode.cjs.orig-3.19.0.10774"
DST="E:/ZCode/resources/glm/zcode.cjs"
cp "$SRC" "$DST"
echo "已还原: $DST (原始 3.19.0.10774)"
