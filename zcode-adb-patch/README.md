# zcode-adb-patch · ZCode 引擎 adb 直连补丁（插件）

让 ZCode 的 Bash 工具**不再拒绝它解析不到的 adb 命令**。ZCode 3.19.1 起，裸 `adb` 能在 SDK 目录或 PATH 里找到时会被改写成绝对路径照常执行；找不到时（adb 在工作区内 / 哪里都找不到 / 执行适配器不支持解析）直接拒绝。本插件把三种「拒绝」改成「跳过改写、命令原样交给 shell」，并去掉 Bash 工具描述里「工作区内 adb 被禁止」的说法。

```
引擎 resources/glm/zcode.cjs 里三处 adb 相关语句（含工具描述那一句）→ 可按原文精确还原
```

## 组成

**引擎补丁**：只改三处。锚点只认每版不变的文字（文案、报错消息），语句里压缩后的变量名用正则捕获，所以 ZCode 小版本升级后一般能自动跟上。三处必须要么都是原文、要么都已打过，否则整体拒绝改动（状态显示 `foreign`），不会乱改。

ZCode 升级后，新会话启动时自动重打（SessionStart 钩子）；改完**新开的会话**才生效，已在运行的会话保持原样。

## 命令

```
python hooks/adb_patch.py status               # 查看状态
python hooks/adb_patch.py restore              # 三处改动还原为原文，并停止自动打补丁
python hooks/adb_patch.py config --patch on|off
```

会话里也可以用 `/adb-patch`（或 `/adb-patch restore`）。

## 配置（`~/.zcode/zcode-adb-patch/config.json`）

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `patchEnabled` | `true` | 引擎补丁开关（`restore` 置 `false`） |
| `autoUpdate` | `true` | 新会话检查插件更新（经宿主官方 CLI） |
| `autoUpdateIntervalMinutes` | `60` | 两次自动检查的最小间隔 |

自动更新走 ZCode 自带的 CLI（`plugins marketplace update` + `plugins update`）：新版本先做语法预检，通过才安装；坏版本不装。更新记录在数据目录的 `update.json`。

## 数据目录

`~/.zcode/zcode-adb-patch/`：`config.json`（设置）、`patch-record.json`（补丁记录：打补丁时记下三处原文，`restore` 靠它逐字节放回）、`engine-backup/`（打补丁前的引擎，仅供排查）、`last-run.json`、`update.json`（自动更新记录）。

卸载：先 `restore`，再在 ZCode 设置 → 插件里移除本插件，最后删除数据目录。

## 和别的补丁共存

与 zcode-auto-compact（自动上下文压缩）改的是同一个引擎文件的不同位置，可以共存。本插件替换引擎前会确认文件没被别的进程改过，替换后回读确认，所以两个插件的钩子同时运行也不会互相覆盖。

## 兼容性

引擎补丁已在 Windows 11 + ZCode 3.19.1、4.0.0 的引擎副本上验证（产物与 `re-patch-adb.sh` 脚本的产物逐字节相同）。其它版本若目标代码形状不符，插件会拒绝改动并在状态里指出是哪一处，不会乱改。
