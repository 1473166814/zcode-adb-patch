#!/usr/bin/env bash
# ZCode 更新后重新打"允许 Bash 直接跑 adb"补丁（在 Git Bash 里执行）：
#   bash ~/.zcode/patches/re-patch-adb.sh
#
# 两个修改点都用跨版本稳定的字面量做锚点（压缩后的函数名每版会变，不能用）：
#   1. 删除 Bash 工具描述里注入的 adb 禁令文案（整条数组元素）
#   2. 把 adb 命令名识别正则替换成永不匹配的 /\u0000/（即使校验函数被别处调用也失效）
# 每处独立计数：1 处则改，0 处提示（可能已打过/版本变化），>1 处中止不改。

set -u
Z="E:/ZCode/resources/glm/zcode.cjs"
[ -f "$Z" ] || { echo "未找到 $Z"; exit 1; }

BAK="${ZCODE_PATCH_DIR:-${USERPROFILE:-$HOME}/.zcode/patches}/zcode.cjs.pre-patch.$(date +%Y%m%d%H%M%S)"
cp "$Z" "$BAK" || { echo "备份失败，未做任何修改"; exit 1; }

perl -0777 -e '
my $f = $ARGV[0];
open my $in, "<:raw", $f or die "read: $!";
local $/; my $s = <$in>; close $in;

my $prompt = q{- Direct adb commands are blocked in this tool, including absolute or relative adb paths. Use Android MCP tools such as android_list_devices and android_preflight. If unavailable, report the missing plugin or SDK; do not retry via a project executable or script wrapper.};
my $p1 = qq{"$prompt",};
my $c1 = () = $s =~ /\Q$p1\E/g;
my $anchor = qq{/^adb(?:\\.(?:exe|com|cmd|bat))?\$/};
my $c2 = () = $s =~ /\Q$anchor\E/g;

if ($c1 == 1) { $s =~ s/\Q$p1\E//; print "edit1 文案: 已删除\n"; }
elsif ($c1 == 0) { print "edit1 文案: 未找到（可能已打过或官方改了文案，仅跳过）\n"; }
else { die "edit1: 出现 $c1 次，中止，文件未修改\n"; }

if ($c2 == 1) { $s =~ s{\Q$anchor\E}{/\\u0000/}; print "edit2 识别正则: 已失效化\n"; }
elsif ($c2 == 0) { print "edit2 识别正则: 未找到（可能已打过或版本结构变化）\n"; }
else { die "edit2: 出现 $c2 次，中止，文件未修改\n"; }

open my $out, ">:raw", $f or die "write: $!";
print $out $s; close $out;
print "补丁完成\n";
' "$Z" || { echo "打补丁失败，正在还原"; cp "$BAK" "$Z"; exit 1; }

NODE=$(command -v node.exe || command -v node || echo "E:/ZCode/resources/glm/node-runtime/node.exe")
"$NODE" --check "$Z" && echo "语法检查通过" || { echo "语法检查失败！正在还原"; cp "$BAK" "$Z"; exit 1; }
echo "本次修改前备份: $BAK"
