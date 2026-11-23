#!/usr/bin/env bash
# ZCode 更新后重新打"放开 adb"补丁（在 Git Bash 里执行）：
#   bash ~/.zcode/patches/re-patch-adb.sh              # 处理已安装的引擎
#   bash ~/.zcode/patches/re-patch-adb.sh <zcode.cjs>   # 只在指定副本上试打并做语法检查，不动已安装的引擎
#
# 适用 3.19.1 起（3.19.1.10833、4.0.0.10870 实测）。从 3.19.1 开始官方不再一律拦截 adb，而是：
#   - 裸 adb 能在 SDK 目录或 PATH 里找到 → 改写成该 adb 的绝对路径后执行；
#   - 找到的 adb 在工作区内 / 哪里都找不到 / 执行适配器不支持解析 → 报错，拒绝执行。
# 本补丁把后三种"报错拒绝"改成"跳过，命令原样交给 shell"，并同步改掉 Bash 工具描述里
# "工作区内 adb 被禁止"的说法。能解析到 SDK adb 时仍照常改写绝对路径。
#
# 三处修改点都只认每版不变的文字（文案、报错消息）做锚点。压缩后的变量名每版会变（如同一条
# 语句里的解析结果 3.19.1 叫 S、4.0.0 叫 v），所以语句类锚点用正则把名字捕获出来，并要求
# 同一条语句里前后一致。要求三处都恰好出现 1 次，或者已经是改后的内容；
# 任何一处找不到或出现多次都中止，不改文件。
#
# 3.19.0 的旧补丁（删除"禁止 adb"文案 + 让识别正则失效）不再适用，备份见
# re-patch-adb.sh.3.19.0.bak：那段文案在新版不存在，而识别正则在新版负责"找到 adb
# 以便改写绝对路径"，让它失效会失去自动改写。

set -u
Z="E:/ZCode/resources/glm/zcode.cjs"
PATCH_DIR="${ZCODE_PATCH_DIR:-${USERPROFILE:-$HOME}/.zcode/patches}"
# 显式传了空路径多半是调用方的失误：报错，而不是悄悄回落到已安装的引擎
[ "$#" -eq 0 ] || [ -n "${1:-}" ] || { echo "路径参数为空（不带参数才是处理已安装的引擎）"; exit 1; }
TARGET="${1:-$Z}"
[ -f "$TARGET" ] || { echo "未找到 $TARGET"; exit 1; }

# 先在副本上改并做语法检查，全部通过后才替换真正的引擎文件
WORK="$(dirname "$TARGET")/.zcode.adb-patch.$$.cjs"
cp "$TARGET" "$WORK" || { echo "复制副本失败，未做任何修改"; exit 1; }

perl -0777 -e '
my $f = $ARGV[0];
open my $in, "<:raw", $f or die "read: $!";
local $/; my $s = <$in>; close $in;

my @edits = (
  {
    name => "Bash 工具描述",
    old  => q{- Workspace-controlled adb executables are blocked. Installed SDK adb outside the workspace is allowed; bare adb},
    new  => q{- adb commands are allowed, including workspace-controlled adb executables; bare adb},
  },
  {
    name => "工作区内 / 找不到 adb 时拒绝执行",
    # 解析结果变量在语句里出现 5 次、报错类命名空间 2 次：用反向引用要求同一条语句里名字一致
    re   => qr#if\(([\w\$]+)\.status!=="resolved"\)throw [\w\$]+\(\1\.status==="workspace"\?([\w\$]+)\.PermissionDenied:\2\.ConfigurationError,\1\.status==="workspace"\?"Workspace-controlled adb execution is blocked\. Use an installed SDK outside the workspace\.":"adb was not found outside the workspace\. Configure Android SDK/PATH or use an installed SDK absolute path\.",\{context:\{reason:\1\.status==="workspace"\?"workspace-adb-blocked":"adb-not-found"\},recoverable:!0\}\);#,
    new  => q{if($1.status!=="resolved")continue;},
    done => qr#if\([\w\$]+\.status!=="resolved"\)continue;#,
  },
  {
    name => "执行适配器不支持解析时拒绝执行",
    re   => qr#if\(!([\w\$]+)\)throw [\w\$]+\([\w\$]+\.ConfigurationError,"Execution adapter cannot resolve adb safely"\);#,
    new  => q{if(!$1)continue;},
    # 新串本身太通用，判断"已打过"要连着前面的方法名一起看
    done => qr#resolveAdbExecutable;if\(![\w\$]+\)continue;#,
  },
);

my ($applied, $already, $problem) = (0, 0, 0);
for my $e (@edits) {
  my $re   = $e->{re}   // qr#\Q$e->{old}\E#;   # 原文：正则，或字面量
  my $done = $e->{done} // qr#\Q$e->{new}\E#;   # 已打过：正则，或字面量
  my ($c, $b, $f, @cap) = (0, 0, 0);
  # 带捕获组的匹配在列表语境下会按组展开，不能用 ()= 计数；匹配变量出了循环就被还原，要在循环内取
  while ($s =~ /$re/g) {
    $c++;
    ($b, $f) = ($-[0], $+[0]);
    @cap = map { substr($s, $-[$_], $+[$_] - $-[$_]) } 1 .. $#-;
  }
  if ($c == 1) {
    (my $new = $e->{new}) =~ s/\$(\d+)/$cap[$1 - 1]/ge;   # 新串里的 $1 换成捕获到的名字
    substr($s, $b, $f - $b) = $new;
    $applied++;
    print "[$e->{name}] 已修改\n";
  } elsif ($c == 0 && $s =~ /$done/) {
    $already++;
    print "[$e->{name}] 已是改后的内容\n";
  } else {
    $problem++;
    print "[$e->{name}] 锚点出现 $c 次（应为 1 次）\n";
  }
}
if ($problem) { die "锚点与预期不符（ZCode 版本可能变了），未修改任何文件\n"; }
if (!$applied) { exit 3; }   # 已经打过补丁

open my $out, ">:raw", $f or die "write: $!";
print $out $s; close $out;
' "$WORK"
RC=$?
if [ "$RC" -eq 3 ]; then
  echo "已经是打过补丁的状态，无需修改"
  rm -f "$WORK"
  exit 0
elif [ "$RC" -ne 0 ]; then
  echo "打补丁失败，未修改任何文件"
  rm -f "$WORK"
  exit 1
fi

NODE=$(command -v node.exe || command -v node || echo "E:/ZCode/resources/glm/node-runtime/node.exe")
if ! "$NODE" --check "$WORK"; then
  echo "语法检查失败！未替换引擎文件"
  rm -f "$WORK"
  exit 1
fi
echo "语法检查通过"

if [ -n "${1:-}" ]; then
  echo "试打完成（仅处理副本）: $WORK"
  echo "已安装的引擎未改动"
  exit 0
fi

VER=$(powershell -NoProfile -Command "(Get-Item 'E:\ZCode\ZCode.exe').VersionInfo.FileVersion" 2>/dev/null | tr -d '\r\n')
ORIG="$PATCH_DIR/zcode.cjs.orig-${VER:-unknown}"
BAK="$PATCH_DIR/zcode.cjs.pre-patch.$(date +%Y%m%d%H%M%S)"
cp "$Z" "$BAK" || { echo "备份失败，未做任何修改"; rm -f "$WORK"; exit 1; }
# 首次给这个版本打补丁时留一份厂商原版；引擎已带有其它补丁（如自动压缩插件 zcode-auto-compact 的）时不算原版
if [ ! -f "$ORIG" ] && ! grep -q -F "zcode-auto-compact" "$Z"; then
  cp "$Z" "$ORIG" && echo "已保存 $VER 的原版引擎: $ORIG（restore-adb.sh 使用）"
fi

if mv -f "$WORK" "$Z" 2>/dev/null; then
  :
else
  if cp "$WORK" "$Z"; then
    rm -f "$WORK"
  else
    echo "替换引擎文件失败（可能被占用），修改前的文件备份在 $BAK"
    rm -f "$WORK"
    exit 1
  fi
fi
echo "补丁完成: $Z"
echo "本次修改前备份: $BAK"
echo "新开的会话才会用上改后的引擎；已经开着的会话保持原样"
